import csv
import multiprocessing
import os
import threading

from titan_curation.consensus import _upsert_cohort_csv_row


def _read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_upsert_appends_new_samples(tmp_path):
    out_csv = str(tmp_path / "cohort.csv")
    _upsert_cohort_csv_row(out_csv, {"sample_id": "A", "val": "1"})
    _upsert_cohort_csv_row(out_csv, {"sample_id": "B", "val": "1"})
    rows = _read_rows(out_csv)
    assert {r["sample_id"] for r in rows} == {"A", "B"}


def test_upsert_replaces_rather_than_duplicates(tmp_path):
    """A rerun of the same sample (common after a transient 429/segfault/etc.
    forces a retry) must replace its old row, not append a duplicate -- this
    is exactly the bug that produced a real cohort CSV with one sample
    appearing 9 times across repeated reruns."""
    out_csv = str(tmp_path / "cohort.csv")
    _upsert_cohort_csv_row(out_csv, {"sample_id": "A", "val": "1"})
    _upsert_cohort_csv_row(out_csv, {"sample_id": "B", "val": "1"})
    _upsert_cohort_csv_row(out_csv, {"sample_id": "A", "val": "2"})
    _upsert_cohort_csv_row(out_csv, {"sample_id": "A", "val": "3"})

    rows = _read_rows(out_csv)
    assert len(rows) == 2
    by_id = {r["sample_id"]: r for r in rows}
    assert by_id["A"]["val"] == "3"  # latest write wins
    assert by_id["B"]["val"] == "1"


def test_upsert_writes_header(tmp_path):
    out_csv = str(tmp_path / "cohort.csv")
    _upsert_cohort_csv_row(out_csv, {"sample_id": "A", "val": "1"})
    with open(out_csv) as f:
        header = f.readline().strip()
    assert header == "sample_id,val"


def _worker(out_csv, sample_id):
    _upsert_cohort_csv_row(out_csv, {"sample_id": sample_id, "val": "run1"})


def test_upsert_concurrent_writers_no_lost_updates(tmp_path):
    """Simulates the documented SLURM array-job pattern: many independent
    processes writing different samples' rows to the same shared cohort CSV
    at once. The read-filter-rewrite cycle is protected by an exclusive
    flock, so concurrent writers must serialize instead of racing each
    other's rewrites -- every row must survive, with zero duplicates."""
    out_csv = str(tmp_path / "cohort.csv")
    n = 10
    procs = [
        multiprocessing.Process(target=_worker, args=(out_csv, f"sample_{i}"))
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    rows = _read_rows(out_csv)
    sample_ids = [r["sample_id"] for r in rows]
    assert len(sample_ids) == n
    assert len(set(sample_ids)) == n  # no duplicates, no lost writes


def test_upsert_concurrent_threads_no_lost_updates(tmp_path):
    """Regression test for a real data-loss bug: cli.py's --workers uses a
    ThreadPoolExecutor, so in production the concurrent writers are THREADS
    in one process, not separate processes -- a materially different
    pattern from test_upsert_concurrent_writers_no_lost_updates above (which
    uses multiprocessing.Process). A real --workers 3 run against an
    NFS-mounted --out-root lost 46 of 51 completed samples' rows (only the
    last few writers' rows survived) despite the flock in
    _upsert_cohort_csv_row -- flock() is not reliably serializing concurrent
    access on that filesystem. Fixed with an in-process threading.Lock()
    that is unconditionally correct regardless of what the filesystem does
    with flock. This test uses real threads (not multiprocessing) to match
    the actual production concurrency pattern."""
    out_csv = str(tmp_path / "cohort.csv")
    n = 20
    threads = [
        threading.Thread(target=_worker, args=(out_csv, f"sample_{i}"))
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive()

    rows = _read_rows(out_csv)
    sample_ids = [r["sample_id"] for r in rows]
    assert len(sample_ids) == n, f"expected {n} rows, got {len(sample_ids)} -- lost writes"
    assert len(set(sample_ids)) == n  # no duplicates either
