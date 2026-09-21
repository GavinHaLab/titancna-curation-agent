"""Discover TITAN ploidy x cluster candidates for a sample.

Supports TWO layouts:

1. **Real cohort layout** (produced by the GavinHaLab TitanCNA Nextflow
   pipeline at scale, e.g. `.../titan/hmm/`): a single cohort root containing
   `titanCNA_ploidy2/`, `titanCNA_ploidy3/`, `titanCNA_ploidy4/`, ... Each of
   those directories holds the text outputs and plot subfolders for EVERY
   sample and cluster in the cohort, flat, side by side:

     titan/hmm/
       optimalClusterSolution.txt
       optimalClusterSolution/
       titanCNA_ploidy2/
         <sample>_cluster1.params.txt
         <sample>_cluster1.segs.txt
         <sample>_cluster1.titan.txt          (large -- not touched by default)
         <sample>_cluster1/                    <- plot subfolder (unpadded cluster #)
           <sample>_cluster01_CNA.pdf/.png     (zero-padded cluster # in filenames)
           <sample>_cluster01_CNASEG.pdf/.png
           <sample>_cluster01_LOH.pdf/.png
           <sample>_cluster01_LOHSEG.pdf/.png
           <sample>_cluster01_CF.pdf/.png
           <sample>_cluster01_subclone.pdf/.png
           <sample>_cluster01_chr1.png ... chrX.png   (per-chromosome, PNG only)
       titanCNA_ploidy3/
         ... same pattern, same sample names, cluster numbers may differ ...
       titanCNA_ploidy4/
         ...

   This is the layout used in production cohorts and is now the primary
   target. A "candidate" here is one (ploidy bin, cluster count) combination
   for ONE named sample, drawn from across the ploidyN_* directories.

2. **Legacy single-sample-folder layout** (used in earlier local testing
   fixtures, kept for backward compatibility): a folder per sample containing
   `ploidyN_clusterM/` subfolders directly, e.g.:

     00-010_LN_L_WGS/
       ploidy2_cluster1/{params.txt, segs.txt, plots...}
       ploidy2_cluster2/...
       ...

   `discover_candidates()` (the old entry point) still works unchanged for
   this layout and is used automatically as a fallback when a cohort root
   does not look like layout 1.
"""
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
PLOIDY_COHORT_DIR_RE = re.compile(r"^titanCNA_ploidy(\d+)$")
CLUSTER_PARAMS_RE = re.compile(r"^(?P<sample>.+)_cluster(?P<cluster>\d+)\.params\.txt$")


def _cohort_ploidy_dirs(cohort_root: str) -> list[tuple[int, str]]:
    """Return [(ploidy_bin, dir_path), ...] for every titanCNA_ploidyN/ dir
    directly under cohort_root, sorted by ploidy."""
    out = []
    for d in sorted(glob.glob(os.path.join(cohort_root, "titanCNA_ploidy*"))):
        if not os.path.isdir(d):
            continue
        m = PLOIDY_COHORT_DIR_RE.match(os.path.basename(d))
        if m:
            out.append((int(m.group(1)), d))
    return sorted(out, key=lambda t: t[0])


def is_cohort_root(path: str) -> bool:
    """True if `path` looks like the real cohort layout (has titanCNA_ploidyN/
    subdirectories), as opposed to a single-sample folder."""
    return len(_cohort_ploidy_dirs(path)) > 0


def list_available_samples(cohort_root: str) -> list[str]:
    """Scan every titanCNA_ploidyN/ directory under a cohort root and return
    the sorted list of distinct sample names found (from
    `<sample>_cluster<M>.params.txt` filenames). Works for the real cohort
    layout only -- for the legacy single-sample layout there is exactly one
    sample and its name is the folder name, so this isn't needed there."""
    cohort_root = os.path.abspath(cohort_root)
    samples = set()
    for _ploidy, ploidy_dir in _cohort_ploidy_dirs(cohort_root):
        for f in glob.glob(os.path.join(ploidy_dir, "*_cluster*.params.txt")):
            m = CLUSTER_PARAMS_RE.match(os.path.basename(f))
            if m:
                samples.add(m.group("sample"))
    return sorted(samples)


