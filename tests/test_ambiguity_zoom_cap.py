from titan_curation.cli import _candidates_needing_ambiguity_zoom


def _flag(a, b, gap):
    return {"candidate_a": a, "candidate_b": b, "s_dbw_gap": gap}


def test_single_pair_both_candidates_included():
    evidence = {"ploidy_doubling_ambiguity_flags": [_flag("A", "B", 0.05)]}
    assert _candidates_needing_ambiguity_zoom(evidence) == {"A", "B"}


def test_no_flags_empty_set():
    evidence = {"ploidy_doubling_ambiguity_flags": []}
    assert _candidates_needing_ambiguity_zoom(evidence) == set()


def test_caps_to_smallest_gap_pair_not_union_of_all():
    """Regression test: a real sample (18-115_cfPL_1039_WGSmerge) had one
    candidate pivoting ~2x ploidy against three others, producing 3
    overlapping ambiguity pairs whose UNION covered 4 of the top 5
    candidates -- each getting the full per-chromosome zoom treatment
    (10 images vs. 6), pushing a real request to ~6.1MB, over the ~5-6MB
    body-size limit that triggers an instant HTTP 400. Capping to only the
    single smallest-S_Dbw-gap pair (the most genuinely ambiguous case)
    keeps this bounded regardless of how many pairs exist."""
    evidence = {
        "ploidy_doubling_ambiguity_flags": [
            _flag("ploidy4_cluster1", "ploidy2_cluster1", 0.1011),
            _flag("ploidy2_cluster1", "ploidy4_cluster2", 0.0007),  # smallest gap
            _flag("ploidy2_cluster1", "ploidy4_cluster3", 0.0173),
        ]
    }
    result = _candidates_needing_ambiguity_zoom(evidence)
    assert result == {"ploidy2_cluster1", "ploidy4_cluster2"}
    assert len(result) == 2  # not the 4-candidate union


def test_max_pairs_override():
    evidence = {
        "ploidy_doubling_ambiguity_flags": [
            _flag("A", "B", 0.10),
            _flag("B", "C", 0.01),  # smallest gap
            _flag("C", "D", 0.05),  # second-smallest
        ]
    }
    # max_pairs=2 takes the two smallest-gap pairs: B-C and C-D.
    assert _candidates_needing_ambiguity_zoom(evidence, max_pairs=2) == {"B", "C", "D"}
