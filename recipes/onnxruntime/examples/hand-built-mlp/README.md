# onnxruntime hand-built MLP

One screen that writes an ONNX model **inside the app**, runs it through onnxruntime on the
device, and checks the answer against the same arithmetic in numpy. No model file, no asset,
no download, nothing written to disk — and no `onnx` package, which is not published for
mobile. About sixty lines of protobuf wire-format helpers emit a valid `ModelProto` in memory
and `ort.InferenceSession(model_bytes, …)` takes it from there.

The graph is a 256 → 512 → 512 → 512 MLP as `Gemm`/`Relu`/`Gemm`/`Relu`/`Gemm`/`Softmax`,
weights filled from a fixed-seed `numpy.random.default_rng`, batch dimension left symbolic
(`N`), opset 17, `ir_version` 10. A slider picks the batch size — 1, 64, 256, 1024 or 4096 —
and releasing it recomputes everything.

The top slider position is the expensive one, and the only one worth watching on a low-RAM
handset: activations scale with the batch, so peak RSS driven through the app's own handlers
on desktop goes from 100.8 MB at the default position to 186.0 MB at 4096, where positions 0
through 3 all sit within a megabyte of each other. A backgrounded Android app that asks for
too much is killed rather than slowed.

What it demonstrates:

- **A model handed over as bytes.** The encoders build `TensorProto`, `ValueInfoProto`,
  `NodeProto`, `AttributeProto` and `GraphProto` by hand, so the app carries no dependency
  beyond onnxruntime and numpy. `Gemm` needs no attributes — its defaults are already
  `Y = X @ W + b` — while `Softmax` gets an explicit `axis=-1`, which is the one place the
  encoder has to get a negative varint right. The symbolic batch dimension is what lets one
  session answer every slider position instead of five.
- **A cross-check that can fail visibly.** A model that loads and runs still tells you
  nothing about whether it computed what you meant, so the verdict line reports
  `max|ort - numpy|` against a 1e-5 tolerance with the actual figure beside it — and, as a
  second and independent check, whether the top-scoring class agrees on every row. A build
  where the graph quietly did the wrong thing then shows FAIL rather than a plausible-looking
  number. On desktop the difference lands around 4e-10 to 4e-09 depending on batch size.
- **Which execution providers this device actually has.** The header prints
  `get_available_providers()` and the footer prints the live session's `get_providers()`.
  On a phone both read `['CPUExecutionProvider']` — the mobile wheels carry no XNNPACK, NNAPI
  or CoreML, so nothing here reaches an NPU. See
  [Things to know](../../README.md#things-to-know).
- **What `intra_op_num_threads` is worth on this SoC.** Three sessions are built per run, at
  1, 2 and 4 threads, and each is timed over the same batch — the median of seven runs after
  a discarded warm-up. That table is the only way to see the answer, because
  `get_session_options().intra_op_num_threads` reads back `0` on a default session even while
  the extra threads are live. On the very first run the 1-thread row's session column also
  carries onnxruntime's one-time initialisation, so it reads high once and settles on the
  next slider move.
- **What `platform.system()` reports here.** The first header line prints it. onnxruntime
  warns `Unsupported platform (…)` at import for anything outside Linux/macOS/AIX/Windows,
  which iOS always trips; whether Android does depends on Flet's Python build, and this is
  the quickest way to find out on a device you have.
- **Compute off the UI thread, where it genuinely helps.** The work runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  slider disabled and a spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. `sess.run` releases the GIL for the whole computation — see
  [Threading](../../README.md#threading) — so the UI keeps its frames while this works. The
  worker body is wrapped in `try/except` because `page.run_thread` discards whatever it
  raises, and it clears the panels on the way out so the previous run's numbers cannot sit
  under this run's error.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

`pyproject.toml` pins `flet` and `onnxruntime`, which is the combination that was verified.
Two entries in it are not decoration. `requires-python = ">=3.11"` is required by the pin —
the onnxruntime wheel declares that floor, and at `>=3.10` uv answers *your project's
requirements are unsatisfiable*, checked the way a consumer meets it by copying that
`pyproject.toml` alone into an empty directory and running `uv lock` there. And
`[tool.flet.android] target_arch = ["arm64-v8a", "x86_64"]` is required because no
`armeabi-v7a` wheel exists; without it the APK build fails resolving that ABI.
