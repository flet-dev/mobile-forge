# tflite-runtime

[`tflite-runtime`](https://ai.google.dev/edge/litert/inference) is TensorFlow Lite's
interpreter and nothing else. You hand it a `.tflite` FlatBuffer that somebody converted on a
laptop and it gives you an
[`Interpreter`](https://ai.google.dev/edge/api/tflite/python/tf/lite/Interpreter) that turns
numpy arrays into numpy arrays.

On a phone it is the shortest path from *"we have a `.tflite`"* to *"the app answers
offline"* — classification, keyword spotting, pose, embeddings, anything the TFLite converter
can emit. Training and conversion stay on the desktop; only the forward pass ships. The CPU
accelerator comes with it: **XNNPACK is compiled into all six slices and applied by default**,
32-bit ARM included.

What it is *not* is a route to the phone's NPU, and it is not a converter — read
[Things to know](#things-to-know) before you size a model. Neighbouring runtimes on this index
finish different jobs: [`onnxruntime`](../onnxruntime) runs ONNX graphs, [`ncnn`](../ncnn) its
own `.param`/`.bin` format, and [`llama-cpp-python`](../llama-cpp-python) GGUF language models.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "numpy",
]

[tool.flet.android]
dependencies = [
    "tflite-runtime",
]

[tool.flet.ios]
dependencies = [
    "tflite-runtime",
]
```

**The platform tables are not a style choice.** No `tflite-runtime` wheel exists that a desktop
Python can install — pypi.flet.dev publishes mobile tags only, upstream's own PyPI releases stop
at 2.14.0 and cp311 on Linux, and there has never been an sdist. A top-level
`"tflite-runtime"` entry therefore makes your own project unresolvable: `uv lock` in an empty
directory answers *Because there is no version of tflite-runtime … your project's requirements
are unsatisfiable*. Declared under the platform tables instead, Flet
[appends them](https://flet.dev/docs/publish/#app-dependencies) to the project list when it
resolves for the device — `apk`/`aab` read `[tool.flet.android]`, `ipa`/`ios-simulator` both
read `[tool.flet.ios]`.

The cost is that **the package is then absent from `flet run` on your desktop as well**, because
nothing outside a `flet build` run reads those tables. Guard the import and put something on
screen when it fails; the example does exactly that and is the shape to copy.

Set `requires-python = ">=3.12"`. Only cp312, cp313 and cp314 wheels are published, and
`requires-python` is what `flet build` reads to choose the bundled Python — leave the floor
lower and it can pick an interpreter no wheel on the index matches.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`threads-and-delegates`](examples/threads-and-delegates) — a 1 KB TFLite model embedded in
  the app, run on device across thread counts and checked against numpy.

## Usage in a Flet app

Load once, then invoke per event:

```python
import os

import numpy as np
from tflite_runtime.interpreter import Interpreter

model = os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "model.tflite")
interpreter = Interpreter(model_path=model, num_threads=2)
interpreter.allocate_tensors()  # where the memory goes, and where a bad model raises
inputs = interpreter.get_input_details()[0]
outputs = interpreter.get_output_details()[0]

interpreter.set_tensor(inputs["index"], np.asarray(x, dtype=inputs["dtype"]))
interpreter.invoke()
label.value = str(interpreter.get_tensor(outputs["index"])[0])
```

Take the dtype from `get_input_details()` rather than writing `np.float32` — that one line is
what stops the most common failure on this API (see [Things to know](#things-to-know)). Build
the interpreter at startup and keep it; do not build one per tap.

### Storage

A model is an ordinary file, and `Interpreter` takes either a path or the bytes themselves.

**Shipped with the app** — put the `.tflite` in `src/assets/` and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir), as
the snippet above does. Assets are read-only and are replaced on every app update, which is
exactly right for a model that ships with the build.

**Downloaded on device** — write it to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups. Never keep a
model you cannot cheaply re-fetch in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

**No file at all** is also supported: `Interpreter(model_content=blob)` takes a `bytes` object,
so a model held in a database column, a preferences blob, or decoded from the source itself
never has to touch the filesystem. The example does that.

**`model_path` does not save you the memory.** Staged RSS on a 100 MB model, desktop, one mode
per process: via `model_path`, `Interpreter(...)` costs +1.5 MB and `allocate_tensors()`
+193 MB; via `model_content`, reading the file costs +96 MB and `allocate_tensors()` another
+97 MB. Both end at **about +194 MB — twice the file** — because the mapped pages become
resident when XNNPACK repacks the weights. Twenty further `invoke()` calls added nothing. Size
the model against the handset, not the laptop.

Inference itself writes nothing: the package contains no `open(` call at all, and the
`Interpreter` API exposes no profiling, tracing or logging switch to turn one on.

### Threading

**`invoke()` releases the GIL for its whole duration; `allocate_tensors()` holds it.** That
decides where a worker thread is worth having. Measured on a desktop 10-core host by a canary
thread recording the longest gap between its own iterations while the call ran — a canary that
never gets a turn is a UI thread that never gets a frame:

| call | duration | longest canary stall | stall ÷ call |
| --- | --- | --- | --- |
| `invoke()`, 4,096 rows | 6.3 ms | 0.04 ms | 0.01 |
| `invoke()`, 262,144 rows | 7.6 ms | 0.06 ms | 0.01 |
| `invoke()`, 1,048,576 rows | 12.5 ms | 0.05 ms | 0.00 |
| `allocate_tensors()`, 100 MB model, ×5 | 17.8–49.3 ms | 11.9–43.9 ms | 0.67–0.89 |

So inference in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
genuinely keeps the UI responsive — at every batch size, not only the big one — and moving
*model loading* there does not. `Interpreter(...)` is left off the table deliberately: it holds
the GIL, but only for the 0.13–0.16 ms it takes whether the buffer is 1 KB or 100 MB. What
construction costs is +1.5 MB on a 100 MB model, because it copies and unpacks nothing;
everything expensive happens in `allocate_tensors()`.

Two standing Flet caveats apply either way: `run_thread` never retrieves the worker's future,
so an exception raised inside one surfaces nowhere at all — wrap the body in
`try/except Exception` — and auto-update does not reach background threads, so end the handler
with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**One `Interpreter` shared across threads is effectively unusable, and under `run_thread` it
fails invisibly.** Six threads running 400 `set_tensor`/`invoke`/`get_tensor` cycles each on one
interpreter raised `RuntimeError: There is at least 1 reference to internal data in the
interpreter in the form of a numpy array or slice…` **2,000 times out of 2,400**. It is not a
data race and no answer came back wrong — it is `Interpreter._ensure_safe()`, which asserts
`sys.getrefcount(self._interpreter) == 2`, and a second thread holding its own temporary
reference trips it. Because `run_thread` swallows what a worker raises, the symptom on device is
a tap that silently does nothing. The same run with **one interpreter per thread** gave 0
exceptions, and so did the shared interpreter with the whole cycle inside a `threading.Lock` —
either fix works; pick per-thread interpreters if the model is small and the lock if it is not.

**Set `num_threads` yourself, at construction.** It defaults to `1`, not to anything adaptive —
`interpreter.py` passes `int(num_threads or 1)` to both wrapper constructors, and a default
interpreter measured identically to `num_threads=1` and created no extra OS threads. (The
docstring in the same file says "an implementation-dependent default number of threads";
believe the code.) `num_threads=N` creates exactly `N-1` extra OS threads, and creates them at
`allocate_tensors()`, not at construction. There is no way to change it afterwards: the C++
wrapper has a `SetNumThreads`, but `Interpreter` never exposes it, so a different thread count
means a different interpreter. Thread accounting is the same on both platforms — there is no
OpenMP in any slice, so `num_threads` is the only knob either one has.

**More threads is not monotonically better, and small work regresses.** Over repeated desktop
runs of the example on a 10-core host, four threads landed between **1.3× and 2.1×** the
1-thread speed at batch 1,048,576 and at **0.46–0.93× — slower** — at batch 4,096. The
run-to-run spread is wide enough that the shape of the curve, not any one figure, is what to
read; the example prints the whole table for that reason. On a big.LITTLE phone the crossover is
somewhere else again, and a backgrounded app that grabs the little cores is throttled or killed
rather than merely slowed. Start at 2, then measure on the handset.

### App size

Roughly 2.0–3.2 MB of compressed wheel and 4.4–8.9 MB unpacked per slice, measured across
all six on 2026-08-25:

| slice | wheel | unpacked |
| --- | ---: | ---: |
| android arm64-v8a | 2.27 MB | 6.32 MB |
| android armeabi-v7a | 1.99 MB | 4.39 MB |
| android x86_64 | 2.95 MB | 8.07 MB |
| iOS arm64 (device) | 2.21 MB | 6.48 MB |
| iOS arm64 (simulator) | 2.29 MB | 6.62 MB |
| iOS x86_64 (simulator) | 3.19 MB | 8.88 MB |

Decimal MB throughout — the x86_64 slices are the
large end and 32-bit ARM the small one. Resolved the way `flet build` does, with numpy, a target
downloads about 8–11 MB in total, and numpy is the larger half of that. Almost all of the
package payload is one extension module, so there is no test suite or data directory worth
naming to [`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup).

All three Android ABIs are published, so
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) is a
choice rather than a constraint: narrow it, or use an app bundle or split APKs, when the app
does not need every ABI. These figures describe the package payload, not the amount added to the
final APK or IPA; packaging and compression determine that.

