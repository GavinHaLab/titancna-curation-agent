"""Select and render TITAN plots (PDF or PNG) for the reviewer models.

Never loads more than requested: genome-wide plots for the top-N candidates,
plus per-chromosome plots only for explicitly requested (chrom, candidate)
pairs (e.g. a ploidy-doubling ambiguity). PDFs are rendered to PNG on demand
via PyMuPDF so both the Claude and Gemini reviewers get a consistent image
format without requiring a system poppler install.
"""
from __future__ import annotations

import glob
import hashlib
import os
from typing import Optional

GENOME_WIDE_SUFFIXES = ["CNA", "CNASEG", "LOH", "LOHSEG", "CF", "subclone"]


def _cache_dir(cache_root: str) -> str:
    os.makedirs(cache_root, exist_ok=True)
    return cache_root


def render_pdf_to_png(pdf_path: str, cache_root: str, dpi: int = 130, page: int = 0) -> str:
    """Render one page of a PDF to PNG, caching by content hash so repeat runs
    don't re-render. Requires PyMuPDF (fitz)."""
    import fitz  # PyMuPDF

    h = hashlib.sha1(f"{pdf_path}:{page}:{dpi}".encode()).hexdigest()[:16]
    out_path = os.path.join(_cache_dir(cache_root), f"{h}.png")
    if os.path.exists(out_path):
        return out_path

    doc = fitz.open(pdf_path)
    pg = doc.load_page(page)
    zoom = dpi / 72.0
    pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    pix.save(out_path)
    doc.close()
    return out_path


def ensure_image(path: str, cache_root: str) -> str:
    """Return a PNG/JPEG path usable directly by a vision API, rendering a PDF
    to PNG if necessary."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".jpg", ".jpeg"):
        return path
    if ext == ".pdf":
        return render_pdf_to_png(path, cache_root)
    raise ValueError(f"Unsupported plot file type: {path}")


def find_genome_wide_plot(plot_dir: str, suffix: str, sample_id: str) -> Optional[str]:
    """Find a genome-wide plot file (PDF preferred, else PNG) for one suffix
    (CNA/CNASEG/LOH/LOHSEG/CF/subclone) inside a candidate's plot directory.
    CNASEG/LOHSEG are the segmented/annotated variants of the CNA/LOH plots
    and carry richer visual detail (called segments overlaid on the raw
    signal) -- treat them as equally primary evidence, not a substitute for
    the raw CNA/LOH plots. Handles both zero-padded (_cluster01_) and
    unpadded (_cluster1_) naming."""
    patterns = [
        os.path.join(plot_dir, f"*_{suffix}.pdf"),
        os.path.join(plot_dir, f"*_{suffix}.png"),
    ]
    for pat in patterns:
        matches = sorted(glob.glob(pat))
        # Prefer genome-wide files: exclude ones with a chr-number segment.
        matches = [m for m in matches if "_chr" not in os.path.basename(m)]
        if matches:
            return matches[0]
    return None


def find_per_chromosome_plot(plot_dir: str, chrom: str) -> Optional[str]:
    patterns = [
        os.path.join(plot_dir, f"*_{chrom}.pdf"),
        os.path.join(plot_dir, f"*_{chrom}.png"),
    ]
    for pat in patterns:
        matches = sorted(glob.glob(pat))
        if matches:
            return matches[0]
    return None


def select_plots_for_candidate(plot_dir: str, sample_id: str, cache_root: str,
                                chromosomes: Optional[list[str]] = None) -> dict:
    """Returns {"genome_wide": {suffix: image_path}, "per_chromosome": {chrom: image_path}}
    for one candidate, rendering PDFs to PNG as needed. Only touches the files
    actually requested -- never globs/loads a candidate's whole plot directory."""
    result = {"genome_wide": {}, "per_chromosome": {}}
    for suffix in GENOME_WIDE_SUFFIXES:
        p = find_genome_wide_plot(plot_dir, suffix, sample_id)
        if p:
            result["genome_wide"][suffix] = ensure_image(p, cache_root)
    if chromosomes:
        for chrom in chromosomes:
            p = find_per_chromosome_plot(plot_dir, chrom)
            if p:
                result["per_chromosome"][chrom] = ensure_image(p, cache_root)
    return result
