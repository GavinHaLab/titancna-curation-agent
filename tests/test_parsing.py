import os

from titan_curation.discovery import discover_candidates
from titan_curation.evidence_builder import build_evidence

FIXTURE_ENV = "TITAN_TEST_SAMPLE_DIR"


def test_discover_candidates_smoke(tmp_path):
    # Synthetic minimal fixture: one candidate dir with a params.txt.
    cand_dir = tmp_path / "ploidy2_cluster1"
    cand_dir.mkdir()
    (cand_dir / "sample_cluster1.params.txt").write_text(
        "Normal contamination estimate:\t0.25\n"
        "Average tumour ploidy estimate:\t2.1\n"
        "Clonal cluster cellular prevalence Z=1:\t1\n"
        "Log likelihood:\t-700000\n"
        "S_Dbw validity index (Both):\t0.7\n"
    )
    candidates = discover_candidates(str(tmp_path))
    assert len(candidates) == 1
    assert candidates[0].candidate_id == "ploidy2_cluster1"
    assert candidates[0].requested_ploidy_bin == 2
    assert candidates[0].requested_num_clusters == 1


def test_build_evidence_on_real_sample_if_available(tmp_path):
    sample_dir = os.environ.get(FIXTURE_ENV)
    if not sample_dir or not os.path.isdir(sample_dir):
        return  # skip: no local sample data available in this environment
    evidence = build_evidence(sample_dir, "test_sample", str(tmp_path), top_n=5)
    assert evidence["num_candidates_discovered"] > 0
    assert evidence["all_candidates_ranked"][0]["s_dbw_rank"] == 1
