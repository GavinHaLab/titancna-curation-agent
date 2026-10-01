# Running on an HPC cluster (Fred Hutch SciComp / generic SLURM)

This guide sets up `titan-curation-agent` on a shared HPC filesystem and runs
it against a real TITAN cohort directory using the Perplexity API backend
(one key drives both the Claude and Gemini reviewer roles). Everything here
also works with the direct Anthropic + Google backend — swap the key names
where noted.

Assumes a Fred Hutch-style environment (login/submission nodes, `module`/
Lmod environment modules, `/fh/fast/...` shared project storage, SLURM
scheduler) but every step is standard SLURM and will work on most academic
HPC clusters with minor path changes.

## 1. Log in and pick a working directory

```bash
ssh rhino.fredhutch.org        # or your cluster's login/submission node
mkdir -p /fh/fast/ha_g/user/$(whoami)/titan_curation
cd /fh/fast/ha_g/user/$(whoami)/titan_curation
```

Use your lab's fast-storage project space (`/fh/fast/<lab>/...`), not your
home directory, if the TITAN cohort output itself lives there — this avoids
slow cross-filesystem I/O when the tool reads `params.txt`/`segs.txt`/plots.

## 2. Get a Python 3.10+ environment

Fred Hutch SciComp nodes have Lmod environment modules. Either load a Python
module or (more reproducibly) create your own conda/mamba environment:

```bash
# Option A: environment module (check `module avail python` for exact name/version)
module load Python/3.11.5-GCCcore-13.2.0
unset PYTHONPATH        # see warning below -- required
python3 -m venv ~/.venvs/titan-curate
source ~/.venvs/titan-curate/bin/activate

# Option B: your own conda/mamba environment (recommended for a pinned, portable setup)
module load Miniconda3
conda create -n titan-curate python=3.11 -y
conda activate titan-curate
```

**With Option A, always create and activate a venv (as shown above) — do
not just `pip install --user` directly against the module's Python.**
Loading a Python module sets `PYTHONPATH` to that module's own
site-packages, which (a) silently shadows any `pip install --user` package
of the same name with the module's own bundled version, no matter how
recent a version you install, and (b) even survives inside a *plain*
`python3 -m venv`, defeating its isolation, unless `PYTHONPATH` is unset
first. We hit both failure modes for real on these nodes: an old bundled
`typing_extensions` (missing `Sentinel`, needed by pydantic) shadowed a
newer `--user`-installed one and broke imports; separately, installing into
the shared `~/.local` (which on a long-lived account accumulates many
unrelated heavy packages -- torch, cudf, numba, etc. -- each with their own
bundled native libraries) caused a real segfault
(`Relink ... librt.so.1 for IFUNC symbol clock_gettime`) loading
`pydantic_core`'s compiled extension, that disappeared entirely once
installed into a clean, isolated venv instead. `unset PYTHONPATH` + a venv
fixes both at once by fully isolating from both the module's bundled
packages and your account's shared `~/.local`.

## 3. Install the package

```bash
git clone https://github.com/GavinHaLab/titancna-curation-agent.git
cd titancna-curation-agent

# Perplexity backend only (recommended if you have one Perplexity API key):
pip install -e ".[perplexity]"

# Or install both backends so you can switch freely:
pip install -e ".[all]"
```

Verify:

```bash
titan-curate --help
titan-curate list-samples --input /fh/fast/ha_g/projects/ProstateTAN/.../titan/hmm
```

## 4. Store your API key securely

**Never commit a real key, and never put it in a script that lives in a
shared or world-readable location.** On a shared HPC filesystem:

```bash
# Create a private env file that only you can read/write
cp .env.example ~/.titan_curate.env
chmod 600 ~/.titan_curate.env
```

Edit `~/.titan_curate.env` and fill in:

```bash
PERPLEXITY_API_KEY=pplx-...
```

