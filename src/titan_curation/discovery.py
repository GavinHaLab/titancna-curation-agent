"""Discover TITAN ploidy x cluster candidate directories under a local sample path."""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Candidate:
    candidate_id: str
    dir_path: str
    requested_ploidy_bin: Optional[int]
    requested_num_clusters: Optional[int]
    params_path: Optional[str] = None
    segs_path: Optional[str] = None
    plot_dir: Optional[str] = None
    extra: dict = field(default_factory=dict)


CANDIDATE_DIR_RE = re.compile(r"ploidy(\d+)_cluster(\d+)$")


def discover_candidates(sample_root: str) -> list[Candidate]:
    """Find every ploidyN_clusterM subdirectory under sample_root and locate its
    params.txt / segs.txt. Falls back to scanning sample_root itself if it IS
    a single candidate directory (no ploidyN_clusterM children)."""
    sample_root = os.path.abspath(sample_root)
    candidate_dirs = sorted(
        d for d in glob.glob(os.path.join(sample_root, "*"))
        if os.path.isdir(d) and CANDIDATE_DIR_RE.search(os.path.basename(d))
    )

    if not candidate_dirs:
        # Maybe the user pointed straight at one candidate directory, or at a
        # flat directory containing all candidates' files without subfolders.
        # Try treating sample_root itself as a single candidate.
        params = glob.glob(os.path.join(sample_root, "*.params.txt"))
        if params:
            candidate_dirs = [sample_root]

    candidates = []
    for d in candidate_dirs:
        base = os.path.basename(d)
        m = CANDIDATE_DIR_RE.search(base)
        ploidy_bin = int(m.group(1)) if m else None
        num_clusters = int(m.group(2)) if m else None

        params_files = glob.glob(os.path.join(d, "*.params.txt"))
        segs_files = glob.glob(os.path.join(d, "*.segs.txt"))

        candidates.append(Candidate(
            candidate_id=base if m else os.path.basename(sample_root),
            dir_path=d,
            requested_ploidy_bin=ploidy_bin,
            requested_num_clusters=num_clusters,
            params_path=params_files[0] if params_files else None,
            segs_path=segs_files[0] if segs_files else None,
            plot_dir=d,
        ))
    return candidates


def find_optimal_cluster_solution(sample_root: str) -> Optional[str]:
    for name in ("optimalClusterSolution.txt",):
        p = os.path.join(sample_root, name)
        if os.path.isfile(p):
            return p
    matches = glob.glob(os.path.join(sample_root, "**", name), recursive=True)
    return matches[0] if matches else None
