"""Build an ONNX model in memory on this device, run it through onnxruntime, and check it against numpy."""

import os
import platform
import statistics
import time

import flet as ft
import numpy as np
import onnxruntime as ort

LAYERS = ((256, 512), (512, 512), (512, 512))

BATCHES = (1, 64, 256, 1024, 4096)

THREADS = (1, 2, 4)

RUNS = 7

TOLERANCE = 1e-5

OPSET = 17

IR_VERSION = 10

SCALING_WEIGHTS = (3, 4, 4, 3)


def varint(value):
    """Encode `value` as a protobuf base-128 varint.

    Negative numbers are two's-complement over 64 bits — the ten-byte form a signed
    attribute such as `axis=-1` needs.
    """
    value &= (1 << 64) - 1
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def field(index, wire, payload):
    """One protobuf field: the tag, then the payload, length-prefixed on wire type 2."""
    tag = varint((index << 3) | wire)
    return tag + (varint(len(payload)) + payload if wire == 2 else payload)


def text(index, value):
    """A `string` field."""
    return field(index, 2, value.encode())


def integer(index, value):
    """An `int32`/`int64` field."""
    return field(index, 0, varint(value))


def tensor(name, array):
    """A `TensorProto` holding `array` as float32 raw data — dims, elem type 1, name, bytes."""
    return (
        b"".join(integer(1, size) for size in array.shape)
        + integer(2, 1)
        + text(8, name)
        + field(9, 2, array.tobytes())
    )


def value_info(name, dims):
    """A `ValueInfoProto` for a float32 tensor; a string in `dims` becomes a symbolic dimension."""
    shape = b"".join(
        field(1, 2, text(2, dim) if isinstance(dim, str) else integer(1, dim))
        for dim in dims
    )
    return text(1, name) + field(2, 2, field(1, 2, integer(1, 1) + field(2, 2, shape)))


def attribute(name, value):
    """An `AttributeProto` carrying a single int (type 2 in the AttributeType enum)."""
    return text(1, name) + integer(3, value) + integer(20, 2)


def node(op_type, inputs, outputs, attributes=b""):
    """A `NodeProto`: input names, output names, the operator, and any attributes."""
    return (
        b"".join(text(1, name) for name in inputs)
        + b"".join(text(2, name) for name in outputs)
        + text(4, op_type)
        + (field(5, 2, attributes) if attributes else b"")
    )


def build_model(rng):
    """Serialise a `ModelProto` for an MLP straight to bytes, and return it with its weights.

    This is the whole point of the example: the `onnx` package is not published for mobile,
    so the graph is written by hand in protobuf wire format — roughly sixty lines above —
    and handed to onnxruntime as bytes. `Gemm` needs no attributes because its defaults are
    already `Y = X @ W + b`; `Softmax` gets an explicit `axis=-1` so the encoder has to get
    a negative varint right. The batch dimension is the symbolic name `N`, which is what
    lets one session serve every slider position.
    """
    nodes, initializers, weights = [], [], []
    name = "x"
    for index, (fan_in, fan_out) in enumerate(LAYERS):
        w = (rng.standard_normal((fan_in, fan_out)) / np.sqrt(fan_in)).astype(
            np.float32
        )
        b = (rng.standard_normal(fan_out) * 0.01).astype(np.float32)
        weights.append((w, b))
        initializers += [
            field(5, 2, tensor(f"W{index}", w)),
            field(5, 2, tensor(f"b{index}", b)),
        ]
        nodes.append(
            field(1, 2, node("Gemm", [name, f"W{index}", f"b{index}"], [f"z{index}"]))
        )
        name = f"z{index}"
        if index < len(LAYERS) - 1:
            nodes.append(field(1, 2, node("Relu", [name], [f"h{index}"])))
            name = f"h{index}"
    nodes.append(field(1, 2, node("Softmax", [name], ["y"], attribute("axis", -1))))

    graph = (
        b"".join(nodes)
        + text(2, "mlp")
        + b"".join(initializers)
        + field(11, 2, value_info("x", ("N", LAYERS[0][0])))
        + field(12, 2, value_info("y", ("N", LAYERS[-1][1])))
    )
    model = (
        integer(1, IR_VERSION)
        + text(2, "flet-hand-built-mlp")
        + field(7, 2, graph)
        + field(8, 2, text(1, "") + integer(2, OPSET))
    )
    return model, weights


def reference(x, weights):
    """The same arithmetic in numpy, as the thing the graph's output is judged against.

    A model that loads and runs still tells you nothing about whether it computes what you
    meant, so the app needs an answer it did not get from onnxruntime.
    """
    for w, b in weights[:-1]:
        x = np.maximum(x @ w + b, 0.0)
    w, b = weights[-1]
    z = x @ w + b
    z = z - z.max(axis=-1, keepdims=True)
    exponentials = np.exp(z)
    return exponentials / exponentials.sum(axis=-1, keepdims=True)


MODEL, WEIGHTS = build_model(np.random.default_rng(0))


