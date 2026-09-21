---
name: titan-cna-curation
description: Curate TitanCNA copy-number/LOH solutions by visually inspecting the genome-wide/per-chromosome CNA and LOH plots for a sample as the PRIMARY evidence, then cross-checking against the params.txt statistics and segs.txt genome-wide summaries as secondary corroboration. Use whenever the user asks to review, curate, QC, pick the optimal solution for, or sanity-check a TITAN run (files/folders named *.titan.txt, *.segs.txt, *.params.txt, optimalClusterSolution.txt, or a titan/hmm directory), regardless of which sample or project it belongs to.
---

# TITAN CNA Solution Curation

TitanCNA runs a grid of (ploidy × numClusters) HMM fits per sample and ranks them statistically (S_Dbw validity index / log-likelihood) via optimalClusterSolution.txt. That statistical ranking is necessary but NOT sufficient, and it is frequently wrong in exactly the cases that matter most (wrong-ploidy fits, ploidy-doubling ambiguity). The plots are the ground truth signal; the text statistics are a fast triage tool for narrowing the field, not the basis for the final call.

**Core rule: visual evidence from the plots (PDFs or PNGs) is the primary basis for the recommendation. Deterministic text-derived statistics (S_Dbw, log-likelihood, fraction-altered, segment counts) are secondary corroboration used to explain and support what you see in the plots — never to override a clear visual verdict.**

## Inputs to locate

Given a sample directory (or titan/hmm/ root), find, for each ploidy/cluster combination:
- `{sample}_cluster{N}.params.txt`
- `{sample}_cluster{N}.segs.txt`
- `{sample}_cluster{N}.titan.txt` (only needed for deep dives, it's large — don't load it in full by default)
- the plot directory `{sample}_cluster{N}/` containing genome-wide `*_CNA.pdf`/`.png` (logR) and `*_CNASEG.pdf`/`.png` (logR with called segments overlaid), `*_LOH.pdf`/`.png` (allelic ratio) and `*_LOHSEG.pdf`/`.png` (allelic ratio with called segments overlaid), a clonal-frequency (`*_CF`) and subclone plot, and per-chromosome versions of the CNA/LOH plots. Treat the SEG variants as equally primary evidence, not a substitute for the raw CNA/LOH plots — the segment overlay is useful for spotting over/under-segmentation, but baseline centering and BAF/logR concordance are still best judged from the raw (non-SEG) plots.
- `optimalClusterSolution.txt` if present, at the sample or project root

**Plot format and size handling:** Prefer the original PDF plots when present — render them to images for the vision model rather than trying to read raw PDF bytes. If only flattened PNGs exist, use those directly. Either way, **never bulk-fetch/load the whole per-sample plot bundle (all ploidy×cluster combinations × all chromosomes can exceed 50–80MB).** Select plots incrementally:
1. First parse only the small text files (`params.txt`, `segs.txt`) for every candidate — these are a few KB to tens of KB each.
2. Rank by S_Dbw/log-likelihood/segment metrics (Step 1–2 below) to narrow to the top 3–5 candidates.
3. Render/select genome-wide CNA/CNASEG/LOH/LOHSEG/clonal-frequency plots for only those top candidates.
4. Render/select per-chromosome plots only for the specific chromosomes and candidates that need closer visual inspection (e.g. the two candidates in a ploidy-doubling ambiguity) — not the full per-chromosome set for every candidate.

This selective, staged approach is what keeps the total payload (and API image/token cost) small regardless of whether the source folder is a few MB or 80MB.

## Step 1 — Pull the statistical ranking (triage only)

Parse every available params.txt and build a table with: ploidy, numClusters, purity (1 − normal contamination), per-cluster cellular prevalence, log-likelihood, S_Dbw index. Sort by S_Dbw (lower is better) and note the top 3–5 candidates — this narrows which plots to look at next. Do not treat this ranking as a conclusion; ambiguity usually shows up as multiple solutions within a small S_Dbw margin of each other, and the single "optimal" pick is frequently the wrong one visually.

