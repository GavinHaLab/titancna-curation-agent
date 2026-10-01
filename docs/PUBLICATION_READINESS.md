# Publication readiness tracker

Living checklist for getting this tool to a publishable state. Two distinct
targets, with different requirements — pick one or both:

- **(A) Software paper** (JOSS, Bioinformatics Applications Note,
  F1000Research Software Tool Article) — publishes the tool as a reusable
  research artifact. Reviewers check: does it work, is it tested, is it
  documented, is it citable/archived.
- **(B) Methods/validation paper** — publishes a scientific claim ("this
  LLM-based visual QC agrees with expert curation at rate X, catches
  ploidy-doubling errors raw statistics miss at rate Y"). Needs actual
  evidence, not just working software, on top of everything in (A).

Status as of 2026-10-01.

## Address now (applies to both tracks)

- [x] Regression tests for the cohort-CSV dedup/lock logic
      (`tests/test_consensus.py`)
- [x] Regression tests for the plot-cache atomic-write/race fix
      (`tests/test_plots.py`)
- [x] CI (`.github/workflows/tests.yml`) running the test suite on every
      push/PR, Python 3.10 + 3.11
- [x] `CHANGELOG.md`
- [ ] Tag a release (`v0.1.0`)
- [ ] `CITATION.cff`
- [ ] Archive a tagged release on Zenodo for a DOI (required by JOSS)

## Track A: software paper — remaining gaps

- [ ] Broader test coverage: `config.py` (resolution precedence across
      CLI flag / env var / config file), `cli.py` (argument wiring,
      `--skip-existing` behavior), reviewer backends (mock the API calls —
      no real network access needed to test request construction/response
      parsing)
- [ ] JOSS-style `paper.md` + `paper.bib` if targeting JOSS specifically
- [ ] API docs (even just well-organized docstrings rendered via a simple
      tool) beyond the current README/docstring coverage

## Track B: methods/validation paper — remaining gaps (needs real science)

- [ ] Benchmark set of samples with **expert-curated ground-truth labels**
      (the lab's own prior manual curations are the obvious source)
- [ ] Quantitative agreement metrics: Claude-vs-Gemini concordance,
      consensus-vs-expert concordance, sensitivity/specificity specifically
      for catching ploidy-doubling ambiguity (the tool's core value
      proposition over raw S_Dbw)
- [ ] **Reproducibility reporting** — models are not fully deterministic
      even at `temperature=0` (observed directly this week); a paper needs
      to run each sample N times and report the variance, not present one
      run as definitive
- [ ] Cost/compute reporting (real per-call cost data is already available
      from the API responses — just needs aggregating)
- [ ] Explicit limitations/failure-modes section — we hit several concrete,
      citable ones this week: truncated JSON at low `max_output_tokens`,
      request-size limits, rate limits, non-determinism
- [ ] Explicit "QC-assist, not replacement for human review" framing —
      the tool already enforces this in its output (`human_review_needed`
      always surfaced), the paper should say so explicitly given the
      clinical/research genomics context

## Feature backlog (raised 2026-10-01, tracked here until closed)

1. **Resume flag** — ✅ done. `--skip-existing` skips a sample in batch
   mode if its curation report already exists.
2. **Temperature control** — ✅ done. `--temperature`, threaded through all
   three reviewer backends. Caveat (documented in README): reduces but does
   not eliminate run-to-run variance.
3. **Parallelization** — ⏳ not started, needs a decision: add `--workers N`
   (thread pool, I/O-bound work). Code is already safe for this (rate-limit
   retry + flock-protected CSV writer verified under real concurrency).
   Open question: default worker count given Tier-1 (3 QPS) accounts —
   proposed 2-3 as a conservative default, overridable via the flag.
4. **Claude vs Gemini PDF handling** — ✅ resolved (not applicable): neither
   model ever receives a raw PDF; `plots.py` renders every plot to PNG/JPEG
   locally before anything is sent. Any output difference is about how
   each model reasons over an image, not PDF parsing.
5. **Log consolidation** — ⏳ not started, needs a decision. `titan-curate`
   itself writes no log files (only the intentional structured per-sample
   artifacts + cohort CSV); the "tons of log files" are SLURM's own
   per-array-task output files (`logs/titan_curate_%A_%a.log`). Options:
   (a) switch that cohort to single-job batch mode (one log, loses
   parallelism), or (b) keep the array job and add a post-run step that
   concatenates `logs/titan_curate_*.log` into one file (safer than
   sharing one live file across tasks, which risks interleaved lines).
6. **Claude's ~3x output-token cost vs Gemini** — ✅ done. Root cause:
   6000-8000 reasoning tokens spent per Claude call before any visible
   text, not the comment itself being longer. `--reasoning-effort`
   (Perplexity backend) controls this directly.