def session(intra_op):
    """An `InferenceSession` over the in-memory model with `intra_op_num_threads` set.

    Left at its default of 0, onnxruntime picks roughly half the logical cores — on a phone
    that reaches the little cores too, and a backgrounded app is throttled or killed rather
    than slowed. A session only echoes back the value it was given, never the count it
    resolved, so the only way to see what a setting costs is to time it, which is what the
    table on screen does.
    """
    options = ort.SessionOptions()
    options.intra_op_num_threads = intra_op
    return ort.InferenceSession(MODEL, options, providers=["CPUExecutionProvider"])


def measure(intra_op, x, expected):
    """Time one session at `intra_op` threads and check its output against `expected`.

    The first `run` is thrown away: it is where onnxruntime allocates its arena and settles
    on kernels, so including it would report the setup cost as the inference cost.
    """
    started = time.perf_counter()
    sess = session(intra_op)
    build_ms = (time.perf_counter() - started) * 1000

    (y,) = sess.run(None, {"x": x})
    times = []
    for _ in range(RUNS):
        started = time.perf_counter()
        sess.run(None, {"x": x})
        times.append((time.perf_counter() - started) * 1000)

    return {
        "intra_op": intra_op,
        "providers": sess.get_providers(),
        "build_ms": build_ms,
        "median_ms": statistics.median(times),
        "difference": float(np.abs(y - expected).max()),
        "argmax": int((y.argmax(axis=-1) == expected.argmax(axis=-1)).sum()),
    }


def table_row(values, size=11):
    """One row of the thread-scaling table, laid out by weight so it fits a phone."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, SCALING_WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """Run the hand-built graph at the chosen batch size and report what came back.

    Three things go on screen that a phone can only answer for itself: which execution
    providers this build actually has, whether the graph agrees with numpy to a tolerance,
    and what `intra_op_num_threads` is worth on this SoC. The slider picks the batch size
    and releasing it recomputes everything.
    """

    def show_batch():
        """Report the batch size the next run will use, as the slider moves."""
        rows = BATCHES[int(size.value)]
        caption.value = (
            f"{rows:,} row{'s' if rows > 1 else ''} of {LAYERS[0][0]} features"
        )

    def start():
        """Hand one measurement round to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end, which fires once on release, so one gesture
        means one run. The guard is set here rather than in the worker because this body is
        synchronous where `run_thread` only schedules — a `disabled` set inside the worker
        would not have taken effect before Flet pushed the control states.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Build the inputs, run three sessions, and rebuild every result line.

        Worth a thread: `sess.run` releases the GIL for the whole computation, so the UI
        keeps its frames while this works. The `try/except` is not optional — `page.run_thread`
        discards whatever a worker raises, so a failure in here would look like a screen
        that simply stopped updating — and the panels are cleared on the way out so the
        previous run's numbers cannot sit under this run's error.
        """
        try:
            batch = BATCHES[int(size.value)]
            x = (
                np.random.default_rng(batch)
                .standard_normal((batch, LAYERS[0][0]))
                .astype(np.float32)
            )
            expected = reference(x, WEIGHTS)
            results = [measure(intra_op, x, expected) for intra_op in THREADS]

            worst = max(result["difference"] for result in results)
            agreed = min(result["argmax"] for result in results)
            passed = worst < TOLERANCE and agreed == batch
            verdict.value = (
                f"{'PASS' if passed else 'FAIL'} · max|ort - numpy| = {worst:.2e} "
                f"against a {TOLERANCE:.0e} tolerance · top class agrees on "
                f"{agreed:,}/{batch:,} rows"
            )
            verdict.color = ft.Colors.GREEN if passed else ft.Colors.RED

            baseline = results[0]["median_ms"]
            scaling.controls = [
                table_row(("intra_op", "session", "inference", "vs 1")),
                ft.Divider(height=1),
                *(
                    table_row(
                        (
                            f"{result['intra_op']} thread"
                            + ("s" if result["intra_op"] > 1 else ""),
                            f"{result['build_ms']:,.1f} ms",
                            f"{result['median_ms']:,.1f} ms",
                            f"{baseline / result['median_ms']:.2f}x",
                        )
                    )
                    for result in results
                ),
            ]
            footer.value = (
                f"median of {RUNS} runs at batch {batch:,} · session providers "
                f"{results[0]['providers']} · os.cpu_count() = {os.cpu_count()}"
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
        title=ft.Text("onnxruntime hand-built MLP"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"onnxruntime {ort.__version__} · numpy {np.__version__} · "
                        f"Python {platform.python_version()} · {page.platform.value} · "
                        f"platform.system() = {platform.system()}",
                        size=11,
                    ),
                    ft.Text(
                        f"available providers: {ort.get_available_providers()} — on a phone "
                        "that is CPU alone: the mobile wheels carry no XNNPACK, NNAPI or CoreML",
                        size=11,
                    ),
                    ft.Text(
                        f"model written in this app: {len(MODEL):,} B of protobuf · opset "
                        f"{OPSET} · ir_version {IR_VERSION} · "
                        + " -> ".join(
                            str(n) for n in (LAYERS[0][0], *(out for _, out in LAYERS))
                        )
                        + " · no onnx package, no asset file, nothing written to disk",
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
                        value=3,
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

    show_batch()
    start()


if __name__ == "__main__":
    ft.run(main)
