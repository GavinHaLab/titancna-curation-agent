import multiprocessing
import os

from titan_curation.plots import render_pdf_to_png


def _make_pdf(path, text="test plot"):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    doc.save(str(path))
    doc.close()


def test_render_pdf_to_png_basic(tmp_path):
    pdf_path = tmp_path / "plot.pdf"
    _make_pdf(pdf_path)
    cache_root = str(tmp_path / "cache")

    out_path = render_pdf_to_png(str(pdf_path), cache_root)
    assert os.path.isfile(out_path)
    assert out_path.endswith(".png")
    assert os.path.getsize(out_path) > 0


def test_render_pdf_to_png_caches_on_repeat_call(tmp_path):
    pdf_path = tmp_path / "plot.pdf"
    _make_pdf(pdf_path)
    cache_root = str(tmp_path / "cache")

    out_path_1 = render_pdf_to_png(str(pdf_path), cache_root)
    mtime_1 = os.path.getmtime(out_path_1)
    out_path_2 = render_pdf_to_png(str(pdf_path), cache_root)

    assert out_path_1 == out_path_2
    assert os.path.getmtime(out_path_2) == mtime_1  # not re-rendered


def test_render_pdf_to_png_leaves_no_tmp_files(tmp_path):
    pdf_path = tmp_path / "plot.pdf"
    _make_pdf(pdf_path)
    cache_root = tmp_path / "cache"

    render_pdf_to_png(str(pdf_path), str(cache_root))
    leftover_tmp = [f for f in os.listdir(cache_root) if ".tmp." in f]
    assert leftover_tmp == []


def _worker(pdf_path, cache_root, result_path):
    # Writes its result to a file rather than a multiprocessing.Queue --
    # Queue requires semaphores, which have been observed to segfault on
    # this account's shared HPC environment (an unrelated, pre-existing
    # native-library conflict, not something render_pdf_to_png can control).
    # File-based results sidestep that entirely and are just as reliable a
    # way to check every worker's outcome.
    try:
        out_path = render_pdf_to_png(pdf_path, cache_root)
        with open(result_path, "w") as f:
            f.write(f"ok\t{out_path}")
    except Exception as e:
        with open(result_path, "w") as f:
            f.write(f"error\t{e!r}")


def test_render_pdf_to_png_concurrent_processes_no_race(tmp_path):
    """Regression test for the "cannot open file ... File exists" bug: many
    independent processes rendering the exact same PDF into the exact same
    cache path at once must all succeed with identical output, not race on
    the destination file. render_pdf_to_png renders to a unique per-process
    temp file and atomically os.replace()s it into place specifically to
    guarantee this."""
    pdf_path = tmp_path / "plot.pdf"
    _make_pdf(pdf_path)
    cache_root = str(tmp_path / "cache")

    n = 8
    ctx = multiprocessing.get_context("fork")
    result_paths = [str(tmp_path / f"result_{i}.txt") for i in range(n)]
    procs = [
        ctx.Process(target=_worker, args=(str(pdf_path), cache_root, result_paths[i]))
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    results = []
    for rp in result_paths:
        with open(rp) as f:
            status, _, value = f.read().partition("\t")
            results.append((status, value))

    errors = [r for r in results if r[0] == "error"]
    assert errors == [], f"expected zero errors, got: {errors}"

    out_paths = {r[1] for r in results}
    assert len(out_paths) == 1  # every process agreed on the same cache path
    out_path = out_paths.pop()
    assert os.path.isfile(out_path)

    leftover_tmp = [f for f in os.listdir(cache_root) if ".tmp." in f]
    assert leftover_tmp == []
