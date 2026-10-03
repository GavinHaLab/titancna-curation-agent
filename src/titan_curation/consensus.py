"""Merge the two reviewer JSON outputs into one per-sample report + a cohort CSV row."""
from __future__ import annotations

import csv
import fcntl
import os
import threading

# Guards _upsert_cohort_csv_row against concurrent calls from this process's
# own threads (cli.py's --workers uses a ThreadPoolExecutor -- all workers
# share one process). This is required IN ADDITION to the flock below, not
# instead of it: flock() on a networked filesystem (this writes to NFS-
# mounted paths in practice) is not reliably serializing concurrent access
# in all configurations -- confirmed empirically, a real --workers 3 run
# lost 46 of 51 completed samples' rows from the cohort CSV (only the last
# few writers' rows survived a lost-update race) despite the flock. A
# plain in-process Lock is unconditionally correct for same-process threads
# regardless of what the underlying filesystem does with flock, and costs
# nothing extra for the separate-process case (SLURM array jobs), where
# flock remains the only (best-effort) protection.
_CSV_LOCK = threading.Lock()


def _upsert_cohort_csv_row(out_csv: str, row: dict) -> None:
    """Write/replace this sample's row in the shared cohort CSV, keeping at
    most one row per sample_id (a rerun of a sample -- common given transient
    429s/segfaults/etc -- replaces its old row instead of appending a
    duplicate). Safe under concurrent writers from the same process (e.g.
    `--workers N`'s thread pool -- see _CSV_LOCK above) and, best-effort,
    across processes (e.g. a SLURM array job with many tasks writing the
    same --cohort-csv) via an exclusive flock."""
    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    fieldnames = list(row.keys())

    with _CSV_LOCK:
        # Open for read+write, creating if needed, without truncating -- so
        # the lock can be taken before we know whether the file has content.
        with open(out_csv, "a+", newline="") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                existing_rows = list(csv.DictReader(f))
                sample_id = row["sample_id"]
                existing_rows = [r for r in existing_rows if r.get("sample_id") != sample_id]
                existing_rows.append(row)

                f.seek(0)
                f.truncate()
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(existing_rows)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def build_report(
    evidence: dict, claude: dict, second: dict, out_md: str, out_csv: str,
    second_reviewer_label: str,
) -> dict:
    """`second` is the second reviewer's output. `second_reviewer_label`
    (e.g. "GPT-5.5") controls how it's identified in the CSV columns and
    report -- that role has already been swapped once (from Gemini) and
    may be again, so it is never hardcoded to a model name here."""
    sample_id = evidence["sample_id"]
    ranked = evidence["all_candidates_ranked"]
    raw_top = ranked[0]
    top_n = evidence["top_candidates_with_segment_metrics"]

    # Consensus requires all three to agree: the raw TITAN S_Dbw optimum AND
    # both independent reviewers. Any one of the three differing is Discordant.
    consensus_agree = (
        raw_top["candidate_id"] == claude["recommended_candidate_id"] == second["recommended_candidate_id"]
    )
    consensus_candidate = raw_top["candidate_id"] if consensus_agree else None
    status = "Consensus" if consensus_agree else "Discordant"

    # Sanitized to a safe CSV column prefix (e.g. "GPT-5.5" -> "gpt_5_5") --
    # the human-readable second_reviewer_label is used as-is in headings/text.
    col = "".join(ch if ch.isalnum() else "_" for ch in second_reviewer_label.lower())

    row = {
        "sample_id": sample_id,
        "raw_titan_optimal_candidate": raw_top["candidate_id"],
        "raw_titan_ploidy": raw_top["ploidy"],
        "raw_titan_purity": raw_top["titan_purity"],
        "raw_titan_sdbw": raw_top["s_dbw_both"],
        "claude_candidate": claude["recommended_candidate_id"],
        "claude_ploidy": claude["recommended_ploidy"],
        "claude_purity": claude["recommended_titan_purity"],
        "claude_overrides_raw": claude.get("overrides_raw_titan_optimal"),
        "claude_comment": (claude.get("comment") or "").replace("\n", " ")[:600],
        f"{col}_candidate": second["recommended_candidate_id"],
        f"{col}_ploidy": second["recommended_ploidy"],
        f"{col}_purity": second["recommended_titan_purity"],
        f"{col}_overrides_raw": second.get("overrides_raw_titan_optimal"),
        f"{col}_comment": (second.get("comment") or "").replace("\n", " ")[:600],
        "consensus_candidate": consensus_candidate or "DISCORDANT",
        "consensus_ploidy": raw_top["ploidy"] if consensus_agree else "",
        "consensus_purity": raw_top["titan_purity"] if consensus_agree else "",
        "status": status,
    }

    _upsert_cohort_csv_row(out_csv, row)

    lines = []
    lines.append(f"# TITAN Curation Report -- {sample_id}\n")
    lines.append("Generated by the TitanCNA Curation Agent CLI "
                  f"(deterministic parsing + independent Claude + {second_reviewer_label} review).\n")

    lines.append("## Summary\n")
    lines.append("| Sample | Raw TITAN optimal (S_Dbw) | Raw purity | Claude rec. | Claude purity | "
                  f"{second_reviewer_label} rec. | {second_reviewer_label} purity | Consensus | Status |")
    lines.append("|---|---|---:|---|---:|---|---:|---|---|")
    lines.append(
        f"| {sample_id} | {raw_top['candidate_id']} | {raw_top['titan_purity']} | "
        f"{claude['recommended_candidate_id']} | {claude['recommended_titan_purity']} | "
        f"{second['recommended_candidate_id']} | {second['recommended_titan_purity']} | "
        f"{consensus_candidate or 'DISCORDANT'} | {status} |\n"
    )

    lines.append("## Candidate detail\n")
    lines.append("| Rank | Candidate | Ploidy | Clusters | Purity | S_Dbw | Log-lik | "
                  f"Genome altered | Subclonal | Segments | Claude verdict | {second_reviewer_label} verdict |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
    claude_verdicts = {c["candidate_id"]: c["verdict"] for c in claude.get("ranked_candidates", [])}
    second_verdicts = {c["candidate_id"]: c["verdict"] for c in second.get("ranked_candidates", [])}
    for c in top_n:
        sm = c.get("segment_metrics") or {}
        fga = sm.get("fraction_genome_altered")
        fsc = sm.get("fraction_genome_subclonal")
        loglik = c["log_likelihood"]
        lines.append(
            f"| {c['s_dbw_rank']} | {c['candidate_id']} | {c['ploidy']} | {c['requested_num_clusters']} | "
            f"{c['titan_purity']} | {c['s_dbw_both']} | {loglik:.0f} | "
            f"{fga:.1%} | {fsc:.1%} | {sm.get('num_segments')} | "
            f"{claude_verdicts.get(c['candidate_id'], '-')} | {second_verdicts.get(c['candidate_id'], '-')} |"
        )
    lines.append("")

    lines.append("## Reviewer comments\n")
    lines.append(f"### Claude (overrides raw optimum: {claude.get('overrides_raw_titan_optimal')})\n")
    lines.append((claude.get("comment") or "") + "\n")
    lines.append(f"### {second_reviewer_label} (overrides raw optimum: {second.get('overrides_raw_titan_optimal')})\n")
    lines.append((second.get("comment") or "") + "\n")

    lines.append("## Flags\n")
    all_flags = [("claude", f) for f in claude.get("flags", [])] + \
        [(second_reviewer_label, f) for f in second.get("flags", [])]
    if all_flags:
        lines.append("| Reviewer | Type | Severity | Evidence |")
        lines.append("|---|---|---|---|")
        for reviewer, f in all_flags:
            lines.append(f"| {reviewer} | {f.get('type')} | {f.get('severity')} | {f.get('evidence')} |")
    else:
        lines.append("No flags raised.")
    lines.append("")

    human_review_focus_items = (
        [("Claude", item) for item in (claude.get("human_review_focus") or [])]
        + [(second_reviewer_label, item) for item in (second.get("human_review_focus") or [])]
    )
    if human_review_focus_items:
        lines.append("## Human review focus\n")
        for reviewer, item in human_review_focus_items:
            lines.append(f"- ({reviewer}) {item}")
        lines.append("")

    os.makedirs(os.path.dirname(out_md) or ".", exist_ok=True)
    with open(out_md, "w") as f:
        f.write("\n".join(lines))

    return row
