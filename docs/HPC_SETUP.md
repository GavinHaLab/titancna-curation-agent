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
  --verbose-errors
```

Submit with `sbatch run_batch.sh`. Swap `--all-samples` for
`--sample-list-file samples.txt` (one sample name per line) to run a curated
subset instead.

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

Because every task appends to the same `--cohort-csv`, avoid launching an
enormous number of tasks that finish at the exact same instant if your
cluster's shared filesystem is sensitive to concurrent small appends;
staggering (`--array=0-99%10` limits to 10 concurrent tasks) is a safe
default on Fred Hutch's `/fh/fast` storage.

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

## Troubleshooting

- **`HTTP 400: max_output_tokens is required when using Anthropic models`** —
  should not occur with this tool (it always sends `max_output_tokens`); if
  you see it after modifying `perplexity_reviewer.py`, check that argument
  wasn't dropped.
- **`ModuleNotFoundError: No module named 'perplexity'`** — you installed with
  a plain `pip install -e .` instead of `pip install -e ".[perplexity]"` (or
  `.[all]`). Re-run the install with the extra.
- **`ImportError: cannot import name 'Sentinel' from 'typing_extensions'`**
  (Option A, environment module) — the module's own bundled
  `typing_extensions` is older than pydantic needs, and it silently shadows
  any newer version you `pip install --user`, because loading the module
  sets `PYTHONPATH` to point at its site-packages ahead of `~/.local`. Fix:
  `unset PYTHONPATH` after `module load` and install into a venv, as shown
  in step 2 — reinstalling with `pip install --user` alone will NOT fix
  this even if it appears to succeed.
- **Segfault (`core dumped`) partway through a run**, especially with a
  `Relink ... for IFUNC symbol` line right before the crash — this is glibc
  failing to safely load a compiled extension (commonly `pydantic_core`'s
  `.so`) because of a conflicting native library elsewhere on the loader
  path. We saw this specifically when installing into the shared `~/.local`
  on an account that also has many unrelated heavy packages installed
  (torch, cudf, numba, etc., each bundling their own native libraries) — the
  exact same `pydantic_core` version worked perfectly in an isolated venv.
  Fix: install into a clean venv (step 2's Option A), not `--user`/`~/.local`
  directly.
- **`pip install -e .` fails compiling PyMuPDF from source** (C++ errors
  mentioning `mupdfcpp_swig`, `PyString_FromString was not declared`, or
  a long `c++ ... -o platform/python/mupdfcpp_swig...cpp.o` command failing)
  — this means pip couldn't find a prebuilt wheel for your platform (most
  likely an HPC login/compute node with an older glibc than PyMuPDF's
  current manylinux wheel baseline requires) and fell back to building
  from source, which then hits a real upstream bug in that mupdf source
  release. Reproduced and confirmed on the Fred Hutch rhino nodes
  (glibc 2.27/Ubuntu 18.04-based): `pip install --only-binary=:all: pymupdf`
  shows **1.26.0 is the last PyMuPDF release with a wheel compatible with
  that glibc** — every version from 1.26.1 up (including the whole 1.27.x/
  1.28.x line) is source-only or needs a newer manylinux baseline there, so
  a plain `pip install "PyMuPDF<1.28"` still picks the newest matching
  version (1.27.2) first and fails the same way. `pyproject.toml` now pins
  `PyMuPDF<=1.26.0`, verified with a full clean install (pip 23.2.1,
  same rhino environment) that resolves straight to the `1.26.0` wheel with
  zero compilation. A fresh `git pull` + reinstall should fix it. If it
  still tries to build from source on a *different* cluster/platform:
  (1) run `pip install --upgrade pip` first — an old pip can fail to
  recognize a wheel that would otherwise work; (2) run
  `pip install --only-binary=:all: "pymupdf<=1.26.0"` to see directly
  whether a compatible wheel exists there at all; (3) check `ldd --version`
  — a very old glibc may mean no PyMuPDF wheel exists for your platform,
  in which case ask your cluster admin for a newer OS/compute-node image or
  a module with a newer
  system Python.
- **Auth errors from the Perplexity API** — confirm `echo $PERPLEXITY_API_KEY`
  is non-empty in the job's environment; `source`d env files inside a SLURM
  script only take effect if `source` runs before the `titan-curate` call, and
  `sbatch` does not automatically inherit your interactive shell's exported
  variables unless you pass `--export=ALL` or source them inside the script
  (as shown above).
- **One sample fails partway through a batch** — batch mode (`--samples`,
  `--sample-list-file`, `--all-samples`) already catches and logs per-sample
  exceptions and continues; check the batch summary at the end of the log for
  which sample(s) failed and why (`--verbose-errors` for full tracebacks).
- **Slow discovery on very large cohort roots** — `list_available_samples`
  and `discover_candidates_for_sample` only glob within the specific
  `titanCNA_ploidyN/` directories and (for a single sample) only files
  matching that sample's name via `glob.escape`, so cost scales with cohort
  size only for the initial directory listing, not per-file reads.
- **`titan-curate` seems to ignore packages/env changes in your active conda
  env** (e.g. "no module named X" for a package you just installed with
  `pip install ...` inside the env, or API keys that were correctly
  `source`d yet still report missing) — the installed `titan-curate` script
  has a shebang line pinned to whichever Python ran `pip install -e .` at
  install time, which is **not necessarily** the `python3` currently on your
  `PATH`. This happens silently if `pip install -e .` was ever run from the
  wrong active env (or fell back to a `--user` install under a base/module
  Python because the env's own site-packages wasn't writable — watch for
  "Defaulting to user installation because normal site-packages is not
  writeable" in the pip output). Diagnose with:
  ```bash
  which titan-curate
  head -1 "$(which titan-curate)"        # the interpreter it actually runs under
  which python3                          # what your active env resolves to
  ```
  If those two interpreters differ, `titan-curate` is running under a
  different environment than the one you're inspecting with `pip
  show`/`python3 -c "import ..."`. Fix by reinstalling from inside the
  correct, already-activated env (`conda activate titan-curate && cd
  titancna-curation-agent && pip install -e ".[perplexity]"`), which
  overwrites the console script with one pinned to that env's interpreter.
