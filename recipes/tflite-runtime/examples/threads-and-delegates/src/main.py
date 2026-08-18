"""Run a 1 KB TFLite model on this device at three thread counts and check it against numpy."""

import base64
import os
import platform
import statistics
import time
import warnings

import flet as ft
import numpy as np

# Every Interpreter() construction warns that tf.lite.Interpreter is deprecated in
# favour of ai_edge_litert, which is not published for mobile at all.
warnings.filterwarnings(
    "ignore", category=UserWarning, module=r"tflite_runtime\.interpreter"
)

try:
    import tflite_runtime
    from tflite_runtime.interpreter import Interpreter

    IMPORT_ERROR = None
except Exception as error:
    # No wheel exists for any desktop OS, so this is the expected path under
    # `flet run`; the package is declared under [tool.flet.android]/[tool.flet.ios].
    tflite_runtime = Interpreter = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

# tests/dense_relu.tflite from this recipe, verbatim: one FULLY_CONNECTED taking 4
# features to 3, with a bias, followed by relu. A FlatBuffer cannot be written out
# by hand the way a protobuf can, so the model rides along as 1,376 characters.
MODEL_BASE64 = (
    "HAAAAFRGTDMUACAAHAAYABQAEAAMAAAACAAEABQAAAAcAAAAjAAAAOQAAADwAQAAAAIAALQDAAADAAAAAQAAABAA"
    "AAAAAAoAEAAMAAgABAAKAAAADAAAABwAAAA8AAAADwAAAHNlcnZpbmdfZGVmYXVsdAABAAAABAAAAJz///8DAAAA"
    "BAAAAAgAAABvdXRwdXRfMAAAAAABAAAABAAAAM7+//8EAAAAAQAAAHgAAAACAAAANAAAAAQAAADc////BgAAAAQA"
    "AAATAAAAQ09OVkVSU0lPTl9NRVRBREFUQQAIAAwACAAEAAgAAAAFAAAABAAAABMAAABtaW5fcnVudGltZV92ZXJz"
    "aW9uAAcAAAAIAQAAAAEAAMAAAACcAAAAlAAAAHQAAAAEAAAAWv///wQAAABgAAAAEAAAAAAAAAAIAA4ACAAEAAgA"
    "AAAQAAAAJAAAAAAABgAIAAQABgAAAAQAAAAAAAAADAAYABQAEAAMAAQADAAAAPG9TI1u+CCQAwAAAAIAAAAEAAAA"
    "BgAAADIuMjEuMAAAxv///wQAAAAQAAAAMS41LjAAAAAAAAAAAAAAAPj9///m////BAAAAAwAAADsNSo/SkgTv9fn"
    "Ir8AAAYACAAEAAYAAAAEAAAAMAAAAI54gL52DUo+3UJiv/oQ1T4HxGY/Ux4wv3F7Oz/zdXW/0o/tPnwhML9jFU8+"
    "BphwP1j+//9c/v//DwAAAE1MSVIgQ29udmVydGVkLgABAAAAFAAAAAAADgAYABQAEAAMAAgABAAOAAAAFAAAABwA"
    "AABsAAAAcAAAAHQAAAAEAAAAbWFpbgAAAAABAAAAFAAAAAAADgAWAAAAEAAMAAsABAAOAAAAGAAAAAAAAAgYAAAA"
    "HAAAAAAABgAIAAcABgAAAAAAAAEBAAAAAwAAAAMAAAAAAAAAAQAAAAIAAAABAAAAAwAAAAEAAAAAAAAABAAAANAA"
    "AACAAAAASAAAAAQAAABW////AAAAARAAAAAQAAAABAAAACAAAABA////EQAAAFBhcnRpdGlvbmVkQ2FsbDowAAAA"
    "AgAAAAEAAAADAAAAlv///wAAAAEQAAAAEAAAAAMAAAAYAAAAgP///wgAAABSZWx1O2FkZAAAAAABAAAAAwAAAMr/"
    "//8AAAABEAAAABAAAAACAAAAFAAAALT///8GAAAATWF0TXVsAAACAAAAAwAAAAQAAAAAABYAGAAUAAAAEAAMAAgA"
    "AAAAAAAABwAWAAAAAAAAARQAAAAUAAAAAQAAACQAAAAEAAQABAAAABMAAABzZXJ2aW5nX2RlZmF1bHRfeDowAAIA"
    "AAABAAAABAAAAAEAAAAQAAAADAAMAAsAAAAAAAQADAAAAAkAAAAAAAAJ"
)

MODEL = base64.b64decode(MODEL_BASE64)

BATCHES = (4_096, 32_768, 262_144, 1_048_576)

FEATURES, UNITS = 4, 3

THREADS = (1, 2, 4)

RUNS = 5

TOLERANCE = 1e-5

COLUMN_WEIGHTS = (3, 4, 4, 3)


