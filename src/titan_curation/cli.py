"""Command-line entry point: titan-curate run --input <path> [sample selection] [--out <dir>]."""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from .config import resolve_config
from .consensus import build_report
from .discovery import is_cohort_root, list_available_samples
from .evidence_builder import build_evidence
from .plots import select_plots_for_candidate

DEFAULT_AMBIGUITY_CHROMS = ["chr4", "chr7", "chr8", "chr12"]


def _gather_labeled_images(evidence: dict, out_dir: str, ambiguity_chroms: list[str]) -> list[tuple[str, str]]:
    cache_root = os.path.join(out_dir, ".plot_cache")
    top_candidates = evidence["top_candidates_with_segment_metrics"]
    ambiguous_ids = set()
    for amb in evidence.get("ploidy_doubling_ambiguity_flags", []):
        ambiguous_ids.add(amb["candidate_a"])
        ambiguous_ids.add(amb["candidate_b"])

    labeled_images: list[tuple[str, str]] = []
    for c in top_candidates:
        if not c.get("plot_dir"):
            continue
        chroms = ambiguity_chroms if c["candidate_id"] in ambiguous_ids else None
        plots = select_plots_for_candidate(c["plot_dir"], evidence["sample_id"], cache_root, chromosomes=chroms)
        for suffix, path in plots["genome_wide"].items():
            labeled_images.append((f"{c['candidate_id']} - genome-wide {suffix}", path))
        for chrom, path in plots["per_chromosome"].items():
            labeled_images.append((f"{c['candidate_id']} - {chrom} zoom", path))
    return labeled_images


def _resolve_sample_ids(args: argparse.Namespace) -> list[str]:
    """Figure out which sample(s) to run, from --sample / --samples /
    --sample-list-file / --all-samples, or (legacy) a bare single-sample
    folder that needs no sample selection at all (returns [None])."""
    explicit_modes = [args.sample, args.samples, args.sample_list_file, args.all_samples]
    num_set = sum(1 for m in explicit_modes if m)
    if num_set > 1:
        raise SystemExit("Specify at most one of --sample / --samples / --sample-list-file / --all-samples.")

    if args.sample:
        return [args.sample]
    if args.samples:
        return [s.strip() for s in args.samples.split(",") if s.strip()]
    if args.sample_list_file:
        with open(args.sample_list_file) as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    if args.all_samples:
        samples = list_available_samples(args.input)
        if not samples:
            raise SystemExit(f"--all-samples: found no samples under {args.input} "
                              "(expected titanCNA_ploidyN/ subdirectories).")
        return samples

    # No explicit sample selection given.
    if is_cohort_root(args.input):
        raise SystemExit(
            f"'{args.input}' is a cohort root with multiple samples -- specify one of "
            "--sample <name>, --samples name1,name2, --sample-list-file <path>, or --all-samples."
        )
    # Legacy layout: the input folder itself is a single sample.
    return [None]


