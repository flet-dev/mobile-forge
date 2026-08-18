"""Exact and approximate nearest-neighbour search over 20,000 embeddings generated on device."""

import os
import sys
import time

import faiss
import flet as ft
import numpy as np

N = 20_000
D = 96
CLUSTERS = 100
QUERIES = 100
K = 10
NLIST = 256
NEIGHBOURS = 32

# float32 inner products over 96 terms disagree in the last bit or two; anything a
# broken BLAS produces is orders of magnitude larger than this.
TOLERANCE = 1e-4

# Durable, app-private storage: an index written here survives restarts, unlike the
# cache and temp directories.
INDEX_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "vectors.ivf")

# One slider position per (IVF nprobe, HNSW efSearch) pair.
SETTINGS = [(1, 8), (2, 16), (4, 32), (8, 64), (16, 128), (32, 256)]


def make_vectors():
    """Generate clustered, L2-normalised float32 embeddings and a batch of queries.

    Real sentence embeddings sit in tight clusters, and IVF is only worth its inverted
    lists when the data has that structure — on uniform noise the same index recalls a
    fraction of what it does here. Everything is float32 from the first allocation,
    because handing add() a float64 array makes faiss convert it and hold a third copy.
    """
    rng = np.random.default_rng(20260818)
    centres = rng.standard_normal((CLUSTERS, D), dtype=np.float32)
    xb = centres[rng.integers(CLUSTERS, size=N)]
    xb += 0.35 * rng.standard_normal((N, D), dtype=np.float32)
    faiss.normalize_L2(xb)
    xq = xb[rng.choice(N, QUERIES, replace=False)]
    xq += 0.10 * rng.standard_normal((QUERIES, D), dtype=np.float32)
    faiss.normalize_L2(xq)
    return xb, xq


def numpy_top_k(xb, xq):
    """Top-K by inner product computed in numpy alone, plus the similarity matrix.

    This is the yardstick: it never touches faiss, so grading the exact index against
    it checks this wheel's own arithmetic rather than checking faiss against itself.
    """
    sims = xq @ xb.T
    top = np.argpartition(-sims, K, axis=1)[:, :K]
    rows = np.arange(len(xq))[:, None]
    return sims, top[rows, np.argsort(-sims[rows, top], axis=1)]


def recall_at_k(got, want):
    """Mean fraction of each row's true top-K that the returned ids actually contain."""
    return np.mean([len(set(a) & set(b)) for a, b in zip(got, want)]) / K


def timed_search(index, xq):
    """Run one K-nearest search and report how long it took, in milliseconds."""
    started = time.perf_counter()
    distances, ids = index.search(xq, K)
    return distances, ids, (time.perf_counter() - started) * 1000