### Android

**TFLite's own C++ output goes to logcat, not to `console.log`.** The binary links
`__android_log_vprint` and carries the tag string `tflite`, so the
`INFO: Created TensorFlow Lite XNNPACK delegate for CPU.` banner and every C++ `ERROR` line land
there. Python exceptions are unaffected and read the same on both platforms. Do not reach for
the banner to find out which delegate applied — read it from Python instead, as
[the example](examples/threads-and-delegates) does.

### iOS

The same C++ output goes somewhere else again: this binary writes through stderr and
`os_log` rather than the Android log, and where stderr surfaces in a Flet iOS run is not
something the wheel can answer. So the advice above is the portable one — read the applied
delegate from Python on both platforms rather than hunting for a banner.

### Other considerations

**Your desktop is not a preview of the device**, and cannot be made into one: there is no
desktop wheel to install by hand. Every timing and memory claim on this page has to be confirmed
on a device or emulator/simulator, which is what the example's on-screen table is for.

Leave Flet's [compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup)
on, on both platforms. The package's three `__file__` uses are pure string operations that never
touch the filesystem, so compiling to `.pyc` is safe, and it carries no data file the default
cleanup could take by accident.

## Things to know

- **XNNPACK on the CPU is the only backend, and it is applied by default.** There is no GPU,
  NNAPI, CoreML or Hexagon delegate anywhere in this build, on either platform. XNNPACK itself is
  compiled into every slice including 32-bit ARM, and the default-delegate hook really does
  create one rather than returning a stub. From Python it shows up as an extra op named
  `DELEGATE` appended to `interpreter._get_ops_details()`; selecting
  `experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES` removes it,
  and there is no reason to.