(Get a key at [console.perplexity.ai](https://console.perplexity.ai) — this
is a separate product from a personal Perplexity account and from Perplexity
Computer credits; it is billed independently.)

Load it into your shell (interactively or at the top of a SLURM script):

```bash
set -a
source ~/.titan_curate.env
set +a
```

Confirm `.gitignore` excludes `.env`/`*.env` before ever working inside the
repo directory with a real key nearby (it already does by default — verify
with `git check-ignore -v ~/.titan_curate.env` if you ever move it inside the
repo, which is not recommended).

If your institution provides a secrets manager (e.g. Vault) prefer that over
a plaintext file; the `--perplexity-key` CLI flag and `PERPLEXITY_API_KEY` env
var both accept whatever your secrets tooling injects at runtime.

## 5. Quick interactive test (one sample, dry run)

Before spending any API budget, sanity-check discovery and ranking:

```bash
source ~/.titan_curate.env
titan-curate run \
  --input /fh/fast/ha_g/projects/ProstateTAN/ProstateTAN2026/data/Tumor/TITAN/all/TITAN_all_tan_1/titan/hmm \
  --sample 00-010_LN_L_WGS \
  --out-root /fh/fast/ha_g/user/$(whoami)/titan_curation/results \
  --dry-run
```

This parses every `params.txt`/`segs.txt` for that sample, ranks candidates by
S_Dbw, flags ploidy-doubling ambiguity, and writes `evidence.json` — with zero
model calls. If the ranked list and ambiguity flags look right, drop
`--dry-run` and add `--backend perplexity` for the full run with both
reviewers:

```bash
titan-curate run \
  --input /fh/fast/ha_g/projects/.../titan/hmm \
  --sample 00-010_LN_L_WGS \
  --out-root /fh/fast/ha_g/user/$(whoami)/titan_curation/results \
  --backend perplexity
```

## 6. Batch: run every sample (or a named subset) in one SLURM job

For a modest cohort, the CLI's own batch mode is simplest — one job, one
process, sequential over samples, shared cohort CSV, per-sample failures
logged and skipped rather than aborting the run:

```bash
#!/bin/bash
#SBATCH --job-name=titan-curate-batch
#SBATCH --partition=campus-new       # replace with your cluster's CPU partition
#SBATCH --time=08:00:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=2
#SBATCH --output=titan_curate_%j.log

set -euo pipefail
cd /fh/fast/ha_g/user/$USER/titan_curation/titancna-curation-agent
source ~/.titan_curate.env
# Option A (module + venv, see step 2) -- MUST unset PYTHONPATH before
# activating the venv, or the module's own site-packages silently shadows
# your installed packages / breaks isolation (see step 2 for why):
module load Python/3.11.5-GCCcore-13.2.0
unset PYTHONPATH
source ~/.venvs/titan-curate/bin/activate
# Option B: `conda activate titan-curate` instead of the three lines above

titan-curate run \
  --input /fh/fast/ha_g/projects/ProstateTAN/ProstateTAN2026/data/Tumor/TITAN/all/TITAN_all_tan_1/titan/hmm \
  --all-samples \
  --out-root /fh/fast/ha_g/user/$USER/titan_curation/results \
  --cohort-csv /fh/fast/ha_g/user/$USER/titan_curation/results/cohort_titan_curation_summary.csv \
  --backend perplexity \
  --verbose-errors \
  --skip-existing
```

Submit with `sbatch run_batch.sh`. Swap `--all-samples` for
`--sample-list-file samples.txt` (one sample name per line) to run a curated
subset instead.

`--skip-existing` makes this submission safe to resubmit as-is after a
partial failure (transient API errors, a node getting pre-empted, etc.) —
any sample that already has a full curation report under `--out-root` is
skipped instead of re-running (and re-billing) it.

## 7. Batch: SLURM array job for real parallelism across many samples

For a large cohort (dozens to hundreds of samples), an array job runs each
sample as its own task, all writing to the same shared `--cohort-csv`:

```bash
#!/bin/bash
#SBATCH --job-name=titan-curate-array
#SBATCH --partition=campus-new
#SBATCH --time=02:00:00
#SBATCH --mem=4G
#SBATCH --cpus-per-task=1
#SBATCH --array=0-99                 # size this to (number of samples - 1)
#SBATCH --output=logs/titan_curate_%A_%a.log

set -euo pipefail
cd /fh/fast/ha_g/user/$USER/titan_curation/titancna-curation-agent
source ~/.titan_curate.env
module load Python/3.11.5-GCCcore-13.2.0
unset PYTHONPATH
source ~/.venvs/titan-curate/bin/activate   # or `conda activate titan-curate`

COHORT_ROOT=/fh/fast/ha_g/projects/ProstateTAN/ProstateTAN2026/data/Tumor/TITAN/all/TITAN_all_tan_1/titan/hmm
OUT_ROOT=/fh/fast/ha_g/user/$USER/titan_curation/results
COHORT_CSV=$OUT_ROOT/cohort_titan_curation_summary.csv

# Build the sample list once (outside the array, e.g. in a setup step or
# committed to the repo), then index into it by SLURM_ARRAY_TASK_ID:
SAMPLE=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" samples.txt)

titan-curate run \
  --input "$COHORT_ROOT" \
  --sample "$SAMPLE" \
  --out-root "$OUT_ROOT" \
  --cohort-csv "$COHORT_CSV" \
  --backend perplexity
```

Generate `samples.txt` first and size `--array` to match:

```bash
mkdir -p logs
titan-curate list-samples --input "$COHORT_ROOT" | tail -n +2 | awk '{print $1}' > samples.txt
wc -l samples.txt   # size --array=0-<N-1> to this count
sbatch run_array.sh
```

Every task writes/updates its own row in the same shared `--cohort-csv`
under an exclusive file lock (`flock`), so concurrent tasks serialize safely
instead of racing each other's writes or producing duplicate rows on a
rerun — verified directly with 20 real concurrent processes writing the
same file. No need to artificially limit concurrency for this reason; size
`--array` and any `%N` throttling based on your cluster's actual job-slot
or API-rate-limit constraints instead.

**Resuming after a partial failure:** rerunning the same `sbatch` submission
(or `sbatch --array=<failed task indices>`) re-runs every task from scratch
by default, including both reviewer API calls, even for samples that already
completed. Add `--skip-existing` to the `titan-curate run` call so each task
skips cleanly (no API cost) if its sample's report already exists:

```bash
titan-curate run \
  --input "$COHORT_ROOT" \
  --sample "$SAMPLE" \
  --out-root "$OUT_ROOT" \
  --cohort-csv "$COHORT_CSV" \
  --backend perplexity \
  --skip-existing
```

**Consolidating the per-task logs:** an array job produces one log file per
sample (`logs/titan_curate_<jobid>_<array_index>.log`), which gets unwieldy
at scale. Each task writing to one *shared* log file directly isn't safe --
concurrent processes interleaving multi-line output into the same file risks
mangled lines -- so instead, run `scripts/consolidate_array_logs.sh` once the
job finishes to concatenate them (sorted by array index, not alphabetically,
so task 10 sorts after task 9) into a single combined log:

```bash
scripts/consolidate_array_logs.sh logs   # writes logs/titan_curate_combined.log
```

Pass a second argument to control the output path:
`scripts/consolidate_array_logs.sh logs /fh/fast/ha_g/user/$USER/titan_curation/combined.log`.

## 8. Checking results

```
results/
├── 00-010_LN_L_WGS/
│   ├── evidence/evidence.json
│   ├── reviews/{claude_review.json, gemini_review.json}
│   └── reports/00-010_LN_L_WGS_curation_report.md
├── 00-020_PRST_N/
│   └── ...
└── cohort_titan_curation_summary.csv   # one row per sample, appended across the whole batch
```

Pull `cohort_titan_curation_summary.csv` and the per-sample `*_curation_report.md`
files back to a local machine (`rsync`/`scp` from the login node) for human
review of anything flagged.