def _run_one_sample(input_path: str, sample_id: str | None, args: argparse.Namespace,
                     cfg, knowledge_dir: str, cohort_csv: str) -> dict:
    """Run the full pipeline for one sample. Returns a small status dict.
    Raises on unrecoverable errors -- callers in batch mode should catch and
    continue with the next sample."""
    resolved_sample_id = sample_id or os.path.basename(os.path.normpath(input_path))
    out_dir = os.path.join(args.out_root, resolved_sample_id) if args.out_root else \
        (args.out or os.path.join("results", resolved_sample_id))
    evidence_dir = os.path.join(out_dir, "evidence")
    reviews_dir = os.path.join(out_dir, "reviews")
    reports_dir = os.path.join(out_dir, "reports")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n=== Sample: {resolved_sample_id} ===")
    print(f"[1/4] Discovering + ranking candidates under {input_path} ...")
    evidence = build_evidence(input_path, resolved_sample_id, evidence_dir, top_n=args.top_n)
    print(f"  found {evidence['num_candidates_discovered']} candidates.")
    top = evidence["top_candidates_with_segment_metrics"]
    for c in top:
        print(f"  rank {c['s_dbw_rank']}: {c['candidate_id']:20s} ploidy={c['ploidy']:.3f}  "
              f"purity={c['titan_purity']}  S_Dbw={c['s_dbw_both']}  loglik={c['log_likelihood']:.0f}")
    for amb in evidence.get("ploidy_doubling_ambiguity_flags", []):
        print(f"  ploidy-doubling ambiguity: {amb['candidate_a']} (ploidy {amb['ploidy_a']}) vs "
              f"{amb['candidate_b']} (ploidy {amb['ploidy_b']}), S_Dbw gap {amb['s_dbw_gap']}")

    if args.dry_run:
        print(f"  --dry-run set: skipping plot selection and model review. Evidence saved under {evidence_dir}/")
        return {"sample_id": resolved_sample_id, "status": "dry-run"}

    print("[2/4] Selecting genome-wide (+ ambiguity per-chromosome) plots ...")
    labeled_images = _gather_labeled_images(evidence, out_dir, args.ambiguity_chromosomes)
    print(f"  selected {len(labeled_images)} images (top {args.top_n} candidates only).")

    os.makedirs(reviews_dir, exist_ok=True)
    claude_review = None
    gemini_review = None
    backend = cfg.resolved_backend()

    print(f"[3/4] Running independent reviewers (backend: {backend}) ...")
    if cfg.has_claude() and not args.skip_claude:
        if backend == "perplexity":
            from .reviewers import perplexity_reviewer
            print(f"  Claude role via Perplexity API ({cfg.perplexity_claude_model}) reviewing ...")
            claude_review = perplexity_reviewer.review(
                evidence, top, labeled_images, knowledge_dir, cfg.perplexity_api_key,
                cfg.perplexity_claude_model, reviewer_name="claude_sonnet",
            )
        else:
            from .reviewers import claude_reviewer
            print(f"  Claude ({cfg.anthropic_model}) reviewing ...")
            claude_review = claude_reviewer.review(
                evidence, top, labeled_images, knowledge_dir, cfg.anthropic_api_key, cfg.anthropic_model,
            )
        with open(os.path.join(reviews_dir, "claude_review.json"), "w") as f:
            json.dump(claude_review, f, indent=2)
        print(f"    -> recommends {claude_review.get('recommended_candidate_id')}")
    else:
        print("  Skipping Claude (no key for the active backend, or --skip-claude set).")

    if cfg.has_gemini() and not args.skip_gemini:
        if backend == "perplexity":
            from .reviewers import perplexity_reviewer
            print(f"  Gemini role via Perplexity API ({cfg.perplexity_gemini_model}) reviewing ...")
            gemini_review = perplexity_reviewer.review(
                evidence, top, labeled_images, knowledge_dir, cfg.perplexity_api_key,
                cfg.perplexity_gemini_model, reviewer_name="gemini",
            )
        else:
            from .reviewers import gemini_reviewer
            print(f"  Gemini ({cfg.gemini_model}) reviewing ...")
            gemini_review = gemini_reviewer.review(
                evidence, top, labeled_images, knowledge_dir, cfg.gemini_api_key, cfg.gemini_model,
            )
        with open(os.path.join(reviews_dir, "gemini_review.json"), "w") as f:
            json.dump(gemini_review, f, indent=2)
        print(f"    -> recommends {gemini_review.get('recommended_candidate_id')}")
    else:
        print("  Skipping Gemini (no key for the active backend, or --skip-gemini set).")

    if not claude_review and not gemini_review:
        print(f"  No reviewer ran for {resolved_sample_id} (missing API keys). "
              f"Evidence-only output is in {evidence_dir}/.")
        return {"sample_id": resolved_sample_id, "status": "no-reviewers"}

    if not (claude_review and gemini_review):
        print("  Only one reviewer ran -- skipping the merged consensus report (needs both). "
              "Its individual review JSON has been saved above.")
        return {"sample_id": resolved_sample_id, "status": "single-reviewer-only"}

    print("[4/4] Building consensus report ...")
    out_md = os.path.join(reports_dir, f"{resolved_sample_id}_curation_report.md")
    row = build_report(evidence, claude_review, gemini_review, out_md, cohort_csv)
    print(f"  consensus candidate: {row['consensus_candidate']}  |  status: {row['status']}")
    print(f"  Wrote:\n    {out_md}\n    {cohort_csv}")
    return {"sample_id": resolved_sample_id, "status": "ok", "row": row, "report": out_md}


