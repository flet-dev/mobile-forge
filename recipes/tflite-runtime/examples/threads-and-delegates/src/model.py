"""The tflite-runtime half of this example: load, resize, invoke, cross-check."""

import base64
import statistics
import time
import warnings

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
    RUNTIME_VERSION = getattr(tflite_runtime, "__version__", "—")
except Exception as error:
    # No wheel exists for any desktop OS, so this is the expected path under
    # `flet run`; the package is declared under [tool.flet.android]/[tool.flet.ios].
    Interpreter = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
    RUNTIME_VERSION = "—"

VERSION = f"tflite_runtime {RUNTIME_VERSION} · numpy {np.__version__}"

# tests/dense_relu.tflite from this recipe, verbatim: one FULLY_CONNECTED taking 4
# features to 3, with a bias, followed by relu. A FlatBuffer cannot be written out
# by hand the way a protobuf can, so the model rides along as base64.
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
THREADS = (1, 2, 4)
RUNS = 5
TOLERANCE = 1e-5
FEATURES, UNITS = 4, 3

MODEL_SUMMARY = (
    f"{len(MODEL):,} B of FlatBuffer embedded in the app · one FULLY_CONNECTED "
    f"{FEATURES} -> {UNITS} plus relu · decoded from base64, nothing written to disk"
)


def describe(rows):
    """One batch in a line: its shape, and the float32 bytes a round over it costs.

    Worth showing before the run rather than after, because it is what decides
    whether a slider stop is safe on a low-RAM handset: one input array plus one
    retained output per thread count.
    """
    held = rows * (FEATURES + len(THREADS) * UNITS) * 4
    return f"{rows:,} rows of {FEATURES} features · {held / 1e6:,.1f} MB of float32"


def measure(threads, x):
    """Run the model over `x` at `num_threads=threads` and report what happened.

    The interpreter is built and dropped inside this call because `num_threads` can
    only be chosen at construction — the C++ wrapper has a `SetNumThreads`, but
    `Interpreter` never exposes it, so three thread counts means three interpreters.
    The first `invoke()` is discarded: it is where the delegate warms its buffers,
    and counting it would report setup as inference.
    """
    started = time.perf_counter()
    interpreter = Interpreter(model_content=MODEL, num_threads=threads)
    index = interpreter.get_input_details()[0]["index"]
    interpreter.resize_tensor_input(index, list(x.shape))
    interpreter.allocate_tensors()  # mandatory after a resize, and holds the GIL
    load_ms = (time.perf_counter() - started) * 1000

    inputs = interpreter.get_input_details()[0]  # re-read: the resize moved the shape
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
    than from constants retyped here, so this cross-check cannot agree by having been
    written to agree.
    """
    return np.maximum(x @ weights.T + bias, 0.0)


def benchmark(rows):
    """Time one batch at every thread count and judge every answer against numpy.

    Returns plain values for the screen: a row per thread count, the worst
    disagreement with numpy across all of them, and the op list the interpreter
    settled on.
    """
    # dtype= generates float32 directly; an .astype() cast would materialise the
    # whole batch as float64 first, costing 32 MB extra at the top stop.
    x = np.random.default_rng(rows).standard_normal((rows, FEATURES), dtype=np.float32)
    results = [measure(threads, x) for threads in THREADS]
    worst = max(
        float(np.abs(r["y"] - reference(x, r["weights"], r["bias"])).max())
        for r in results
    )
    baseline = results[0]["median_ms"]
    return {
        "rows": [
            (r["threads"], r["load_ms"], r["median_ms"], baseline / r["median_ms"])
            for r in results
        ],
        "worst": worst,
        "passed": worst < TOLERANCE,
        "tolerance": TOLERANCE,
        "runs": RUNS,
        "ops": results[0]["ops"],
    }
