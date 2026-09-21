# TitanCNA Curation Agent (CLI)

Curates TitanCNA copy-number/LOH candidate solutions for a tumor sample using
deterministic statistics for triage and two independent vision-capable LLM
reviewers (Claude and Gemini) for the actual visual QC call. Point it at a
real TITAN HMM cohort directory (or a local single-sample folder) — no
OneDrive, no upload limits required. Drive the two reviewers with your own
Anthropic + Google API keys, **or** with a single Perplexity API key.

This is the standalone, bring-your-own-API-key counterpart to the
["TitanCNA Curation Agent"](#relationship-to-the-perplexity-computer-prototype)
prototype developed on Perplexity Computer. The curation methodology
(`src/titan_curation/knowledge/skills.md`) is the shared source of truth
between both.

For running this at scale on an HPC cluster (SLURM, shared filesystems,
batch/array jobs), see [`docs/HPC_SETUP.md`](docs/HPC_SETUP.md).

## Why two reviewers, and why plots first

TitanCNA's own statistical ranking (S_Dbw / log-likelihood) is necessary but
not sufficient — it is frequently wrong exactly when it matters most: wrong
ploidy fits and 2N/4N ploidy-doubling ambiguity often score *better* on S_Dbw
than the biologically correct solution. This tool's core design rule (see
`knowledge/skills.md`) is: **plots are primary evidence, text statistics are
secondary corroboration.** Both reviewers are told this explicitly and are
shown the genome-wide (CNA, CNASEG, LOH, LOHSEG, CF, subclone — PDF preferred,
PNG fallback) and, for closely-ranked or ploidy-doubling-ambiguous pairs, the
per-chromosome plots, before being given the numeric ranking.

## Install

```bash
git clone <this-repo>
cd titan-curation-agent
pip install -e .

# Pick the reviewer backend(s) you plan to use (installs the matching SDK):
pip install -e ".[perplexity]"   # single Perplexity API key drives both reviewers
pip install -e ".[direct]"       # separate Anthropic + Google API keys
pip install -e ".[all]"          # both backends available, switch anytime
```

Requires Python 3.10+. No system dependencies (PDF rendering uses PyMuPDF,
pure Python/C-extension, no poppler install needed).

## Configure your API key(s)

Two reviewer **backends** are supported — pick whichever matches the keys you
have. `--backend auto` (the default) picks Perplexity if `PERPLEXITY_API_KEY`
is set, otherwise direct. CLI flags win over environment variables, which win
over `config.yaml`.