- **There is no Flex (Select TF ops) delegate either, and asking for one cannot work.**
  `tflite::AcquireFlexDelegate()` is present in all six slices but never returns one: on iOS it
  looks up a symbol nothing in the wheel defines, and on Android it is a stub that hands back an
  empty pointer without looking. Convert with
  [`target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]`](https://ai.google.dev/edge/litert/models/ops_select)
  only — never `SELECT_TF_OPS`, and never `allow_custom_ops`.
- **A model whose ops this build lacks fails at `allocate_tensors()`, not at `Interpreter(...)`**
  — so a `try/except` wrapped only around construction catches nothing. Reproduced with three
  different Select-TF-op models: `Interpreter(model_path=…)` returned normally each time, then
  `allocate_tensors()` raised `RuntimeError: Select TensorFlow op(s), included in the given
  model, is(are) not supported by this interpreter … Node number 1 (FlexMatrixDeterminant) failed
  to prepare.` The sibling messages `Encountered unresolved custom op: %s.` and *Didn't find op
  for builtin opcode … Are you using an old TFLite binary with a newer model?* are in every
  shipped binary too. Wrap `allocate_tensors()` in `try/except RuntimeError`; the message names
  the offending node. The Gradle advice inside that message is for the Java path and does not
  apply to a Flet app.
- **A bad model produces five different messages, none of which says "empty".** All are
  `ValueError` from `Interpreter(...)`: a zero-length file at `model_path` gives
  `Mmap of '3' at offset '0' failed with error '22'.`; a truncated *file* gives
  `No subgraph in the model.`; truncated or garbage *bytes* give
  `The model is not a valid Flatbuffer buffer`; a missing path gives `Could not open '<path>'.`
  And `Interpreter(model_content=b"")` reports `model_path` or `model_content` must be specified
  — an empty download looks like a missing argument. Check the size of whatever you downloaded or
  copied, and catch `ValueError` around construction separately from `RuntimeError` around
  `allocate_tensors()`.
- **`set_tensor` is strict about dtype in a way that catches almost everyone.** A plain Python
  list, or any array not explicitly `float32`, is rejected: `ValueError: Cannot set tensor: Got
  value of type FLOAT64 but expected type FLOAT32 for input 0, name: serving_default_x:0`. A
  wrong shape gives `Cannot set tensor: Dimension mismatch. Got 5 but expected 4 for dimension 1
  of input 0.` Always pass `np.asarray(x, dtype=details["dtype"])` with the dtype read from
  `get_input_details()`.
- **`resize_tensor_input()` invalidates the allocation, and the failure surfaces on the next
  `set_tensor`** as `Cannot set tensor: Tensor is unallocated. Try calling allocate_tensors()
  first`. Always call `allocate_tensors()` again after a resize, and re-read
  `get_input_details()` because the shape changed. Done properly it is powerful: the example
  drives a 1 KB static-shape model up to 1,048,576 rows this way.
- **Use `get_tensor()`, not `tensor()`, in app code.** `tensor(i)` returns a *callable*, and the
  callable is safe to keep — but the numpy array it returns is a live view of interpreter memory,
  and holding that array makes the very next `invoke()` raise `RuntimeError: There is at least 1
  reference to internal data in the interpreter…` until it is dropped. `get_tensor()` copies and
  has no such rule. It also works on constant tensors even with the delegate attached, which is
  how the example reads a model's own weights back out and recomputes the answer independently.
- **Nothing here can produce or analyse a model.** `tflite_runtime.interpreter` exposes exactly
  `Interpreter`, `InterpreterWithCustomOps`, `OpResolverType`, `Delegate`, `load_delegate` and
  `SignatureRunner`. Everything else in `tf.lite` — `TFLiteConverter`, `OpsSet`, `Optimize`,
  `RepresentativeDataset`, `TargetSpec`, and the experimental `Analyzer`, `QuantizationDebugger`
  and `authoring` helpers — is absent, and `tensorflow` itself is not published for mobile.
  Convert and quantize on a laptop.
- **Quantize to int8 rather than hoping for an NPU.** int8 models are delegated to XNNPACK too —
  an int8 `CONV_2D` model reads `['CONV_2D', 'CONV_2D', 'DELEGATE']` — and both arm64 slices,
  Android and iOS alike, carry the same wide-integer kernels (i8mm `SMMLA` and SME). What those
  kernels are worth on a given SoC is a measurement, not a symbol count.
- **Every `Interpreter()` construction warns, and the warning points somewhere you cannot go.**
  `UserWarning: Warning: tf.lite.Interpreter is deprecated and is scheduled for deletion in
  TF 2.20. Please use the LiteRT interpreter from the ai_edge_litert package. …` fires because
  `_IS_LITERT_PACKAGE` is false for a package named `tflite_runtime`. Under default filters it
  prints once per process, to stderr. `ai-edge-litert` is not published on pypi.flet.dev, and
  neither are `tensorflow`, `tflite-support`, `litert` or `ai-edge-torch` — so there is nothing
  to migrate to, and the deadline in the message has already passed. Silence it with
  `warnings.filterwarnings("ignore", category=UserWarning, module=r"tflite_runtime\.interpreter")`
  before you construct anything.
- **Importing it is cheap.** `from tflite_runtime.interpreter import Interpreter` pulls in the
  five modules the wheel ships and nothing else of its own — the package, `interpreter`, the
  native wrapper, `metrics_interface` and `metrics_portable` — plus numpy, ctypes and platform.
  `metrics_portable` is a no-op stub: every `TFLiteMetrics` method is `pass`.
- **These wheels are newer than anything upstream publishes, and there is nothing to compare them
  against.** PyPI's `tflite-runtime` stops at 2.14.0 and at cp311, with no sdist at any version
  and nothing for iOS or Android ever. So there is no reference build to check a surprise
  against: treat behaviour questions as answerable only by running it, and record what you find
  here.

## Build notes (maintainers)

### Recipe shape

A PEP 517 shim, like [`onnxruntime`](../onnxruntime), and for the same reason: TensorFlow ships
no sdist and no `setup.py` for `tflite-runtime` anywhere in its tree, only
`build_pip_package_with_cmake.sh`, whose cmake dispatch has no Android case at all.
`patches/mobile.patch` adds a backend that replicates that script inside the PEP 517 hooks
rather than trying to drive it.

There is deliberately no `flet-libtensorflowlite` recipe under this one: the wrapper statically
absorbs the interpreter, XNNPACK, ruy, abseil, Eigen, flatbuffers and pytorch/cpuinfo, which is
what makes the shipped wheel exactly eleven entries with one `.so`. The Android extension links
`libc++_shared.so`, so those slices carry an extra `Requires-Dist` on `flet-libcpp-shared`; iOS
links the system `libc++` and needs no companion wheel, and takes no link-time dependency on
Python either — 152 of its 429 undefined symbols are CPython API, resolved at `dlopen`.

The iOS extensions need no fixing up: all three slices are already `MH_DYLIB` marked
`NOUNDEFS TWOLEVEL`, so the `MH_BUNDLE` conversion other recipes on this index depend on never
engages here. Their `LC_ID_DYLIB` install name ends in `.dylib` even though the file on disk
is a `.so`; nothing resolves against it, and it is noted only so an `otool -L` reading is not
mistaken for a missing dependency.

### Upgrade hazards

**The `meta.yaml` comment above the Android `FORGE_CMAKE_ARGS` contradicts the shipped wheels**
and should be corrected on the next touch of that file. It says XNNPACK is off for
`armeabi-v7a`; the shim's own comment says the opposite ("XNNPACK stays ON for every ABI … the
python wheel cannot be built with `TFLITE_ENABLE_XNNPACK=OFF` at all"), and the wheel agrees
with the shim. A symbol check alone would not settle this — `MaybeCreateXNNPACKDelegate` is
defined either way, as a real function or as a `return nullptr` stub — so disassemble it: on all
three ABIs, armeabi-v7a included, it calls `TfLiteXNNPackDelegateOptionsDefault` and
`TfLiteXNNPackDelegateCreateWithThreadpool`. The sections above take the wheel's word.

Two slice-comparison traps, recorded because opening one binary and generalising gets them
wrong. The iOS `LC_BUILD_VERSION` minimum is not the same across the three slices despite the
identical `ios_13_0` in every filename — device and x86_64 simulator say 13.0, the arm64
simulator says 14.0. And **both simulator wheels ship an extension with the same filename**,
`_pywrap_tensorflow_interpreter_wrapper.cpython-3xx-iphonesimulator.so`; only the wheel tag
tells arm64 from x86_64.

### Re-verification checklist

A version bump can falsify the consumer-facing claims without the build going red.

- **The delegate set.** The negative scan in [Things to know](#things-to-know) — GPU, NNAPI,
  CoreML, Hexagon, Flex — is the check, and it is the claim a consumer will plan a feature
  around. `tests/` covers inference, not what accelerated it; an assertion that
  `_get_ops_details()` ends in `DELEGATE` would pin the XNNPACK half cheaply.
- **The Android ABI list.** All three publishing today is what makes `target_arch` a choice in
  [App size](#app-size). If armeabi-v7a ever drops out, that paragraph and the example's
  `pyproject.toml` both change.
- **`Requires-Dist`.** The wheel declares no `Requires-Python` of its own and takes `numpy` plus,
  on Android, `flet-libcpp-shared`. Upstream moves the numpy floor without ceremony.
- **The Python matrix.** cp312/cp313/cp314 today; the `requires-python` value in
  [Install](#install) and in the example's `pyproject.toml` is derived from it, and that value is
  what `flet build` uses to pick the bundled Python.
- **Whether upstream has published anything for a desktop OS.** The whole
  `[tool.flet.android]`/`[tool.flet.ios]` argument in [Install](#install) rests on there being no
  desktop wheel *at a Python this recipe targets*. `curl
  https://pypi.org/pypi/tflite-runtime/json` settles it, but read the interpreter tags and not
  just the platform tags: 2.5.0 does carry macOS and Windows files, and they are cp35–cp38.
- **The sizes and the download totals.** All measured off the cp314 wheels and a `pip download`
  against pypi.flet.dev; quote decimal MB, not what `du -h` prints. The iOS slices keep a partial
  symbol table — `strip -S -x` on a copy of the device extension recovers about 1.0 MB of 6.4 —
  which is the obvious size win nobody has taken.
- **Android ELF hygiene.** All three `PT_LOAD` segments are 16 KB (`0x4000`) aligned on every
  ABI, which Android 15 requires; the extension carries no `RUNPATH` or `RPATH` and is stripped.
- **The GIL, thread-accounting and memory measurements.** All desktop, from a version-matched
  `tensorflow` control venv whose `tensorflow/lite/python/interpreter.py` is byte-identical to
  the shipped `tflite_runtime/interpreter.py` — which is what makes that venv a legitimate
  stand-in for every Python-layer claim, and what stops being true the moment the two files
  diverge.

### Coverage gaps

`tests/` runs two real inferences through a committed 1 KB model and checks the numbers against
desktop-recorded expectations. It covers nothing else: not which delegate ran, not `num_threads`,
not memory, not `resize_tensor_input`, and not any of the failure messages quoted above. Every
threading and memory figure on this page is desktop measurement, not device evidence — the
example's screen exists to be the thing you read the device's own numbers off.
