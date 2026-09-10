# TitanCNA Curation Agent (CLI)

Curates TitanCNA copy-number/LOH candidate solutions for a tumor sample using
deterministic statistics for triage and two independent vision-capable LLM
reviewers (Claude and Gemini) for the actual visual QC call. Point it at a
local folder of TITAN HMM output — no OneDrive, no upload limits, no Perplexity
account required. Bring your own Anthropic and/or Google API key.

This is the standalone, bring-your-own-API-key counterpart to the
["TitanCNA Curation Agent"](#relationship-to-the-perplexity-computer-prototype)
prototype developed on Perplexity Computer. The curation methodology
(`src/titan_curation/knowledge/skills.md`) is the shared source of truth
between both.

## Why two reviewers, and why plots first

TitanCNA's own statistical ranking (S_Dbw / log-likelihood) is necessary but
not sufficient — it is frequently wrong exactly when it matters most: wrong
ploidy fits and 2N/4N ploidy-doubling ambiguity often score *better* on S_Dbw
than the biologically correct solution. This tool's core design rule (see
`knowledge/skills.md`) is: **plots are primary evidence, text statistics are
secondary corroboration.** Both reviewers are told this explicitly and are
shown the genome-wide (and, for closely-ranked pairs, per-chromosome) CNA/LOH
plots before being given the numeric ranking.

## Install

```bash
git clone <this-repo>
cd titan-curation-agent
pip install -e .
```

Requires Python 3.10+. No system dependencies (PDF rendering uses PyMuPDF,
pure Python/C-extension, no poppler install needed).

## Configure your API key(s)

Any one of these works; CLI flags win over environment variables, which win
over `config.yaml`:

```bash
# Option A: environment variables (simplest)
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=...

# Option B: your own config file
cp config/config.example.yaml config.yaml   # then fill in keys/models
titan-curate run --input ... --config config.yaml

# Option C: per-invocation flags (handy for a personal key on a shared machine)
titan-curate run --input ... --anthropic-key sk-ant-... --gemini-key ...
```

You can run with only one provider configured (`--skip-claude` / `--skip-gemini`,
or simply omit that key) — the tool will save that single review, but the
merged consensus report needs both.

## Run it

```bash
titan-curate run \
  --input /path/to/00-010_LN_L_WGS \
  --out results/00-010_LN_L_WGS
```

`--input` accepts:
- a sample folder containing `ploidyN_clusterM/` subfolders (the standard
  layout produced by the [GavinHaLab TitanCNA Nextflow pipeline](https://github.com/GavinHaLab/Nextflow-Pipelines/tree/main/TitanCNA)), or
- a single candidate folder directly (one `params.txt` + `segs.txt` + plots).

Useful flags:

```
--top-n 5                  # how many S_Dbw-ranked candidates to visually review (default 5)
--ambiguity-chromosomes chr4 chr7 chr8 chr12   # per-chromosome zooms for ploidy-doubling pairs
--dry-run                  # deterministic parsing + ranking only, no plots, no API calls, no cost
--sample-id 00-010_LN_L_WGS
--cohort-csv results/cohort_titan_curation_summary.csv   # append target across many samples
```

Run `--dry-run` first on any new dataset to sanity-check discovery/parsing
before spending API calls.

## Output

Exactly two deliverables per sample (plus the intermediate JSON evidence for
audit/reproducibility):

```
results/<sample_id>/
├── evidence/
│   ├── evidence.json              # full ranked candidate table + segment metrics
│   └── candidate_metrics.csv
├── reviews/
│   ├── claude_review.json         # raw structured output, reviewer = "claude_sonnet"
│   └── gemini_review.json         # raw structured output, reviewer = "gemini"
└── reports/
    ├── <sample_id>_curation_report.md      # <-- deliverable 1: per-sample report
    └── cohort_titan_curation_summary.csv   # <-- deliverable 2: one row per sample, appended
```

## Batch / bigger data

Loop the CLI over many sample folders and point every run at the same
`--cohort-csv` to build one running cohort table:

```bash
for d in /data/titan_runs/*/; do
  titan-curate run --input "$d" --cohort-csv results/cohort_titan_curation_summary.csv
done
```

## Repo layout

```
src/titan_curation/
  knowledge/
    skills.md            curation methodology -- the "plots are primary evidence" rule lives here
    titan_reference.md   condensed TITAN interpretation reference
  discovery.py            find ploidyN_clusterM candidate folders
  parsing.py               params.txt / segs.txt parsers
  evidence_builder.py     ranking + segment-metric evidence.json / candidate_metrics.csv
  plots.py                 selective plot lookup + on-demand PDF->PNG rendering (PyMuPDF)
  config.py                 API key / model resolution (flag > env > config.yaml)
  reviewers/
    base.py                 shared system/user prompt construction, JSON schema
    claude_reviewer.py      Anthropic API backend
    gemini_reviewer.py      Google Generative AI API backend
  consensus.py              merges both reviews into the per-sample report + cohort CSV row
  cli.py                     `titan-curate` entry point
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

## License

MIT — see `LICENSE`.
