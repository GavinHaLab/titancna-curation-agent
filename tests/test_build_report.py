import csv

from titan_curation.consensus import build_report


def _evidence(raw_top_id="ploidy2_cluster1", ploidy=2.0, purity=0.3, sdbw=0.7):
    top = {
        "candidate_id": raw_top_id,
        "ploidy": ploidy,
        "requested_num_clusters": 1,
        "titan_purity": purity,
        "s_dbw_both": sdbw,
        "s_dbw_rank": 1,
        "log_likelihood": -700000,
        "segment_metrics": {
            "fraction_genome_altered": 0.2,
            "fraction_genome_subclonal": 0.0,
            "num_segments": 10,
        },
    }
    return {
        "sample_id": "sampleA",
        "all_candidates_ranked": [top],
        "top_candidates_with_segment_metrics": [top],
    }


def _review(candidate_id, ploidy=2.0, purity=0.3, **extra):
    return {
        "recommended_candidate_id": candidate_id,
        "recommended_ploidy": ploidy,
        "recommended_titan_purity": purity,
        "comment": "test comment",
        "ranked_candidates": [],
        "flags": [],
        **extra,
    }


def _read_row(csv_path):
    with open(csv_path, newline="") as f:
        return next(csv.DictReader(f))


def test_consensus_when_all_three_agree(tmp_path):
    evidence = _evidence(raw_top_id="ploidy2_cluster1")
    claude = _review("ploidy2_cluster1")
    second = _review("ploidy2_cluster1")
    out_md = str(tmp_path / "report.md")
    out_csv = str(tmp_path / "cohort.csv")

    row = build_report(evidence, claude, second, out_md, out_csv, second_reviewer_label="GPT-5.5")

    assert row["status"] == "Consensus"
    assert row["consensus_candidate"] == "ploidy2_cluster1"
    assert _read_row(out_csv)["status"] == "Consensus"


def test_discordant_when_claude_differs_from_raw_optimum(tmp_path):
    """Claude and the second reviewer agreeing with EACH OTHER is not enough
    -- they must also agree with the raw TITAN S_Dbw optimum, or it's
    Discordant."""
    evidence = _evidence(raw_top_id="ploidy2_cluster1")
    claude = _review("ploidy3_cluster1")
    second = _review("ploidy3_cluster1")
    out_md = str(tmp_path / "report.md")
    out_csv = str(tmp_path / "cohort.csv")

    row = build_report(evidence, claude, second, out_md, out_csv, second_reviewer_label="GPT-5.5")

    assert row["status"] == "Discordant"
    assert row["consensus_candidate"] == "DISCORDANT"


def test_discordant_when_only_second_reviewer_differs(tmp_path):
    evidence = _evidence(raw_top_id="ploidy2_cluster1")
    claude = _review("ploidy2_cluster1")
    second = _review("ploidy3_cluster1")
    out_md = str(tmp_path / "report.md")
    out_csv = str(tmp_path / "cohort.csv")

    row = build_report(evidence, claude, second, out_md, out_csv, second_reviewer_label="GPT-5.5")

    assert row["status"] == "Discordant"


def test_no_confidence_or_human_review_columns(tmp_path):
    evidence = _evidence()
    claude = _review("ploidy2_cluster1", confidence="high", human_review_needed=True)
    second = _review("ploidy2_cluster1", confidence="low", human_review_needed=True)
    out_md = str(tmp_path / "report.md")
    out_csv = str(tmp_path / "cohort.csv")

    row = build_report(evidence, claude, second, out_md, out_csv, second_reviewer_label="GPT-5.5")

    for key in ("claude_confidence", "gpt_5_5_confidence", "human_review_needed"):
        assert key not in row

    header = _read_row(out_csv).keys()
    for key in ("claude_confidence", "gpt_5_5_confidence", "human_review_needed"):
        assert key not in header


def test_report_markdown_has_no_confidence_or_always_true_human_review_line(tmp_path):
    evidence = _evidence()
    claude = _review("ploidy2_cluster1", confidence="high")
    second = _review("ploidy2_cluster1", confidence="low")
    out_md = str(tmp_path / "report.md")
    out_csv = str(tmp_path / "cohort.csv")

    build_report(evidence, claude, second, out_md, out_csv, second_reviewer_label="GPT-5.5")

    with open(out_md) as f:
        text = f.read()
    assert "confidence" not in text.lower()
    assert "Overall human review needed" not in text


def test_second_reviewer_label_renames_columns_and_headings(tmp_path):
    """Regression test for the Gemini -> GPT-5.5 swap: nothing in the CSV
    columns or report should say "gemini" -- the label is always threaded
    through explicitly, never defaulted to a specific model name."""
    evidence = _evidence()
    claude = _review("ploidy2_cluster1")
    second = _review("ploidy2_cluster1", flags=[{"type": "other", "severity": "low", "evidence": "x"}],
                      human_review_focus=["check this"])
    out_md = str(tmp_path / "report.md")
    out_csv = str(tmp_path / "cohort.csv")

    row = build_report(evidence, claude, second, out_md, out_csv, second_reviewer_label="GPT-5.5")

    # CSV columns are sanitized (dots/dashes -> underscores), not "gemini".
    for key in ("gpt_5_5_candidate", "gpt_5_5_ploidy", "gpt_5_5_purity",
                "gpt_5_5_overrides_raw", "gpt_5_5_comment"):
        assert key in row
    assert "gemini_candidate" not in row

    header = _read_row(out_csv).keys()
    assert "gpt_5_5_candidate" in header
    assert "gemini_candidate" not in header

    with open(out_md) as f:
        text = f.read()
    assert "### GPT-5.5 (" in text
    assert "GPT-5.5 rec." in text  # Summary table header
    assert "GPT-5.5 verdict" in text  # Candidate detail table header
    assert "(GPT-5.5) check this" in text  # Human review focus bullet
    assert "| GPT-5.5 | other | low | x |" in text  # Flags table row
    assert "gemini" not in text.lower()
