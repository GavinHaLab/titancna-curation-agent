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
- [ ] **`confidence` field is uncalibrated** — checked `base.py` and the
      full knowledge base: `confidence` (low/moderate/high) is purely the
      model's own free-text self-assessment, with zero rubric tying it to
      any computed signal (S_Dbw margin, BAF/logR concordance strength,
      etc.). LLM self-reported confidence is known to correlate poorly with
      actual accuracy unless explicitly calibrated. Before using it in any
      reported metric, either (a) validate it post-hoc against ground truth
      and report the calibration, or (b) replace it with something computed
      directly (e.g. derived from the S_Dbw margin or from Claude/Gemini's
      agreement) rather than a self-rating.
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
3. **Parallelization** — ✅ done. `--workers N` (thread pool, default 3,
   given a Tier-1/3-QPS account at the time; raise it as the account's rate
   limit changes). `--workers 1` preserves the old sequential behavior.
   Per-sample console output interleaves when workers > 1 (documented).
4. **Claude vs Gemini PDF handling** — ✅ resolved (not applicable): neither
   model ever receives a raw PDF; `plots.py` renders every plot to PNG/JPEG
   locally before anything is sent. Any output difference is about how
   each model reasons over an image, not PDF parsing.
5. **Log consolidation** — ✅ done. `scripts/consolidate_array_logs.sh`
   concatenates a SLURM array job's per-task logs
   (`logs/titan_curate_<jobid>_<array_index>.log`) into one combined log,
   sorted numerically by array index, run as a post-job step. Documented
   in `docs/HPC_SETUP.md` section 7.
6. **Claude's ~3x output-token cost vs Gemini** — ✅ done. Root cause:
   6000-8000 reasoning tokens spent per Claude call before any visible
   text, not the comment itself being longer. `--reasoning-effort`
   (Perplexity backend) controls this directly.
