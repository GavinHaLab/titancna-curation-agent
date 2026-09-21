import os

from titan_curation.discovery import (
    discover_candidates,
    discover_candidates_auto,
    discover_candidates_for_sample,
    is_cohort_root,
    list_available_samples,
)
from titan_curation.evidence_builder import build_evidence

FIXTURE_ENV = "TITAN_TEST_SAMPLE_DIR"
COHORT_FIXTURE_ENV = "TITAN_TEST_COHORT_DIR"


def _write_params(path, sdbw=0.7):
    path.write_text(
        "Normal contamination estimate:\t0.25\n"
        "Average tumour ploidy estimate:\t2.1\n"
        "Clonal cluster cellular prevalence Z=1:\t1\n"
        "Log likelihood:\t-700000\n"
        f"S_Dbw validity index (Both):\t{sdbw}\n"
    )


def _write_segs(path):
    path.write_text(
        "Sample\tChromosome\tStart_Position.bp.\tEnd_Position.bp.\tCorrected_Call\t"
        "Corrected_Copy_Number\tCorrected_MajorCN\tCorrected_MinorCN\tCellular_Prevalence\n"
        "sample\tchr1\t1\t1000000\tNEUT\t2\t1\t1\t1\n"
    )


# ---- legacy single-sample-folder layout (backward compatibility) ----

def test_discover_candidates_smoke(tmp_path):
    cand_dir = tmp_path / "ploidy2_cluster1"
    cand_dir.mkdir()
    _write_params(cand_dir / "sample_cluster1.params.txt")
    candidates = discover_candidates(str(tmp_path))
    assert len(candidates) == 1
    assert candidates[0].candidate_id == "ploidy2_cluster1"
    assert candidates[0].requested_ploidy_bin == 2
    assert candidates[0].requested_num_clusters == 1


def test_is_cohort_root_false_for_legacy_layout(tmp_path):
    (tmp_path / "ploidy2_cluster1").mkdir()
    assert is_cohort_root(str(tmp_path)) is False


def test_build_evidence_on_real_sample_if_available(tmp_path):
    sample_dir = os.environ.get(FIXTURE_ENV)
    if not sample_dir or not os.path.isdir(sample_dir):
        return  # skip: no local sample data available in this environment
    evidence = build_evidence(sample_dir, "test_sample", str(tmp_path), top_n=5)
    assert evidence["num_candidates_discovered"] > 0
    assert evidence["all_candidates_ranked"][0]["s_dbw_rank"] == 1


# ---- real cohort layout (titanCNA_ploidyN/ across all samples) ----

def _build_cohort_fixture(root):
    """<root>/titanCNA_ploidy2/{sampleA,sampleB}_cluster1.params.txt (+segs, +plot dir)
    and <root>/titanCNA_ploidy3/sampleA_cluster2.params.txt (+segs)."""
    p2 = root / "titanCNA_ploidy2"
    p2.mkdir()
    _write_params(p2 / "sampleA_cluster1.params.txt", sdbw=0.7)
    _write_segs(p2 / "sampleA_cluster1.segs.txt")
    plot_dir = p2 / "sampleA_cluster1"
    plot_dir.mkdir()
    (plot_dir / "sampleA_cluster01_CNA.png").write_bytes(b"fake-png")
    (plot_dir / "sampleA_cluster01_CNASEG.png").write_bytes(b"fake-png")
    (plot_dir / "sampleA_cluster01_LOH.png").write_bytes(b"fake-png")
    (plot_dir / "sampleA_cluster01_LOHSEG.png").write_bytes(b"fake-png")

    _write_params(p2 / "sampleB_cluster1.params.txt", sdbw=0.9)
    _write_segs(p2 / "sampleB_cluster1.segs.txt")

    p3 = root / "titanCNA_ploidy3"
    p3.mkdir()
    _write_params(p3 / "sampleA_cluster2.params.txt", sdbw=0.6)
    _write_segs(p3 / "sampleA_cluster2.segs.txt")


def test_is_cohort_root_true_for_real_layout(tmp_path):
    _build_cohort_fixture(tmp_path)
    assert is_cohort_root(str(tmp_path)) is True


def test_list_available_samples(tmp_path):
    _build_cohort_fixture(tmp_path)
    samples = list_available_samples(str(tmp_path))
    assert samples == ["sampleA", "sampleB"]


def test_discover_candidates_for_sample(tmp_path):
    _build_cohort_fixture(tmp_path)
    candidates = discover_candidates_for_sample(str(tmp_path), "sampleA")
    ids = sorted(c.candidate_id for c in candidates)
    assert ids == ["ploidy2_cluster1", "ploidy3_cluster2"]

    ploidy2 = next(c for c in candidates if c.candidate_id == "ploidy2_cluster1")
    assert ploidy2.params_path.endswith("sampleA_cluster1.params.txt")
    assert ploidy2.segs_path.endswith("sampleA_cluster1.segs.txt")
    assert ploidy2.plot_dir.endswith("sampleA_cluster1")

    # sampleB only has a ploidy2 candidate, and discovery must not leak sampleA's files.
    b_candidates = discover_candidates_for_sample(str(tmp_path), "sampleB")
    assert len(b_candidates) == 1
    assert b_candidates[0].candidate_id == "ploidy2_cluster1"
    assert "sampleB" in b_candidates[0].params_path


def test_discover_candidates_auto_routes_by_layout(tmp_path):
    _build_cohort_fixture(tmp_path)
    # cohort layout requires a sample_id
    try:
        discover_candidates_auto(str(tmp_path), None)
        assert False, "expected ValueError for missing sample_id on a cohort root"
    except ValueError:
        pass
    candidates = discover_candidates_auto(str(tmp_path), "sampleA")
    assert len(candidates) == 2


def test_build_evidence_on_cohort_fixture(tmp_path):
    fixture_root = tmp_path / "cohort"
    fixture_root.mkdir()
    _build_cohort_fixture(fixture_root)
    out_dir = tmp_path / "out"
    evidence = build_evidence(str(fixture_root), "sampleA", str(out_dir), top_n=5)
    assert evidence["num_candidates_discovered"] == 2
    ranked_ids = [c["candidate_id"] for c in evidence["all_candidates_ranked"]]
    # lower S_Dbw ranks first: ploidy3_cluster2 (0.6) before ploidy2_cluster1 (0.7)
    assert ranked_ids[0] == "ploidy3_cluster2"
    assert ranked_ids[1] == "ploidy2_cluster1"


def test_build_evidence_on_real_cohort_fixture_if_available(tmp_path):
    """Optional: point TITAN_TEST_COHORT_DIR at a real titanCNA_ploidyN/ cohort
    root to exercise this against real params.txt/segs.txt/plot data end to end."""
    cohort_dir = os.environ.get(COHORT_FIXTURE_ENV)
    if not cohort_dir or not os.path.isdir(cohort_dir):
        return  # skip: no local cohort fixture available in this environment
    samples = list_available_samples(cohort_dir)
    assert samples, f"no samples discovered under {cohort_dir}"
    evidence = build_evidence(cohort_dir, samples[0], str(tmp_path), top_n=5)
    assert evidence["num_candidates_discovered"] > 0