def main(page: ft.Page):
    """Three indexes over one set of vectors, each graded against the exact answer.

    The header line makes the build describe itself: the SIMD level reported by
    `get_compile_options()` and the OpenMP thread count both differ by platform, and
    reading them off the screen beats reading them off any documentation.
    """

    xq = exact_ids = None
    flat = ivf = hnsw = None
    flat_recall = flat_ms = 0.0
    sizes = ()

    def work(job, message):
        """Run `job` in the thread pool with the slider disabled and the spinner up.

        `page.run_thread` never retrieves the worker's future, so an exception raised
        inside one would vanish without a crash, a log line or a trace — hence the
        catch. The closing `page.update()` is equally mandatory: auto-update does not
        reach background threads.
        """

        def runner():
            try:
                job()
            except Exception as error:
                status.value = f"{type(error).__name__}: {error}"
            effort.disabled = False
            spinner.visible = False
            page.update()

        status.value = message
        effort.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(runner)

    def build():
        """Generate the vectors, build all three indexes, and check Flat against numpy.

        The exact index has to return the same ids and the same values as numpy, so
        anything but PASS means the arithmetic in this wheel is wrong — the one failure
        a demo can catch that a benchmark cannot.
        """
        nonlocal xq, exact_ids, flat, ivf, hnsw, flat_recall, flat_ms, sizes
        xb, xq = make_vectors()
        sims, exact_ids = numpy_top_k(xb, xq)

        flat = faiss.IndexFlatIP(D)
        flat.add(xb)
        distances, flat_ids, flat_ms = timed_search(flat, xq)
        flat_recall = recall_at_k(flat_ids, exact_ids)
        agreement = np.abs(distances - np.take_along_axis(sims, flat_ids, axis=1)).max()
        passed = flat_recall == 1.0 and agreement < TOLERANCE
        check.value = (
            f"{'PASS' if passed else 'FAIL'} · Flat vs numpy — recall@{K} "
            f"{flat_recall:.4f}, largest distance disagreement {agreement:.1e} "
            f"against a {TOLERANCE:.0e} tolerance"
        )
        check.color = ft.Colors.GREEN if passed else ft.Colors.RED

        ivf = faiss.IndexIVFFlat(
            faiss.IndexFlatIP(D), D, NLIST, faiss.METRIC_INNER_PRODUCT
        )
        ivf.train(xb)
        ivf.add(xb)

        hnsw = faiss.IndexHNSWFlat(D, NEIGHBOURS, faiss.METRIC_INNER_PRODUCT)
        hnsw.add(xb)

        faiss.write_index(ivf, INDEX_PATH)
        sizes = (
            len(faiss.serialize_index(flat)),
            os.path.getsize(INDEX_PATH),
            len(faiss.serialize_index(hnsw)),
        )

        # IO_FLAG_MMAP leaves the inverted lists in the page cache instead of copying
        # them onto the heap. read_index accepts it for any index but only IVF benefits;
        # Flat and HNSW need IO_FLAG_MMAP_IFC instead.
        reloaded = faiss.read_index(INDEX_PATH, faiss.IO_FLAG_MMAP)
        reloaded.nprobe = ivf.nprobe = SETTINGS[int(effort.value)][0]
        same = (reloaded.search(xq, K)[1] == ivf.search(xq, K)[1]).all()
        stored.value = (
            f"{INDEX_PATH} — {sizes[1]:,} bytes, reloaded with IO_FLAG_MMAP, "
            f"ntotal {reloaded.ntotal:,}, same ids as the index in memory: {bool(same)}"
        )
        rebuild_table()

    def rebuild_table():
        """Re-search the two approximate indexes at the slider's setting and redraw.

        Only the searches are repeated. Neither index depends on `nprobe` or
        `efSearch` — that they are query-time knobs is the reason to tune them here
        rather than rebuild.
        """
        nprobe, ef_search = SETTINGS[int(effort.value)]
        ivf.nprobe = nprobe
        hnsw.hnsw.efSearch = ef_search
        _, ivf_ids, ivf_ms = timed_search(ivf, xq)
        _, hnsw_ids, hnsw_ms = timed_search(hnsw, xq)
        table.controls = [
            table_row(("index", "recall", "ms", "bytes"), ft.FontWeight.BOLD),
            table_row(
                (
                    "Flat (exact)",
                    f"{flat_recall:.4f}",
                    f"{flat_ms:.0f}",
                    f"{sizes[0]:,}",
                )
            ),
            table_row(
                (
                    f"IVF{NLIST} nprobe={nprobe}",
                    f"{recall_at_k(ivf_ids, exact_ids):.4f}",
                    f"{ivf_ms:.0f}",
                    f"{sizes[1]:,}",
                )
            ),
            table_row(
                (
                    f"HNSW{NEIGHBOURS} ef={ef_search}",
                    f"{recall_at_k(hnsw_ids, exact_ids):.4f}",
                    f"{hnsw_ms:.0f}",
                    f"{sizes[2]:,}",
                )
            ),
        ]
        status.value = (
            f"{N:,} vectors x {D} dims, {QUERIES} queries, k={K}. Every row is graded "
            f"against the numpy top-{K}, not against the row above it. Sizes: "
            f"Flat = N*d*4, IVF = N*(d*4+8) + nlist*d*4, HNSW = Flat + N*(8*M+16), "
            f"each plus a small header."
        )

    def table_row(cells, weight=None):
        """One line of the table, sized by expand weights so it can never overflow.

        A non-scrolling Row wider than a phone screen draws Flutter's striped overflow
        marker; weights make the four columns share whatever width there is.
        """
        return ft.Row(
            controls=[
                ft.Text(cell, size=12, weight=weight, expand=span)
                for cell, span in zip(cells, (7, 4, 3, 7))
            ]
        )

    def on_effort_change():
        """Slider release. `on_change_end` fires once, where `on_change` fires per step."""
        work(rebuild_table, "Searching…")

    page.appbar = ft.AppBar(title=ft.Text("faiss nearest"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"faiss {faiss.__version__} · "
                        f"{faiss.get_compile_options().strip()} · "
                        f"omp={faiss.omp_get_max_threads()} · "
                        f"gpus={faiss.get_num_gpus()} · numpy {np.__version__} · "
                        f"py{sys.version_info.major}.{sys.version_info.minor}",
                        size=11,
                        selectable=True,
                    ),
                    check := ft.Text(size=14, weight=ft.FontWeight.BOLD),
                    table := ft.Column(spacing=2),
                    ft.Text("Search effort", size=12),
                    effort := ft.Slider(
                        min=0,
                        max=len(SETTINGS) - 1,
                        divisions=len(SETTINGS) - 1,
                        value=3,
                        disabled=True,
                        on_change_end=on_effort_change,
                    ),
                    spinner := ft.ProgressRing(visible=False),
                    status := ft.Text(size=11),
                    stored := ft.Text(size=11, selectable=True),
                ],
            ),
        )
    )

    work(build, f"Generating {N:,} vectors and building three indexes…")


if __name__ == "__main__":
    ft.run(main)
