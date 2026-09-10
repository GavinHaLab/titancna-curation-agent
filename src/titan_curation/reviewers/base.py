"""Shared prompt construction and JSON-schema contract for both reviewers."""
from __future__ import annotations

import json
import os

REVIEW_SCHEMA_HINT = {
    "reviewer": "claude_sonnet | gemini",
    "sample_id": "string",
    "recommended_candidate_id": "string, e.g. ploidy2_cluster1",
    "recommended_ploidy": "number",
    "recommended_titan_purity": "number",
    "recommended_num_clusters": "integer",
    "raw_titan_optimal_candidate_id": "string, the lowest S_Dbw candidate id from evidence",
    "overrides_raw_titan_optimal": "boolean",
    "confidence": "low | moderate | high",
    "ranked_candidates": [
        {
            "rank": "integer",
            "candidate_id": "string",
            "verdict": "preferred | plausible_alternative | rejected",
            "rationale": "1-3 sentences",
        }
    ],
    "flags": [
        {
            "type": "ploidy_doubling_ambiguity | noisy_segmentation | baf_logr_discordance | "
                    "purity_implausible | high_subclonal_fraction | borderline_sdbw_margin | other",
            "severity": "low | moderate | high",
            "evidence": "1-2 sentences citing specific numbers or plot observations",
        }
    ],
    "comment": "Precise human-facing rationale, under 750 words total",
    "human_review_needed": "boolean",
    "human_review_focus": ["short strings"],
}


def load_text(path: str) -> str:
    with open(path) as f:
        return f.read()


def build_system_prompt(knowledge_dir: str) -> str:
    skills = load_text(os.path.join(knowledge_dir, "skills.md"))
    reference = load_text(os.path.join(knowledge_dir, "titan_reference.md"))
    return (
        "You are an independent expert reviewer curating TitanCNA copy-number/LOH "
        "candidate solutions for one tumor sample. Follow this curation methodology "
        "exactly:\n\n"
        f"{skills}\n\n---\n\n{reference}\n\n---\n\n"
        "Return ONLY a single valid JSON object matching this shape (no markdown "
        "fencing, no prose before or after):\n"
        f"{json.dumps(REVIEW_SCHEMA_HINT, indent=2)}\n\n"
        "Do not invent values not present in the images or evidence package. "
        "The 'comment' field must open by describing what you saw in the plots "
        "(specific axis values, chromosomes, band positions), not just cite "
        "S_Dbw/log-likelihood/FGA numbers -- those are secondary corroboration only."
    )


def build_user_text(evidence: dict, top_candidates: list[dict], reviewer_name: str) -> str:
    compact_evidence = {
        "sample_id": evidence["sample_id"],
        "raw_titan_optimal_candidate_id": top_candidates[0]["candidate_id"] if top_candidates else None,
        "ploidy_doubling_ambiguity_flags": evidence.get("ploidy_doubling_ambiguity_flags", []),
        "top_candidates": [
            {
                "candidate_id": c["candidate_id"],
                "ploidy": c["ploidy"],
                "requested_num_clusters": c["requested_num_clusters"],
                "effective_num_clusters": c["effective_num_clusters"],
                "titan_purity": c["titan_purity"],
                "log_likelihood": c["log_likelihood"],
                "s_dbw_both": c["s_dbw_both"],
                "s_dbw_rank": c["s_dbw_rank"],
                "cluster_collapse_flag": c["cluster_collapse_flag"],
                "segment_metrics": c.get("segment_metrics"),
            }
            for c in top_candidates
        ],
    }
    return (
        f"You are reviewer '{reviewer_name}'. Set the 'reviewer' field in your JSON "
        f"response to exactly '{reviewer_name}'.\n\n"
        "Below is the deterministic evidence package for this sample (S_Dbw ranking, "
        "log-likelihood, segment metrics for the top candidates). The images that "
        "follow are the genome-wide (and, for closely-ranked pairs, per-chromosome) "
        "CNA/LOH/clonal-frequency plots for these same candidates, in the same order "
        "they are listed here. Inspect the images as your PRIMARY evidence; use the "
        "numbers below only to corroborate what you see.\n\n"
        f"{json.dumps(compact_evidence, indent=2, default=str)}"
    )
