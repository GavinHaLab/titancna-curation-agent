#!/usr/bin/env bash
# Concatenate a SLURM array job's per-task log files (one per sample, named
# titan_curate_<jobid>_<array_index>.log per the array-job template in
# docs/HPC_SETUP.md) into a single combined log, ordered by array index.
#
# Why not have every task write to one shared log file directly instead?
# Many processes appending to the same file concurrently risks interleaved/
# mangled lines (each process's multi-line sample output isn't written
# atomically) -- SLURM's one-file-per-task default avoids that, at the cost
# of ending up with one log file per sample. This script recombines them
# after the job finishes, when it's safe to do so sequentially.
#
# Usage:
#   scripts/consolidate_array_logs.sh [logs_dir] [output_file]
#
# Defaults: logs_dir=logs, output_file=logs/titan_curate_combined.log

set -euo pipefail

LOGS_DIR="${1:-logs}"
OUT_FILE="${2:-$LOGS_DIR/titan_curate_combined.log}"

if [ ! -d "$LOGS_DIR" ]; then
    echo "error: logs directory '$LOGS_DIR' does not exist" >&2
    exit 1
fi

# Match titan_curate_<jobid>_<array_index>.log and sort numerically by
# array index (not lexicographically -- task 10 must sort after task 9,
# not after task 1).
shopt -s nullglob
log_files=("$LOGS_DIR"/titan_curate_*_*.log)
shopt -u nullglob

if [ ${#log_files[@]} -eq 0 ]; then
    echo "error: no titan_curate_*_*.log files found under '$LOGS_DIR'" >&2
    exit 1
fi

sorted_files=$(for f in "${log_files[@]}"; do
    array_index=$(basename "$f" .log | awk -F'_' '{print $NF}')
    printf '%s\t%s\n' "$array_index" "$f"
done | sort -n -k1,1 | cut -f2)

: > "$OUT_FILE"
count=0
while IFS= read -r f; do
    {
        echo "===== $(basename "$f") ====="
        cat "$f"
        echo
    } >> "$OUT_FILE"
    count=$((count + 1))
done <<< "$sorted_files"

echo "Combined $count log file(s) into $OUT_FILE"
