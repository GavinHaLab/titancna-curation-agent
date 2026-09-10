"""Command-line entry point: titan-curate run --input <path> --out <dir>."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .config import resolve_config
from .consensus import build_report
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
        chroms = ambiguity_chroms if c["candidate_id"] in ambiguous_ids else None
        plots = select_plots_for_candidate(c["plot_dir"], evidence["sample_id"], cache_root, chromosomes=chroms)
        for suffix, path in plots["genome_wide"].items():
            labeled_images.append((f"{c['candidate_id']} - genome-wide {suffix}", path))
        for chrom, path in plots["per_chromosome"].items():
            labeled_images.append((f"{c['candidate_id']} - {chrom} zoom", path))
    return labeled_images


def cmd_run(args: argparse.Namespace) -> int:
    sample_id = args.sample_id or os.path.basename(os.path.normpath(args.input))
    out_dir = args.out or os.path.join("results", sample_id)
    evidence_dir = os.path.join(out_dir, "evidence")
    reviews_dir = os.path.join(out_dir, "reviews")
    reports_dir = os.path.join(out_dir, "reports") if not args.cohort_csv else os.path.dirname(args.cohort_csv) or "."
    os.makedirs(out_dir, exist_ok=True)

    print(f"[1/4] Discovering + ranking candidates under {args.input} ...")
    evidence = build_evidence(args.input, sample_id, evidence_dir, top_n=args.top_n)
    print(f"  found {evidence['num_candidates_discovered']} candidates.")
    top = evidence["top_candidates_with_segment_metrics"]
    for c in top:
        print(f"  rank {c['s_dbw_rank']}: {c['candidate_id']:20s} ploidy={c['ploidy']:.3f}  "
              f"purity={c['titan_purity']}  S_Dbw={c['s_dbw_both']}  loglik={c['log_likelihood']:.0f}")
    for amb in evidence.get("ploidy_doubling_ambiguity_flags", []):
        print(f"  ploidy-doubling ambiguity: {amb['candidate_a']} (ploidy {amb['ploidy_a']}) vs "
              f"{amb['candidate_b']} (ploidy {amb['ploidy_b']}), S_Dbw gap {amb['s_dbw_gap']}")

    if args.dry_run:
        print("\n--dry-run set: skipping plot selection and model review. "
              f"Evidence saved under {evidence_dir}/")
        return 0

    print("\n[2/4] Selecting genome-wide (+ ambiguity per-chromosome) plots ...")
    labeled_images = _gather_labeled_images(evidence, out_dir, args.ambiguity_chromosomes)
    print(f"  selected {len(labeled_images)} images (top {args.top_n} candidates only).")

    cfg = resolve_config(
        config_path=args.config,
        anthropic_key_flag=args.anthropic_key,
        gemini_key_flag=args.gemini_key,
        anthropic_model_flag=args.anthropic_model,
        gemini_model_flag=args.gemini_model,
    )

    knowledge_dir = args.knowledge_dir or os.path.join(os.path.dirname(__file__), "knowledge")
    knowledge_dir = os.path.abspath(knowledge_dir)

    os.makedirs(reviews_dir, exist_ok=True)
    claude_review = None
    gemini_review = None

    print("\n[3/4] Running independent reviewers ...")
    if cfg.has_claude() and not args.skip_claude:
        from .reviewers import claude_reviewer
        print(f"  Claude ({cfg.anthropic_model}) reviewing ...")
        claude_review = claude_reviewer.review(
            evidence, top, labeled_images, knowledge_dir, cfg.anthropic_api_key, cfg.anthropic_model,
        )
        with open(os.path.join(reviews_dir, "claude_review.json"), "w") as f:
            json.dump(claude_review, f, indent=2)
        print(f"    -> recommends {claude_review.get('recommended_candidate_id')}")
    else:
        print("  Skipping Claude (no ANTHROPIC_API_KEY / --anthropic-key provided, or --skip-claude set).")

    if cfg.has_gemini() and not args.skip_gemini:
        from .reviewers import gemini_reviewer
        print(f"  Gemini ({cfg.gemini_model}) reviewing ...")
        gemini_review = gemini_reviewer.review(
            evidence, top, labeled_images, knowledge_dir, cfg.gemini_api_key, cfg.gemini_model,
        )
        with open(os.path.join(reviews_dir, "gemini_review.json"), "w") as f:
            json.dump(gemini_review, f, indent=2)
        print(f"    -> recommends {gemini_review.get('recommended_candidate_id')}")
    else:
        print("  Skipping Gemini (no GEMINI_API_KEY / --gemini-key provided, or --skip-gemini set).")

    if not claude_review and not gemini_review:
        print("\nNo reviewer ran (missing API keys). Provide --anthropic-key/--gemini-key, "
              "set ANTHROPIC_API_KEY/GEMINI_API_KEY, or use --config. Evidence-only output is in "
              f"{evidence_dir}/.")
        return 1

    if not (claude_review and gemini_review):
        print("\nOnly one reviewer ran -- skipping the merged consensus report (needs both). "
              "Its individual review JSON has been saved above.")
        return 0

    print("\n[4/4] Building consensus report ...")
    out_md = os.path.join(reports_dir, f"{sample_id}_curation_report.md")
    out_csv = args.cohort_csv or os.path.join(reports_dir, "cohort_titan_curation_summary.csv")
    row = build_report(evidence, claude_review, gemini_review, out_md, out_csv)
    print(f"  consensus candidate: {row['consensus_candidate']}  |  status: {row['status']}")
    print(f"\nDone. Wrote:\n  {out_md}\n  {out_csv}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="titan-curate", description="TitanCNA Curation Agent CLI")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the full curation pipeline on a local sample folder")
    run.add_argument("--input", required=True, help="Path to a TITAN HMM sample folder "
                      "(containing ploidyN_clusterM subfolders), or a single candidate folder")
    run.add_argument("--out", default=None, help="Output directory (default: results/<sample_id>)")
    run.add_argument("--sample-id", default=None, help="Sample ID (default: input folder name)")
    run.add_argument("--top-n", type=int, default=5, help="How many top S_Dbw candidates to visually review (default 5)")
    run.add_argument("--ambiguity-chromosomes", nargs="*", default=DEFAULT_AMBIGUITY_CHROMS,
                      help="Chromosomes to zoom into for ploidy-doubling-ambiguous pairs")
    run.add_argument("--cohort-csv", default=None, help="Path to append the cohort summary row to "
                      "(default: <out>/reports/cohort_titan_curation_summary.csv)")
    run.add_argument("--knowledge-dir", default=None, help="Override path to knowledge/ "
                      "(skills.md, titan_reference.md); defaults to the bundled knowledge/ directory")
    run.add_argument("--config", default=None, help="Optional YAML config file with API keys/models "
                      "(see config/config.example.yaml)")
    run.add_argument("--anthropic-key", default=None, help="Overrides ANTHROPIC_API_KEY env var")
    run.add_argument("--gemini-key", default=None, help="Overrides GEMINI_API_KEY/GOOGLE_API_KEY env var")
    run.add_argument("--anthropic-model", default=None, help="Overrides ANTHROPIC_MODEL env var")
    run.add_argument("--gemini-model", default=None, help="Overrides GEMINI_MODEL env var")
    run.add_argument("--skip-claude", action="store_true", help="Don't run the Claude reviewer even if a key is present")
    run.add_argument("--skip-gemini", action="store_true", help="Don't run the Gemini reviewer even if a key is present")
    run.add_argument("--dry-run", action="store_true", help="Only run deterministic parsing/ranking; no plots, no model calls")
    run.set_defaults(func=cmd_run)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