**Backend 1: Perplexity API (one key, both reviewers)** — recommended if you
only have a Perplexity API key. Get one at [console.perplexity.ai](https://console.perplexity.ai)
(this is a separate product from a Perplexity account / Computer credits).

```bash
export PERPLEXITY_API_KEY=pplx-...
titan-curate run --input ... --sample <name> --backend perplexity
```

This calls Perplexity's Agent API once per reviewer role, pointed at
`anthropic/claude-sonnet-5` for the "claude_sonnet" role and
`google/gemini-3.1-pro-preview` for the "gemini" role by default (override with
`--perplexity-claude-model` / `--perplexity-gemini-model` or the matching env
vars). Full setup walkthrough: [`docs/HPC_SETUP.md`](docs/HPC_SETUP.md).

**Backend 2: direct Anthropic + Google keys** (the original design):

```bash
# Option A: environment variables (simplest)
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=...
titan-curate run --input ... --sample <name> --backend direct

# Option B: your own config file
cp config/config.example.yaml config.yaml   # then fill in keys/models
titan-curate run --input ... --sample <name> --config config.yaml

# Option C: per-invocation flags (handy for a personal key on a shared machine)
titan-curate run --input ... --sample <name> --anthropic-key sk-ant-... --gemini-key ...
```

You can run with only one reviewer role configured (`--skip-claude` /
`--skip-gemini`, or simply omit that key) — the tool will save that single
review, but the merged consensus report needs both.

## Run it

`--input` accepts two layouts:

- **Real cohort root** — a directory containing `titanCNA_ploidy2/`,
  `titanCNA_ploidy3/`, `titanCNA_ploidy4/`, ... subdirectories, each holding
  every sample's and cluster's flat `params.txt`/`segs.txt` plus a
  `<sample>_cluster<M>/` plot subfolder (the layout produced by the
  [GavinHaLab TitanCNA Nextflow pipeline](https://github.com/GavinHaLab/Nextflow-Pipelines/tree/main/TitanCNA)
  at cohort scale). Since this holds many samples, pair it with a
  sample-selection flag: `--sample`, `--samples`, `--sample-list-file`, or
  `--all-samples`.
- **Legacy single-sample folder** — a folder containing `ploidyN_clusterM/`
  subfolders directly for one sample (older/local layout, still supported).
  No sample-selection flag is needed here.

```bash
# See what samples are available in a cohort root:
titan-curate list-samples --input /fh/fast/ha_g/.../titan/hmm

# Single sample from a cohort root:
titan-curate run \
  --input /fh/fast/ha_g/.../titan/hmm \
  --sample 00-010_LN_L_WGS \
  --out-root results

# Several named samples in one run, sharing one cohort CSV:
titan-curate run --input /fh/fast/ha_g/.../titan/hmm \
  --samples 00-010_LN_L_WGS,00-020_PRST_N \
  --out-root results

# Every sample found under the cohort root:
titan-curate run --input /fh/fast/ha_g/.../titan/hmm --all-samples --out-root results

# Legacy single-sample folder (no --sample needed):
titan-curate run --input /path/to/00-010_LN_L_WGS --out results/00-010_LN_L_WGS
```

Useful flags:

```
--sample NAME                                  # one sample from a cohort root
--samples NAME1,NAME2                          # several named samples, one shared cohort CSV
--sample-list-file FILE                        # one sample name per line
--all-samples                                  # every sample discoverable under --input
--top-n 5                  # how many S_Dbw-ranked candidates to visually review (default 5)
--ambiguity-chromosomes chr4 chr7 chr8 chr12   # per-chromosome zooms for ploidy-doubling pairs
--dry-run                  # deterministic parsing + ranking only, no plots, no API calls, no cost
--backend {auto,direct,perplexity}             # reviewer transport (default auto)
--cohort-csv results/cohort_titan_curation_summary.csv   # shared append target across samples
--verbose-errors           # full tracebacks for per-sample failures in batch mode
```

In batch mode (`--samples`/`--sample-list-file`/`--all-samples`) a failure on
one sample is logged and skipped — it does not abort the rest of the batch.
Every sample still writes its own `results/<sample_id>/` folder, and every
successful consensus row is appended to the same `--cohort-csv`.

Run `--dry-run` first on any new dataset to sanity-check discovery/parsing
before spending API calls.

## Output

Exactly two deliverables per sample (plus the intermediate JSON evidence for
audit/reproducibility):

```
<out-root>/                                       # e.g. results/ (default) or --out-root
├── cohort_titan_curation_summary.csv           # <-- deliverable 2: one row per sample, shared/appended across the whole batch
└── <sample_id>/
    ├── evidence/
    │   ├── evidence.json              # full ranked candidate table + segment metrics
    │   └── candidate_metrics.csv
    ├── reviews/
    │   ├── claude_review.json         # raw structured output, reviewer = "claude_sonnet"
    │   └── gemini_review.json         # raw structured output, reviewer = "gemini"
    └── reports/
        └── <sample_id>_curation_report.md      # <-- deliverable 1: per-sample report
```

For a single-sample run without `--out-root`, pass `--out results/<sample_id>` directly and `--cohort-csv` explicitly if you want it somewhere specific (default: `results/cohort_titan_curation_summary.csv`).

## Batch / bigger data

For a real cohort root, use the built-in batch modes instead of shelling out a
loop — they share one `--cohort-csv`, isolate per-sample failures, and print a
batch summary at the end:

```bash
titan-curate run --input /fh/fast/ha_g/.../titan/hmm \
  --all-samples --out-root results --backend perplexity \
  --cohort-csv results/cohort_titan_curation_summary.csv
```

For the legacy single-sample-folder layout (or any other case where you
already have a list of folders), loop the CLI and point every run at the same
`--cohort-csv`:

```bash
for d in /data/titan_runs/*/; do
  titan-curate run --input "$d" --cohort-csv results/cohort_titan_curation_summary.csv
done
```

For SLURM array-job parallelism across hundreds of samples on an HPC cluster,
see [`docs/HPC_SETUP.md`](docs/HPC_SETUP.md).

## Repo layout

```
src/titan_curation/
  knowledge/
    skills.md            curation methodology -- the "plots are primary evidence" rule lives here
    titan_reference.md   condensed TITAN interpretation reference
  discovery.py            candidate discovery for BOTH layouts:
                            - real cohort root: titanCNA_ploidyN/ dirs, many samples
                            - legacy: ploidyN_clusterM/ subfolders, one sample
                          also: list_available_samples(), optimalClusterSolution.txt lookup
  parsing.py               params.txt / segs.txt parsers
  evidence_builder.py     ranking + segment-metric evidence.json / candidate_metrics.csv
  plots.py                 selective plot lookup (CNA/CNASEG/LOH/LOHSEG/CF/subclone,
                          PDF preferred else PNG) + on-demand PDF->PNG rendering (PyMuPDF)
  config.py                 API key / model / backend resolution (flag > env > config.yaml)
  reviewers/
    base.py                 shared system/user prompt construction, JSON schema
    claude_reviewer.py      Anthropic API backend (direct)
    gemini_reviewer.py      Google Generative AI API backend (direct)
    perplexity_reviewer.py  Perplexity Agent API backend (drives BOTH reviewer roles)
  consensus.py              merges both reviews into the per-sample report + cohort CSV row
  cli.py                     `titan-curate run` / `titan-curate list-samples` entry point
docs/HPC_SETUP.md          SLURM / shared-filesystem setup guide
config/config.example.yaml
.env.example
tests/
```

## Relationship to the Perplexity Computer prototype

The agentic workflow (fetching from OneDrive/SharePoint, orchestrating
subagents on the platform's own model access, no personal API keys) is
developed and iterated on in a Perplexity Computer project. This repository is
the portable version for running the *same reviewer methodology* against
larger local datasets with your own API keys, without a Perplexity account.

`src/titan_curation/knowledge/skills.md` and `titan_reference.md` are the
shared source of truth for the curation logic across both versions. The input
layer (OneDrive connector vs. local file path) and the reviewer transport
(Perplexity model access vs. Anthropic/Google API keys) intentionally differ
and are not synced — only the curation methodology and reporting format are
kept in step between the two.

## Syncing curation methodology from the Perplexity project

`knowledge/skills.md` and `knowledge/titan_reference.md` are the shared source
of truth between this repo and the Perplexity Computer prototype. When someone
updates the curation methodology there, sync it here with:

```bash
python scripts/sync_knowledge_from_perplexity.py \
  --project-files <path to the Perplexity project's file checkout> \
  --commit --push
```

Run it with no `--commit`/`--push` first to see a dry-run diff. It only ever
touches `src/titan_curation/knowledge/*.md` -- never `cli.py`, `config.py`, or
the reviewer backends, since the input layer and API-key handling are meant to
stay different between the two versions.

**This is a judgment call, not a blind copy.** Some wording in `skills.md`
(e.g. how plots are located/fetched) is intentionally phrased differently for
the OneDrive-connector version vs. this local-path CLI. Before running
`--commit`, read the diff: sync methodology changes (the "plots are primary
evidence" rule, QC steps, flag definitions), but keep input-mechanism-specific
phrasing as-is on each side.

Any of the TitanCNA Curation Agent Perplexity project's contributors can run
this themselves -- they already have write access to this GitHub repo via the
GavinHaLab org.

## License

MIT — see `LICENSE`.
