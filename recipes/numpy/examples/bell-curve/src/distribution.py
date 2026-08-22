"""The numpy side of the bell curve: draw, average, bin, and hand back plain numbers."""

import time

import numpy as np

SAMPLES = 100_000
BINS = 25

rng = np.random.default_rng()


def blas():
    """Name the BLAS this numpy was built against, or "unknown" if it will not say.

    `show_config` is how you ask a wheel what it is rather than trusting a page:
    the mobile wheels answer `none`, a desktop wheel usually names a tuned
    library. The lookup is guarded because the shape of that dict belongs to
    numpy, and an exception at import would leave the app blank instead of
    losing one word of a header line.
    """
    try:
        return np.show_config("dicts")["Build Dependencies"]["blas"]["name"]
    except Exception:
        return "unknown"


BUILD = (
    f"numpy {np.__version__} — BLAS {blas()} — "
    f"long double {np.dtype(np.longdouble).itemsize * 8}-bit"
)


def sample(draws):
    """Average `draws` uniform values 100,000 times, and bin the means.

    One 2-D draw collapsed along its second axis, rather than a Python loop over
    the samples: the whole batch stays inside compiled code, which is the reason
    numpy is worth shipping to a phone at all. The predicted spread is the
    central limit theorem's own answer for k uniform draws, 1/sqrt(12k).

    Everything returned is a plain Python value — the bin counts as a list of
    ints rather than an ndarray — so nothing that reaches a Flet control is a
    numpy scalar.
    """
    started = time.perf_counter()

    draw = rng.random((SAMPLES, draws))
    means = draw.mean(axis=1)
    counts, _ = np.histogram(means, bins=BINS, range=(0.0, 1.0))

    return {
        "counts": counts.tolist(),
        "mean": float(means.mean()),
        "std": float(means.std()),
        "predicted": float(1.0 / np.sqrt(12.0 * draws)),
        "megabytes": draw.nbytes / 1e6,
        "milliseconds": (time.perf_counter() - started) * 1000,
    }