def cmd_run(args: argparse.Namespace) -> int:
    sample_ids = _resolve_sample_ids(args)
    is_batch = len(sample_ids) > 1

    cohort_csv = args.cohort_csv or (
        os.path.join(args.out_root, "cohort_titan_curation_summary.csv") if args.out_root
        else os.path.join("results", "cohort_titan_curation_summary.csv")
    )

    cfg = resolve_config(
        config_path=args.config,
        anthropic_key_flag=args.anthropic_key,
        gemini_key_flag=args.gemini_key,
        anthropic_model_flag=args.anthropic_model,
        gemini_model_flag=args.gemini_model,
        backend_flag=args.backend,
        perplexity_key_flag=args.perplexity_key,
        perplexity_claude_model_flag=args.perplexity_claude_model,
        perplexity_gemini_model_flag=args.perplexity_gemini_model,
    )
    knowledge_dir = args.knowledge_dir or os.path.join(os.path.dirname(__file__), "knowledge")
    knowledge_dir = os.path.abspath(knowledge_dir)

    if is_batch:
        print(f"Batch mode: {len(sample_ids)} sample(s) under {args.input}")

    results = []
    failures = []
    for sample_id in sample_ids:
        try:
            results.append(_run_one_sample(args.input, sample_id, args, cfg, knowledge_dir, cohort_csv))
        except Exception as e:
            label = sample_id or os.path.basename(os.path.normpath(args.input))
            print(f"\n[FAILED] {label}: {e}", file=sys.stderr)
            if args.verbose_errors:
                traceback.print_exc()
            failures.append({"sample_id": label, "error": str(e)})
            if not is_batch:
                return 1
            continue

    if is_batch:
        completed = len(results)  # ran without raising, regardless of status
        with_report = sum(1 for r in results if r.get("status") == "ok")
        print(f"\n=== Batch summary: {completed}/{len(sample_ids)} samples processed "
              f"({with_report} with a full consensus report, {len(failures)} failed) ===")
        for r in results:
            if r.get("status") != "ok":
                print(f"  {r['sample_id']}: {r['status']}")
        for f in failures:
            print(f"  FAILED: {f['sample_id']}: {f['error']}")
        if with_report > 0:
            print(f"Cohort CSV: {cohort_csv}")
        return 1 if failures and completed == 0 else 0

    return 0 if not failures else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="titan-curate", description="TitanCNA Curation Agent CLI")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the curation pipeline for one or many samples")
    run.add_argument("--input", required=True,
                      help="Path to a TITAN cohort root (containing titanCNA_ploidy2/3/4/ "
                           "directories -- use with --sample/--samples/--sample-list-file/--all-samples), "
                           "or a legacy single-sample folder (containing ploidyN_clusterM/ subfolders)")

    sample_group = run.add_mutually_exclusive_group()
    sample_group.add_argument("--sample", default=None, help="Single sample name to run (cohort-root mode)")
    sample_group.add_argument("--samples", default=None,
                               help="Comma-separated list of sample names to run in batch")
    sample_group.add_argument("--sample-list-file", default=None,
                               help="Path to a text file with one sample name per line")
    sample_group.add_argument("--all-samples", action="store_true",
                               help="Auto-discover and run every sample found under --input")

    run.add_argument("--out", default=None, help="Output directory for a single sample "
                      "(default: results/<sample_id>); ignored in batch mode")
    run.add_argument("--out-root", default=None,
                      help="Output root for batch mode: each sample writes to <out-root>/<sample_id>/ "
                           "(default: results/)")
    run.add_argument("--top-n", type=int, default=5, help="How many top S_Dbw candidates to visually review (default 5)")
    run.add_argument("--ambiguity-chromosomes", nargs="*", default=DEFAULT_AMBIGUITY_CHROMS,
                      help="Chromosomes to zoom into for ploidy-doubling-ambiguous pairs")
    run.add_argument("--cohort-csv", default=None, help="Path to append every sample's summary row to "
                      "(default: <out-root or results>/cohort_titan_curation_summary.csv)")
    run.add_argument("--knowledge-dir", default=None, help="Override path to knowledge/ "
                      "(skills.md, titan_reference.md); defaults to the bundled knowledge/ directory")
    run.add_argument("--config", default=None, help="Optional YAML config file with API keys/models "
                      "(see config/config.example.yaml)")

    run.add_argument("--backend", choices=["auto", "direct", "perplexity"], default=None,
                      help="Reviewer transport: 'direct' calls Anthropic/Google APIs directly, "
                           "'perplexity' routes both reviewer roles through one Perplexity API key, "
                           "'auto' (default) picks perplexity if PERPLEXITY_API_KEY is set, else direct")
    run.add_argument("--perplexity-key", default=None, help="Overrides PERPLEXITY_API_KEY env var")
    run.add_argument("--perplexity-claude-model", default=None,
                      help="Perplexity provider/model id for the Claude reviewer role "
                           "(default: anthropic/claude-sonnet-5)")
    run.add_argument("--perplexity-gemini-model", default=None,
                      help="Perplexity provider/model id for the Gemini reviewer role "
                           "(default: google/gemini-3.1-pro-preview)")

    run.add_argument("--anthropic-key", default=None, help="Overrides ANTHROPIC_API_KEY env var (direct backend)")
    run.add_argument("--gemini-key", default=None, help="Overrides GEMINI_API_KEY/GOOGLE_API_KEY env var (direct backend)")
    run.add_argument("--anthropic-model", default=None, help="Overrides ANTHROPIC_MODEL env var (direct backend)")
    run.add_argument("--gemini-model", default=None, help="Overrides GEMINI_MODEL env var (direct backend)")

    run.add_argument("--skip-claude", action="store_true", help="Don't run the Claude reviewer role even if a key is present")
    run.add_argument("--skip-gemini", action="store_true", help="Don't run the Gemini reviewer role even if a key is present")
    run.add_argument("--dry-run", action="store_true", help="Only run deterministic parsing/ranking; no plots, no model calls")
    run.add_argument("--verbose-errors", action="store_true", help="Print full tracebacks for per-sample failures in batch mode")
    run.set_defaults(func=cmd_run)

    list_cmd = sub.add_parser("list-samples", help="List every sample name discoverable under a cohort root")
    list_cmd.add_argument("--input", required=True, help="Path to a TITAN cohort root (titanCNA_ploidyN/ directories)")
    list_cmd.set_defaults(func=cmd_list_samples)

    return p


def cmd_list_samples(args: argparse.Namespace) -> int:
    if not is_cohort_root(args.input):
        print(f"'{args.input}' does not look like a cohort root (no titanCNA_ploidyN/ directories found).")
        return 1
    samples = list_available_samples(args.input)
    print(f"{len(samples)} sample(s) found under {args.input}:")
    for s in samples:
        print(f"  {s}")
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