def discover_candidates_for_sample(cohort_root: str, sample_id: str) -> list[Candidate]:
    """Real cohort layout: gather every (ploidy bin, cluster count) candidate
    for one named sample across all titanCNA_ploidyN/ directories under
    cohort_root. Only touches files that match this sample_id -- never globs
    or loads other samples' data."""
    cohort_root = os.path.abspath(cohort_root)
    escaped = glob.escape(sample_id)
    candidates: list[Candidate] = []

    for ploidy_bin, ploidy_dir in _cohort_ploidy_dirs(cohort_root):
        for params_path in sorted(glob.glob(os.path.join(ploidy_dir, f"{escaped}_cluster*.params.txt"))):
            m = CLUSTER_PARAMS_RE.match(os.path.basename(params_path))
            if not m:
                continue
            num_clusters = int(m.group("cluster"))
            segs_path = os.path.join(ploidy_dir, f"{sample_id}_cluster{num_clusters}.segs.txt")
            plot_dir = os.path.join(ploidy_dir, f"{sample_id}_cluster{num_clusters}")

            candidates.append(Candidate(
                candidate_id=f"ploidy{ploidy_bin}_cluster{num_clusters}",
                dir_path=ploidy_dir,
                requested_ploidy_bin=ploidy_bin,
                requested_num_clusters=num_clusters,
                params_path=params_path,
                segs_path=segs_path if os.path.isfile(segs_path) else None,
                plot_dir=plot_dir if os.path.isdir(plot_dir) else None,
            ))
    return candidates


def discover_candidates(sample_root: str) -> list[Candidate]:
    """Legacy layout: find every ploidyN_clusterM subdirectory directly under
    sample_root and locate its params.txt / segs.txt. Falls back to scanning
    sample_root itself if it IS a single candidate directory (no
    ploidyN_clusterM children)."""
    sample_root = os.path.abspath(sample_root)
    candidate_dirs = sorted(
        d for d in glob.glob(os.path.join(sample_root, "*"))
        if os.path.isdir(d) and CANDIDATE_DIR_RE.search(os.path.basename(d))
    )

    if not candidate_dirs:
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


def discover_candidates_auto(input_path: str, sample_id: Optional[str]) -> list[Candidate]:
    """Unified entry point: if `input_path` is a real cohort root (has
    titanCNA_ploidyN/ subdirectories), discover candidates for `sample_id`
    within it. Otherwise fall back to the legacy single-sample-folder
    behavior and ignore `sample_id` (the folder itself is the sample)."""
    if is_cohort_root(input_path):
        if not sample_id:
            raise ValueError(
                f"'{input_path}' looks like a cohort root (contains titanCNA_ploidyN/ "
                "directories) with multiple samples -- specify --sample, --samples, "
                "--sample-list-file, or --all-samples."
            )
        return discover_candidates_for_sample(input_path, sample_id)
    return discover_candidates(input_path)


def find_optimal_cluster_solution(sample_root: str) -> Optional[str]:
    """Locate the (possibly cohort-wide) optimalClusterSolution.txt file.
    In the real cohort layout this single file covers every sample; in the
    legacy layout it is per-sample. Either way this just returns its path --
    use get_optimal_solution_for_sample() to extract one sample's row."""
    for name in ("optimalClusterSolution.txt",):
        p = os.path.join(sample_root, name)
        if os.path.isfile(p):
            return p
    matches = glob.glob(os.path.join(sample_root, "**", name), recursive=True)
    return matches[0] if matches else None


def get_optimal_solution_for_sample(optimal_file: Optional[str], sample_id: str) -> Optional[dict]:
    """Best-effort parse of a (possibly cohort-wide, tab- or whitespace-
    delimited) optimalClusterSolution.txt to pull out the row for one sample,
    as a raw {column: value} dict. This is informational only -- treated per
    the curation methodology as "the raw TITAN selection", never authoritative
    on its own. Returns None if the file is missing, unreadable, or has no
    row matching sample_id; never raises."""
    if not optimal_file or not os.path.isfile(optimal_file):
        return None
    try:
        with open(optimal_file) as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        if not lines:
            return None
        header = re.split(r"\t|\s{2,}", lines[0].strip())
        for line in lines[1:]:
            fields = re.split(r"\t|\s{2,}", line.strip())
            if any(sample_id in field for field in fields):
                row = dict(zip(header, fields))
                return row
    except Exception:
        return None
    return None
