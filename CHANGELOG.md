# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.1.0] - 2026-10-01

Initial tagged release.

### Added
- Core CLI (`titan-curate run` / `titan-curate list-samples`): deterministic
  TITAN candidate discovery/ranking, staged genome-wide + per-chromosome
  plot selection, independent Claude + Gemini visual review, consensus
  report generation.
- Two reviewer backends: `direct` (bring your own Anthropic + Google API
  keys) and `perplexity` (one Perplexity API key drives both reviewer
  roles via its Agent API).
- Support for the real multi-sample TITAN Nextflow cohort layout
  (`titanCNA_ploidyN/` directories), in addition to the legacy
  single-sample-folder layout.
- Batch mode (`--samples` / `--sample-list-file` / `--all-samples`) with
  per-sample failure isolation and a shared cohort summary CSV.
- `--skip-existing`: skip a sample in batch mode if its curation report
  already exists, so a batch can be resumed after a partial failure
  without re-spending already-completed samples' API calls.
- `--temperature` / `--reasoning-effort`: sampling controls for reducing
  run-to-run variance and (on the Perplexity backend) Claude's reasoning-
  token spend.
- `docs/HPC_SETUP.md`: full walkthrough for Fred Hutch SciComp / generic
  SLURM clusters, including both single-job and array-job batch patterns.

### Fixed
- Race condition in the PDF-to-PNG plot-render cache that could produce
  `cannot open file ... File exists` under concurrent access (two batch
  runs against the same `--out-root`, or a stale directory listing on a
  networked filesystem) — fixed by rendering to a unique per-process temp
  file and atomically moving it into place.
- Cohort summary CSV accumulating duplicate rows on every rerun of a
  sample instead of replacing the old row — fixed with a `flock`-protected
  upsert, verified safe under real concurrent writers (the documented
  SLURM array-job pattern).
- HTTP 429 (rate limit) from the Perplexity backend failing the whole
  sample instead of retrying — added exponential backoff honoring the
  API's `Retry-After` header.
- Oversized/uncompressed image payloads triggering an opaque HTTP 400 from
  the Perplexity backend — plot images are now downscaled and re-encoded
  as JPEG before embedding.
- Truncated/invalid JSON from the Perplexity backend when `max_output_tokens`
  was too low for `anthropic/*` models' internal reasoning overhead.
- `response.output_text` unreliable on the Perplexity SDK for this Agent
  API — text is now extracted directly from `response.output[]`.

### Known issues / in progress
See the "Publication readiness" tracker in `docs/PUBLICATION_READINESS.md`
for the current list of open items (test coverage, CI status, validation
data, parallelization, log consolidation).
