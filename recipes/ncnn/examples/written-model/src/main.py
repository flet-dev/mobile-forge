"""Write an ncnn model at runtime, run it on this device, and check it against numpy."""

import os
import resource
import statistics
import struct
import time
from importlib.metadata import version

import flet as ft
import ncnn
import numpy as np

SIDE = 128

CHANNELS = (8, 16, 24, 32, 48, 64)

CONVS = 3

REPEATS = 5

SEED = 0

TOLERANCE = 1e-4

COLUMN_WEIGHTS = (6, 4, 4, 3)

STORAGE = os.getenv("FLET_APP_STORAGE_DATA", ".")

# ru_maxrss counts bytes on Darwin kernels and kilobytes on Linux ones. uname() asks the
# kernel, so it settles this without depending on what platform.system() reports for the
# Python version in use.
RSS_UNIT = 1 if os.uname().sysname == "Darwin" else 1024

# a one-core emulator would otherwise give the thread slider a zero-wide range
CORES = max(2, ncnn.get_cpu_count())


def peak_mib():
    """Peak resident set size in MiB — a high-water mark, so it never falls back."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * RSS_UNIT / (1 << 20)


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


def table_row(values):
    """One row of the results table, laid out by weight so it fits a phone."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=weight)
            for value, weight in zip(values, COLUMN_WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """Write a model, run it three ways, and report what this device answered.

    Two sliders drive it: the channel count sets how much arithmetic one inference is, and
    the thread count is ncnn's one portable performance knob. Both recompute on release.
    """

    def show_channels():
        """Report the model the next run will write, as the channel slider moves."""
        channels = CHANNELS[round(width.value)]
        caption.value = (
            f"{CONVS} conv layers of {channels} channels over 1x{SIDE}x{SIDE}"
        )

    def show_threads():
        """Report the thread count the next run will use, as the thread slider moves."""
        picked = round(threads.value)
        cores.value = (
            f"opt.num_threads = {picked} of {ncnn.get_cpu_count()} cores "
            f"({ncnn.get_big_cpu_count()} big, {ncnn.get_little_cpu_count()} little) · "
            f"ncnn's own default here is {ncnn.get_physical_big_cpu_count()}"
        )

    def start():
        """Hand one round to a background thread and lock the sliders while it works.

        The guard goes on here rather than inside the worker: this body is synchronous
        where `run_thread` only schedules, and `extract` holds the GIL for its whole
        computation, so anything set inside the worker would not reach the screen until
        the work was already over.
        """
        if width.disabled:
            return
        width.disabled = threads.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Write the model, run it three ways, and rebuild every result line.

        The `try/except` is not optional — `page.run_thread` discards whatever a worker
        raises, so a failure in here would look like a screen that simply stopped
        updating — and the table is cleared on the way out so the previous run's numbers
        cannot sit under this run's error.
        """
        try:
            round_started = time.perf_counter()
            channels, picked = CHANNELS[round(width.value)], round(threads.value)
            param, binary, weights = write_model(channels)
            x = as_float32(
                np.random.default_rng(SEED + 1).standard_normal((1, SIDE, SIDE))
            )
            started = time.perf_counter()
            expected = reference(x, weights)
            reference_ms = (time.perf_counter() - started) * 1000
            scale = float(np.abs(expected).max())

            plural = f"{picked} thread" + ("s" if picked > 1 else "")
            runs = [
                (f"defaults, {plural}", picked, True),
                (f"fp16 off, {plural}", picked, False),
            ]
            if picked != 1:
                runs.append(("defaults, 1 thread", 1, True))
            results = [
                (label, fp16, measure(param, binary, x, count, fp16))
                for label, count, fp16 in runs
            ]

            differences = {
                label: float(np.abs(result["output"] - expected).max()) / scale
                for label, _, result in results
            }
            # only the fp16 rows differ by thread count alone, so only they get a ratio
            baseline = results[-1 if picked != 1 else 0][2]["median_ms"]
            files.value = (
                f"wrote {os.path.getsize(param):,} B of .param and "
                f"{os.path.getsize(binary):,} B of .bin to {STORAGE}"
            )
            graph.value = f"ncnn read it back as {results[0][2]['graph']}"
            table.controls = [
                table_row(("run", "max diff", "median", "vs 1 thread")),
                ft.Divider(height=1),
                *(
                    table_row(
                        (
                            label,
                            f"{differences[label]:.1e}",
                            f"{result['median_ms']:,.1f} ms",
                            f"{baseline / result['median_ms']:.2f}x" if fp16 else "—",
                        )
                    )
                    for label, fp16, result in results
                ),
            ]

            default, exact = results[0][0], results[1][0]
            passed = differences[exact] < TOLERANCE
            verdict.value = (
                f"{'PASS' if passed else 'FAIL'} · with fp16 off ncnn agrees with numpy to "
                f"{differences[exact]:.1e} against a {TOLERANCE:.0e} tolerance · "
                f"its defaults agree to {differences[default]:.1e}, because they do the "
                "arithmetic in fp16"
            )
            verdict.color = ft.Colors.GREEN if passed else ft.Colors.RED
            footer.value = (
                f"differences relative to the largest output · median of {REPEATS} "
                f"inferences · loading took {results[0][2]['load_ms']:,.0f} ms · whole "
                f"round {(time.perf_counter() - round_started) * 1000:,.0f} ms, of which "
                f"{reference_ms:,.0f} ms was the numpy cross-check · peak RSS for the "
                f"whole app {peak_mib():,.0f} MiB"
            )
        except Exception as error:
            table.controls = []
            files.value = graph.value = footer.value = ""
            verdict.color = ft.Colors.RED
            verdict.value = f"{type(error).__name__}: {error}"

        width.disabled = threads.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("ncnn written model"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"ncnn {version('ncnn')} (the extension reports {ncnn.__version__}) · "
                        f"numpy {np.__version__} · {page.platform.value}",
                        size=11,
                    ),
                    ft.Text(
                        f"opt.use_vulkan_compute = {ncnn.Option().use_vulkan_compute} and "
                        f"ncnn.get_gpu_count exists: {hasattr(ncnn, 'get_gpu_count')} — "
                        "these builds are CPU/NEON only",
                        size=11,
                    ),
                    files := ft.Text(size=11),
                    graph := ft.Text(size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True, size=12),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    width := ft.Slider(
                        min=0,
                        max=len(CHANNELS) - 1,
                        value=3,
                        divisions=len(CHANNELS) - 1,
                        on_change=show_channels,
                        on_change_end=start,
                    ),
                    cores := ft.Text(size=12),
                    threads := ft.Slider(
                        min=1,
                        max=CORES,
                        value=ncnn.get_physical_big_cpu_count(),
                        divisions=CORES - 1,
                        on_change=show_threads,
                        on_change_end=start,
                    ),
                    verdict := ft.Text(size=12),
                    ft.Divider(),
                    table := ft.Column(spacing=2),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_channels()
    show_threads()
    start()


if __name__ == "__main__":
    ft.run(main)