## Step 2 — Summarize each candidate's segs.txt (triage only)

For each of the top candidates, compute from segs.txt:
- fraction of genome altered (non-HET/NLOH-diploid)
- fraction of genome subclonal
- number of segments (very high segment count relative to peers = noisy fit)
- largest and most confident CN events (by segment length)

These are cheap, deterministic summaries used to decide which candidates deserve a close visual look and to explain what you already saw in the plots.

## Step 3 — Visual QC (this is the primary evidence — do this thoroughly, on the actual plots, before finalizing anything)

Open the genome-wide CNA and LOH plots for each top candidate. Form an independent visual verdict for each candidate FIRST, before looking again at the S_Dbw ranking. Check:
- **LogR baseline centering** — does the copy-neutral (HET/diploid) population sit at logR ≈ 0 at the stated ploidy, or does the whole track look shifted, implying the wrong ploidy was picked? A shifted baseline is disqualifying regardless of how good the S_Dbw score is.
- **Segmentation cleanliness** — are segment boundaries crisp, or is the signal fragmented/noisy (common at low purity, and a reason automated stats overfit)?
- **LogR/BAF concordance** — does the allelic-ratio (LOH) plot's HET/LOH pattern match what the CN calls in the CNA plot claim? A claimed copy-neutral LOH region should show BAF skew even though logR ≈ 0; a claimed simple gain/loss should show a consistent, not noisy, BAF split.
- **Ploidy-doubling ambiguity** — if two candidates are ~2x apart in ploidy with similar S_Dbw/likelihood, compare their plots directly, including per-chromosome plots for a few representative chromosomes: the correct one usually has tighter, more consistent segment clusters at the claimed integer CN states, and the baseline sits at 0.
- **Subclonal cluster plausibility** — in the clonal-frequency plot, are subclones well-separated in cellular prevalence, or are extra clusters splitting hairs (near-identical prevalence, or clusters that blanket nearly the whole genome = likely overfit, prefer the simpler solution)?

**If the visual verdict and the S_Dbw ranking disagree, the visual verdict wins.** State explicitly, in these terms, which plot observation is driving your recommendation, quoting what you actually saw (e.g. "the HET band sits at logR≈0.4 not 0, across chr1-6 and chr9-22" rather than only citing the fraction-altered number).

## Step 4 — Cross-check biological plausibility

- If an independent purity estimate exists (pathology, WES, ichorCNA tumor fraction), check the TITAN purity isn't wildly inconsistent with it.
- Flag implausible ploidy (>5, or <1.5 for a solid tumor without prior knowledge of extreme genome doubling) as needing extra scrutiny rather than auto-accepting.
- Flag solutions with a very high subclonal fraction as needing extra scrutiny — this is often a symptom of a wrong ploidy/purity fit rather than real subclonality, and should be visually confirmed.

## Step 5 — Output

Produce, per sample:
- A ranked table of the top candidates with: ploidy, purity, numClusters, S_Dbw, fraction genome altered/subclonal, and a one-line **visual** QC verdict per plot set (this is the load-bearing column, not the S_Dbw column).
- A recommended solution, distinct from the raw S_Dbw top pick whenever the visual/biological checks override it — and say so explicitly.
- Explicit flags for anything a human should look at personally: ploidy-doubling ambiguity, noisy segmentation, BAF/logR discordance, purity inconsistency with external estimates, or borderline S_Dbw margins between top candidates.

Never silently accept the optimalClusterSolution.txt pick, or the lowest-S_Dbw candidate, without doing Step 3 on its actual plots.

## Notes

This skill is deliberately sample-agnostic: it takes a directory path as input and works from file naming conventions, not from hardcoded sample IDs or project paths. A report that only cites S_Dbw/log-likelihood/fraction-altered numbers without a specific, concrete description of what the plots showed has not done Step 3 properly.
