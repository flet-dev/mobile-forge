"""Write an ncnn model at runtime, run it three ways, and check it against numpy."""

import os
import resource
import statistics
import struct
import time
from importlib.metadata import version

import ncnn
import numpy as np

SIDE = 128
CHANNELS = (8, 16, 24, 32, 48, 64)
CONVS = 3
REPEATS = 5
SEED = 0
TOLERANCE = 1e-4

STORAGE = os.getenv("FLET_APP_STORAGE_DATA", ".")

# ru_maxrss counts bytes on Darwin kernels and kilobytes on Linux ones. uname() asks the
# kernel, so it settles this without depending on what platform.system() reports for the
# Python version in use.
RSS_UNIT = 1 if os.uname().sysname == "Darwin" else 1024

# a one-core emulator would otherwise give the thread slider a zero-wide range
CORES = max(2, ncnn.get_cpu_count())
DEFAULT_THREADS = max(1, min(ncnn.get_physical_big_cpu_count(), CORES))

# the two version strings disagree on mobile: the extension reports the day it was
# compiled, the distribution reports the release that was installed
VERSIONS = (
    f"ncnn {version('ncnn')} (extension says {ncnn.__version__}) · "
    f"numpy {np.__version__}"
)

GPU = (
    f"opt.use_vulkan_compute = {ncnn.Option().use_vulkan_compute} · ncnn.get_gpu_count "
    f"exists: {hasattr(ncnn, 'get_gpu_count')} — these builds are CPU and NEON only"
)