def measure(threads, x):
    """Run the model over `x` with `num_threads=threads` and report what happened.

    Everything the screen needs comes out of one interpreter: how long the load
    took, the median per-invoke time, the answer, the model's own weights, and the
    op list the interpreter settled on. It is built and dropped inside this call
    because `num_threads` can only be chosen at construction — the C++ wrapper has
    a `SetNumThreads`, but `Interpreter` never exposes it, so three thread counts
    means three interpreters.

    The first `invoke()` is discarded: it is where the delegate warms its buffers,
    and counting it would report setup as inference.
    """
    started = time.perf_counter()
    interpreter = Interpreter(model_content=MODEL, num_threads=threads)
    index = interpreter.get_input_details()[0]["index"]
    interpreter.resize_tensor_input(index, list(x.shape))
    interpreter.allocate_tensors()  # mandatory after a resize, and holds the GIL
    load_ms = (time.perf_counter() - started) * 1000

    inputs = interpreter.get_input_details()[0]
    outputs = interpreter.get_output_details()[0]
    interpreter.set_tensor(inputs["index"], np.asarray(x, dtype=inputs["dtype"]))

    interpreter.invoke()
    times = []
    for _ in range(RUNS):
        started = time.perf_counter()
        interpreter.invoke()
        times.append((time.perf_counter() - started) * 1000)

    return {
        "threads": threads,
        "load_ms": load_ms,
        "median_ms": statistics.median(times),
        "y": interpreter.get_tensor(outputs["index"]),
        "weights": interpreter.get_tensor(1),
        "bias": interpreter.get_tensor(2),
        # Experimental and private: the applied delegates are not on the public API.
        # A delegated graph shows an extra op named DELEGATE.
        "ops": [op["op_name"] for op in interpreter._get_ops_details()],
    }


def reference(x, weights, bias):
    """The same arithmetic in numpy, as the thing the interpreter's answer is judged against.

    The weights come from `get_tensor()` on the model's own constant tensors rather
    than from constants retyped here, so this cross-check cannot agree by having
    been written to agree.
    """
    return np.maximum(x @ weights.T + bias, 0.0)


def table_row(values, size=11):
    """One row of the thread table, laid out by weight so it fits a phone."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, COLUMN_WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """Run the embedded model at the chosen batch size and report what came back.

    Three things go on screen that only this handset can answer: whether the
    interpreter agrees with numpy, whether XNNPACK actually attached here, and what
    `num_threads` is worth on this SoC. The slider picks the batch size, and
    releasing it recomputes everything.
    """

    def show_batch():
        """Report the batch size and the float32 arrays it costs, as the slider moves.

        The bytes are worth showing before the run rather than after: they are what
        decides whether a stop is safe on a low-RAM handset, and they are exactly
        derivable from the slider position — one input array plus one retained
        output per thread count.
        """
        rows = BATCHES[int(size.value)]
        held = rows * (FEATURES + len(THREADS) * UNITS) * 4
        caption.value = (
            f"{rows:,} rows of {FEATURES} features · "
            f"{held / 1e6:,.1f} MB of float32 arrays"
        )

    def start():
        """Hand one measurement round to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end, which fires once on release, so one
        gesture means one run. The guard is set here rather than in the worker
        because this body is synchronous where `run_thread` only schedules.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Build the inputs, run three interpreters, and rebuild every result line.

        Worth a thread: `invoke()` releases the GIL for its whole duration, so the
        UI keeps its frames while this works. The `try/except` is not optional —
        `page.run_thread` discards whatever a worker raises, so a failure in here
        would look like a screen that simply stopped updating — and the panels are
        cleared on the way out so the previous run's numbers cannot sit under this
        run's error.
        """
        try:
            batch = BATCHES[int(size.value)]
            # dtype= generates float32 directly; an .astype() cast would materialise
            # the whole batch as float64 first, costing 32 MB extra at the top stop.
            x = np.random.default_rng(batch).standard_normal(
                (batch, FEATURES), dtype=np.float32
            )
            results = [measure(threads, x) for threads in THREADS]

            worst = max(
                float(
                    np.abs(
                        result["y"] - reference(x, result["weights"], result["bias"])
                    ).max()
                )
                for result in results
            )
            passed = worst < TOLERANCE
            verdict.value = (
                f"{'PASS' if passed else 'FAIL'} · max|tflite - numpy| = {worst:.2e} "
                f"against a {TOLERANCE:.0e} tolerance, over {batch:,} rows"
            )
            verdict.color = ft.Colors.GREEN if passed else ft.Colors.RED

            baseline = results[0]["median_ms"]
            scaling.controls = [
                table_row(("num_threads", "load", "invoke", "vs 1")),
                ft.Divider(height=1),
                *(
                    table_row(
                        (
                            f"{result['threads']} thread"
                            + ("s" if result["threads"] > 1 else ""),
                            f"{result['load_ms']:,.1f} ms",
                            f"{result['median_ms']:,.2f} ms",
                            f"{baseline / result['median_ms']:.2f}x",
                        )
                    )
                    for result in results
                ),
            ]
            footer.value = (
                f"median of {RUNS} invokes · ops {results[0]['ops']} — a DELEGATE "
                f"entry is XNNPACK · os.cpu_count() = {os.cpu_count()}"
            )
        except Exception as error:
            scaling.controls = []
            footer.value = ""
            verdict.color = ft.Colors.RED
            verdict.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(
        title=ft.Text("tflite-runtime threads and delegates"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"tflite_runtime {getattr(tflite_runtime, '__version__', '—')} · "
                        f"numpy {np.__version__} · Python {platform.python_version()} · "
                        f"{page.platform.value}",
                        size=11,
                    ),
                    ft.Text(
                        f"model embedded in this app: {len(MODEL):,} B of FlatBuffer, "
                        f"one FULLY_CONNECTED {FEATURES} -> {UNITS} plus relu · decoded "
                        "from base64, no asset file and nothing written to disk",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=0,
                        max=len(BATCHES) - 1,
                        value=2,
                        divisions=len(BATCHES) - 1,
                        on_change=show_batch,
                        on_change_end=start,
                    ),
                    verdict := ft.Text(size=12),
                    ft.Divider(),
                    scaling := ft.Column(spacing=2),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_batch()  # derived from the slider alone, so it fills in even without the package

    if IMPORT_ERROR:
        verdict.value = f"tflite_runtime is not installed here — {IMPORT_ERROR}"
        verdict.color = ft.Colors.RED
        size.disabled = True
        page.update()
        return

    start()


if __name__ == "__main__":
    ft.run(main)
