"""Square GEMM measurements on top of cython-blis, against numpy's own matmul.

`blis.py.gemm` is a thin Cython wrapper over a single BLIS call, so what these
functions time is the microkernel rather than Python. Every array is 2-D,
C-contiguous and exactly float32 or float64: the wrapper's signatures are fused
over those two types only, and anything else raises rather than being converted.
"""

import threading
import time

import blis.about
import blis.py
import numpy as np

SIZES = (128, 256, 384)
THREADS = (1, 2, 4)
DTYPES = ("float32", "float64")
REPS = 3
JOBS = 8


def numpy_blas():
    """Name the BLAS numpy was built against.

    This is the number to read the comparison against: the mobile numpy wheel
    reports "none" and falls back to its own matmul loop, while a desktop wheel
    usually names a tuned library, which is why the same app tells a different
    story under `flet run`.
    """
    try:
        return np.show_config("dicts")["Build Dependencies"]["blas"]["name"]
    except Exception:
        return "unknown"


BUILD = f"blis {blis.about.__version__} · numpy {np.__version__} · BLAS {numpy_blas()}"


def operands(size, dtype):
    """Two square matrices and a zeroed output buffer, all C-contiguous."""
    source = np.random.default_rng(0)
    a = source.random((size, size), dtype=dtype)
    b = source.random((size, size), dtype=dtype)
    return a, b, np.zeros((size, size), dtype=dtype)


def fastest(call, reps=REPS):
    """Milliseconds for the quickest of `reps` runs, which is the least disturbed."""
    best = float("inf")
    for _ in range(reps):
        started = time.perf_counter()
        call()
        best = min(best, time.perf_counter() - started)
    return best * 1000


def rate(size, milliseconds):
    """GFLOP/s, from the 2*n^3 floating-point operations a square GEMM performs."""
    return 2 * size**3 / (milliseconds / 1000) / 1e9


def compare(size, dtype):
    """Time BLIS and numpy on the same multiply, and check they agree.

    Both write into a buffer allocated up front, so neither is charged for the
    result array. The repeats accumulate into `out` because `gemm`'s `beta`
    defaults to 1 rather than 0 -- that is the same arithmetic every time, so it
    does not move the rate, but it is why the buffer is zeroed again before the
    result is compared.
    """
    a, b, out = operands(size, dtype)
    blis_ms = fastest(lambda: blis.py.gemm(a, b, out=out))
    reference = np.empty_like(out)
    numpy_ms = fastest(lambda: np.matmul(a, b, out=reference))

    out.fill(0)
    blis.py.gemm(a, b, out=out)
    difference = np.max(np.abs(out - reference)) / np.max(np.abs(reference))
    return blis_ms, numpy_ms, float(difference)


def accumulated(size=64):
    """Multiply twice into one buffer and report how much the result grew.

    A GEMM computes `out = alpha*A*B + beta*out`, and this wrapper's `beta`
    defaults to 1, so a reused buffer adds rather than replaces. It is the
    quietest way to get wrong numbers out of the API.
    """
    a, b, out = operands(size, "float32")
    blis.py.gemm(a, b, out=out)
    once = float(out[0, 0])
    blis.py.gemm(a, b, out=out)
    return float(out[0, 0]) / once


def spread(size, threads, jobs=JOBS):
    """Wall-clock milliseconds for `jobs` multiplies shared by `threads` threads.

    BLIS is compiled here with threading disabled, so one call never uses more
    than one core and no environment variable changes that. The parallelism has
    to come from the caller, and it works because the wrapper holds `nogil`
    across the whole BLIS call: the threads do arithmetic at the same time
    instead of taking turns on the GIL. Each thread owns its output buffer,
    since two threads writing one buffer is a data race BLIS will not notice.
    """
    a, b, _ = operands(size, "float32")
    share = jobs // threads

    def worker():
        """Do this thread's share of the multiplies into a buffer only it holds."""
        out = np.zeros((size, size), dtype="float32")
        for _ in range(share):
            blis.py.gemm(a, b, out=out)

    started = time.perf_counter()
    pool = [threading.Thread(target=worker) for _ in range(threads)]
    for thread in pool:
        thread.start()
    for thread in pool:
        thread.join()
    return (time.perf_counter() - started) * 1000


def measure(size, threads):
    """Everything one press of Run produces, as plain numbers."""
    rates = {}
    for dtype in DTYPES:
        blis_ms, numpy_ms, difference = compare(size, dtype)
        rates[dtype] = (
            blis_ms,
            rate(size, blis_ms),
            numpy_ms,
            rate(size, numpy_ms),
            difference,
        )
    serial = spread(size, 1)
    parallel = serial if threads == 1 else spread(size, threads)
    return {
        "rates": rates,
        "difference": rates["float32"][4],
        "accumulated": accumulated(),
        "serial_ms": serial,
        "parallel_ms": parallel,
        "speedup": serial / parallel,
    }