def peak_rss_mb():
    """Peak resident set size in decimal MB — a high-water mark, it never falls back."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * RSS_UNIT / 1e6


def describe(channels):
    """Describe the graph a channel count will produce."""
    return f"{CONVS} conv layers of {channels} channels over 1x{SIDE}x{SIDE}"


def cpu_summary(threads):
    """Describe a thread setting against what ncnn makes of this SoC."""
    return (
        f"opt.num_threads = {threads} of {ncnn.get_cpu_count()} cores "
        f"({ncnn.get_big_cpu_count()} big, {ncnn.get_little_cpu_count()} little) · "
        f"ncnn's own default here is {ncnn.get_physical_big_cpu_count()}"
    )


def as_float32(array):
    """Return `array` as the C-contiguous float32 buffer ncnn works in.

    Every number that reaches ncnn goes through here. `ncnn.Mat` accepts any dtype
    without complaint and then reads the bytes as float32, so a float64 array — which is
    what `np.zeros(n)` and most numpy arithmetic hand you — takes the whole process down
    with SIGBUS instead of raising something an app could catch.
    """
    return np.ascontiguousarray(array, dtype=np.float32)


def write_model(channels):
    """Write a `.param`/`.bin` pair for a `CONVS`-layer 3x3 conv net into app storage.

    The `.param` is plain text — a magic number, the layer and blob counts, then one line
    per layer. The `.bin` is each layer's weights and bias as raw little-endian float32,
    with a single 4-byte flag word (0 = float32) in front of every weight blob and none in
    front of a bias. That is the whole format, which is why an app can ship a model without
    shipping a model file: these two files are written here, at runtime, from numbers the
    app generated itself.
    """
    rng = np.random.default_rng(SEED)
    lines = ["Input           in     0 1 x"]
    blobs, weights, bottom = [], [], "x"
    for index in range(CONVS):
        fan_in = 1 if index == 0 else channels
        w = as_float32(
            rng.standard_normal((channels, fan_in, 3, 3)) / np.sqrt(9 * fan_in)
        )
        b = as_float32(rng.standard_normal(channels) * 0.01)
        weights.append((w, b))
        top = "y" if index == CONVS - 1 else f"h{index}"
        lines.append(
            f"Convolution     conv{index}  1 1 {bottom} {top} 0={channels} 1=3 3=1 4=1 "
            f"5=1 6={w.size} 9={0 if index == CONVS - 1 else 1}"
        )
        blobs.append(struct.pack("<I", 0) + w.tobytes() + b.tobytes())
        bottom = top
    param = os.path.join(STORAGE, "net.param")
    binary = os.path.join(STORAGE, "net.bin")
    with open(param, "w") as handle:
        handle.write(f"7767517\n{len(lines)} {len(lines)}\n" + "\n".join(lines) + "\n")
    with open(binary, "wb") as handle:
        handle.write(b"".join(blobs))
    return param, binary, weights


def convolve(x, w, b):
    """One 3x3 stride-1 pad-1 convolution over `x` in numpy, as ncnn defines it."""
    channels, height, width = w.shape[0], x.shape[1], x.shape[2]
    padded = np.zeros((x.shape[0], height + 2, width + 2), np.float32)
    padded[:, 1:-1, 1:-1] = x
    out = np.zeros((channels, height, width), np.float32) + b[:, None, None]
    for row in range(3):
        for column in range(3):
            window = padded[:, row : row + height, column : column + width]
            out += np.tensordot(w[:, :, row, column], window, axes=([1], [0]))
    return out


def reference(x, weights):
    """Run the written graph in numpy — the answer ncnn's output is judged against.

    A model that loads and runs still says nothing about whether it computed what you
    meant, so the app needs a result it did not get from ncnn.
    """
    for w, b in weights[:-1]:
        x = np.maximum(convolve(x, w, b), 0.0)
    w, b = weights[-1]
    return convolve(x, w, b)


def measure(param, binary, x, threads, fp16):
    """Load the model just written and time `REPEATS` inferences at these settings.

    The fp16 flags go on before `load_param` because they are a load-time decision: the
    weights are converted as they are read. Flipping them after `load_model` is not a
    slower path, it is a broken one — turning them off there poisons the output with NaN
    and still reports success, and turning them on there kills the process.
    """
    net = ncnn.Net()
    net.opt.num_threads = threads
    net.opt.use_fp16_packed = fp16
    net.opt.use_fp16_storage = fp16
    net.opt.use_fp16_arithmetic = fp16
    started = time.perf_counter()
    if net.load_param(param) != 0 or net.load_model(binary) != 0:
        raise RuntimeError("ncnn refused the model this app just wrote")
    load_ms = (time.perf_counter() - started) * 1000

    times, output = [], None
    for _ in range(REPEATS + 1):
        started = time.perf_counter()
        extractor = net.create_extractor()
        # ncnn.Mat keeps no reference to x; inlining the conversion into this call
        # would free the buffer before extract reads it, and still return 0
        extractor.input("x", ncnn.Mat(x))
        code, mat = extractor.extract("y")
        if code != 0:
            # a failed extract hands back an empty Mat, and np.array of one segfaults
            raise RuntimeError(f"ncnn extract returned {code}")
        # np.array copies; mat.numpy() would hand back a view of the Net's own pool
        output = np.array(mat)
        times.append((time.perf_counter() - started) * 1000)

    return {
        "output": output,
        "load_ms": load_ms,
        "median_ms": statistics.median(times[1:]),
        "graph": (
            f"{len(net.layers())} layers · {len(net.blobs())} blobs · "
            f"in {net.input_names()} · out {net.output_names()}"
        ),
    }


def run(channels, threads):
    """Write a model, run it three ways, and return everything the screen needs.

    The three configurations are ncnn's defaults, the same graph with fp16 off, and —
    unless the slider is already there — the defaults at one thread. The first two differ
    only in precision, so they are what the agreement column compares; the third is what
    makes the speedup column a number measured on the handset in your hand.
    """
    round_started = time.perf_counter()
    param, binary, weights = write_model(channels)
    x = as_float32(np.random.default_rng(SEED + 1).standard_normal((1, SIDE, SIDE)))

    started = time.perf_counter()
    expected = reference(x, weights)
    reference_ms = (time.perf_counter() - started) * 1000
    scale = float(np.abs(expected).max())

    plural = f"{threads} thread" + ("s" if threads > 1 else "")
    wanted = [
        (f"defaults, {plural}", threads, True),
        (f"fp16 off, {plural}", threads, False),
    ]
    if threads != 1:
        wanted.append(("defaults, 1 thread", 1, True))

    results = [
        (label, fp16, measure(param, binary, x, count, fp16))
        for label, count, fp16 in wanted
    ]
    diffs = [float(np.abs(r["output"] - expected).max()) / scale for _, _, r in results]
    # only the fp16 rows differ by thread count alone, so only they get a ratio
    baseline = results[-1 if threads != 1 else 0][2]["median_ms"]

    return {
        "storage": STORAGE,
        "param_bytes": os.path.getsize(param),
        "bin_bytes": os.path.getsize(binary),
        "graph": results[0][2]["graph"],
        "rows": [
            (label, diff, r["median_ms"], baseline / r["median_ms"] if fp16 else None)
            for (label, fp16, r), diff in zip(results, diffs)
        ],
        "default_diff": diffs[0],
        "exact_diff": diffs[1],
        "passed": diffs[1] < TOLERANCE,
        "load_ms": results[0][2]["load_ms"],
        "reference_ms": reference_ms,
        "round_ms": (time.perf_counter() - round_started) * 1000,
        "peak_mb": peak_rss_mb(),
    }
