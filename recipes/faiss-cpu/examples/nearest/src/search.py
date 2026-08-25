"""The faiss half of the example: vectors, three indexes over them, and graded searches."""

import os
import platform
import time

import faiss
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

# One slider position per (IVF nprobe, HNSW efSearch) pair, and where it starts.
SETTINGS = ((1, 8), (2, 16), (4, 32), (8, 64), (16, 128), (32, 256))
DEFAULT = 3

# Durable, app-private storage: an index written here survives restarts, unlike the
# cache and temp directories.
INDEX_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "vectors.ivf")


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


def persist(index, xq):
    """Write the index to app storage, read it back mapped, and compare the answers.

    What this proves is that the round trip is lossless, and nothing more: read_index
    accepts either mmap flag on any index and returns the same ids either way, so
    matching results can never be evidence that a mapping engaged. Only memory can say
    that. IO_FLAG_MMAP is the right flag for IVF; Flat and HNSW want IO_FLAG_MMAP_IFC.
    """
    faiss.write_index(index, INDEX_PATH)
    reloaded = faiss.read_index(INDEX_PATH, faiss.IO_FLAG_MMAP)
    reloaded.nprobe = index.nprobe
    same = bool((reloaded.search(xq, K)[1] == index.search(xq, K)[1]).all())
    return (
        f"{INDEX_PATH} — {os.path.getsize(INDEX_PATH):,} bytes written, reloaded with "
        f"IO_FLAG_MMAP: ntotal {reloaded.ntotal:,}, ids identical to the in-memory "
        f"index ({same}). That is a lossless round trip, not proof of the mapping."
    )


def build():
    """Generate the vectors, build all three indexes, and grade Flat against numpy.

    Everything comes back as plain values, so this runs and can be read with no screen
    attached. The exact index has to return both the same ids and the same distances as
    numpy: anything else means the arithmetic in this wheel is wrong on this device,
    which is the one failure a demo can catch that a benchmark cannot. Both halves
    matter — corrupt the vectors and recall drops, scale the returned distances and
    recall stays perfect while the disagreement blows past the tolerance.
    """
    xb, xq = make_vectors()
    sims, exact_ids = numpy_top_k(xb, xq)

    flat = faiss.IndexFlatIP(D)
    flat.add(xb)
    distances, flat_ids, flat_ms = timed_search(flat, xq)
    recall = recall_at_k(flat_ids, exact_ids)
    agreement = float(
        np.abs(distances - np.take_along_axis(sims, flat_ids, axis=1)).max()
    )

    ivf = faiss.IndexIVFFlat(faiss.IndexFlatIP(D), D, NLIST, faiss.METRIC_INNER_PRODUCT)
    ivf.train(xb)
    ivf.add(xb)
    ivf.nprobe = SETTINGS[DEFAULT][0]

    hnsw = faiss.IndexHNSWFlat(D, NEIGHBOURS, faiss.METRIC_INNER_PRODUCT)
    hnsw.add(xb)

    return {
        "queries": xq,
        "exact_ids": exact_ids,
        "indexes": (flat, ivf, hnsw),
        "sizes": (
            len(faiss.serialize_index(flat)),
            len(faiss.serialize_index(ivf)),
            len(faiss.serialize_index(hnsw)),
        ),
        "flat": (recall, flat_ms),
        "recall": recall,
        "agreement": agreement,
        "passed": recall == 1.0 and agreement < TOLERANCE,
        "storage": persist(ivf, xq),
    }


def rank(state, effort):
    """Re-search the two approximate indexes at one search-effort setting.

    Only the searches repeat. Neither index depends on nprobe or efSearch — that they
    are query-time knobs is the reason to tune them here rather than rebuild. Every row
    is graded against the numpy top-K rather than against the exact index's row, so a
    wrong exact index shows up as a wrong exact row instead of quietly redefining what
    the approximate ones are measured by.
    """
    nprobe, ef_search = SETTINGS[effort]
    _, ivf, hnsw = state["indexes"]
    ivf.nprobe = nprobe
    hnsw.hnsw.efSearch = ef_search

    flat_recall, flat_ms = state["flat"]
    rows = [("Flat (exact)", flat_recall, flat_ms, state["sizes"][0])]
    for label, index, size in (
        (f"IVF{NLIST} nprobe={nprobe}", ivf, state["sizes"][1]),
        (f"HNSW{NEIGHBOURS} ef={ef_search}", hnsw, state["sizes"][2]),
    ):
        _, ids, elapsed = timed_search(index, state["queries"])
        rows.append((label, recall_at_k(ids, state["exact_ids"]), elapsed, size))
    return rows


VERSIONS = (
    f"faiss {faiss.__version__} · numpy {np.__version__} · "
    f"Python {platform.python_version()}"
)

# The shortest way to see which slice you are running on: the SIMD level and the OpenMP
# thread count both differ between Android and iOS, and get_compile_options() names
# nothing at all when the compiled-in level is NONE.
BUILD_OPTIONS = (
    f"compile options: {faiss.get_compile_options().strip() or 'none (emulated SIMD)'}"
    f" · omp_get_max_threads() = {faiss.omp_get_max_threads()}"
    f" · get_num_gpus() = {faiss.get_num_gpus()}"
)

SUMMARY = (
    f"{N:,} vectors x {D} dims, {QUERIES} queries, k={K}. Every row is graded against "
    f"the numpy top-{K}, not against the row above it. Sizes: Flat = N*d*4, "
    f"IVF = N*(d*4+8) + nlist*d*4, HNSW = Flat + N*(8*M+16), each plus a small header."
)
