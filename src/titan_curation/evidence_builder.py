"""Rank candidates and build the evidence package (evidence.json + candidate_metrics.csv)."""
from __future__ import annotations

import json
import os

import pandas as pd

from .discovery import discover_candidates, find_optimal_cluster_solution
from .parsing import parse_params, parse_segs


def build_evidence(sample_root: str, sample_id: str, out_dir: str, top_n: int = 5) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    candidates_raw = discover_candidates(sample_root)
    optimal_file = find_optimal_cluster_solution(sample_root)

    candidates = []
    for c in candidates_raw:
        if not c.params_path:
            continue
        params = parse_params(c.params_path)
        candidates.append({
            "sample_id": sample_id,
            "candidate_id": c.candidate_id,
            "requested_ploidy_bin": c.requested_ploidy_bin,
            "requested_num_clusters": c.requested_num_clusters,
            "params_path": c.params_path,
            "segs_path": c.segs_path,
            "plot_dir": c.plot_dir,
            **params,
        })

    ranked = sorted(candidates, key=lambda c: (c["s_dbw_both"] is None, c["s_dbw_both"]))
    for i, c in enumerate(ranked):
        c["s_dbw_rank"] = i + 1
        c["cluster_collapse_flag"] = (
            c["effective_num_clusters"] is not None
            and c["requested_num_clusters"] is not None
            and c["effective_num_clusters"] < c["requested_num_clusters"]
        )

    top_candidates = ranked[:top_n]
    for c in top_candidates:
        c["segment_metrics"] = parse_segs(c["segs_path"]) if c["segs_path"] else None

    ambiguities = []
    for i in range(len(top_candidates)):
        for j in range(i + 1, len(top_candidates)):
            a, b = top_candidates[i], top_candidates[j]
            if a["ploidy"] and b["ploidy"]:
                ratio = max(a["ploidy"], b["ploidy"]) / min(a["ploidy"], b["ploidy"])
                sdbw_gap = abs(a["s_dbw_both"] - b["s_dbw_both"])
                if 1.7 <= ratio <= 2.3 and sdbw_gap < 0.15:
                    ambiguities.append({
                        "candidate_a": a["candidate_id"], "candidate_b": b["candidate_id"],
                        "ploidy_a": a["ploidy"], "ploidy_b": b["ploidy"],
                        "s_dbw_gap": round(sdbw_gap, 4),
                    })

    evidence = {
        "sample_id": sample_id,
        "sample_root": os.path.abspath(sample_root),
        "num_candidates_discovered": len(candidates),
        "optimal_cluster_solution_file": optimal_file,
        "all_candidates_ranked": ranked,
        "top_candidates_with_segment_metrics": top_candidates,
        "ploidy_doubling_ambiguity_flags": ambiguities,
    }

    evidence_path = os.path.join(out_dir, "evidence.json")
    with open(evidence_path, "w") as f:
        json.dump(evidence, f, indent=2, default=str)

    csv_rows = []
    for c in ranked:
        csv_rows.append({
            "candidate_id": c["candidate_id"],
            "s_dbw_rank": c["s_dbw_rank"],
            "ploidy": c["ploidy"],
            "requested_num_clusters": c["requested_num_clusters"],
            "effective_num_clusters": c["effective_num_clusters"],
            "cluster_collapse_flag": c["cluster_collapse_flag"],
            "normal_contamination": c["normal_contamination"],
            "titan_purity": c["titan_purity"],
            "cluster_cellular_prevalence": ";".join(str(x) for x in c["cluster_cellular_prevalence"]),
            "log_likelihood": c["log_likelihood"],
            "s_dbw_both": c["s_dbw_both"],
            "s_dbw_logratio": c["s_dbw_logratio"],
            "s_dbw_allelicratio": c["s_dbw_allelicratio"],
        })
    pd.DataFrame(csv_rows).to_csv(os.path.join(out_dir, "candidate_metrics.csv"), index=False)

    return evidence
