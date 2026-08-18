# tflite-runtime

[`tflite-runtime`](https://ai.google.dev/edge/litert/inference) is TensorFlow Lite's
interpreter and nothing else. You hand it a `.tflite` FlatBuffer that somebody converted on a
laptop and it gives you an
[`Interpreter`](https://ai.google.dev/edge/api/tflite/python/tf/lite/Interpreter) that turns
numpy arrays into numpy arrays. That is the whole package: four Python files and one
extension module, eleven entries per wheel.

On a phone it is the shortest path from *"we have a `.tflite`"* to *"the app answers
offline"* — classification, keyword spotting, pose, embeddings, anything the TFLite converter
can emit. Training and conversion stay on the desktop; only the forward pass ships. And
unlike the sibling [`onnxruntime`](../onnxruntime) build, this one has a real CPU accelerator
compiled in: **XNNPACK, in all six slices, applied by default**, including 32-bit ARM.

Which of the two you want, if you have a choice of export format:

| | tflite-runtime | [`onnxruntime`](../onnxruntime) |
| --- | --- | --- |
| CPU backend | XNNPACK, on by default | MLAS, no XNNPACK |
| default threads | 1 | half the logical cores |
| releases the GIL in | `invoke()` | `run()` |
| holds the GIL in | `allocate_tensors()` | `InferenceSession(...)` |
| Android ABIs published | all three | no `armeabi-v7a` |
| wide int8 kernels (`SMMLA`) | both arm64 slices | Android only |
| unpacked, arm64-v8a | 6,321,278 B | 26,497,167 B |

The other neighbours on this index finish different jobs: [`ncnn`](../ncnn) is a third CPU
inference runtime, with its own `.param`/`.bin` model format;
[`llama-cpp-python`](../llama-cpp-python) runs GGUF language models through `libllama`;
[`faiss-cpu`](../faiss-cpu) searches the vectors a model here produces; and
[`safetensors`](../safetensors) memory-maps a large side table you would rather not hold
resident.

What this is **not** is a route to the phone's NPU, and it is not a converter — see
[Things to know](#things-to-know) before you size a model.

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

**The platform tables are not a style choice.** There is no `tflite-runtime` wheel your
development machine can install: pypi.flet.dev publishes mobile tags only, and upstream's own
PyPI releases stop at 2.14.0, whose newest interpreter is cp311. Everything from 2.7.0 on is
Linux-only (`manylinux2014_x86_64`, `manylinux_2_34_aarch64`, `manylinux_2_34_armv7l`); the
only release that ever carried desktop wheels is 2.5.0, cp35–cp38 on Intel macOS and
`win_amd64`; and no release, ever, carried an sdist. Under the `>=3.12` this package needs,
nothing upstream is installable or buildable on any OS. So a
top-level `"tflite-runtime"` entry makes your own project unresolvable; with the version
pinned, `uv lock` in an empty directory answers *Because there is no version of
tflite-runtime==2.21.0 … your project's requirements are unsatisfiable*. Declared under the
platform tables instead, Flet
[appends](https://flet.dev/docs/publish/#app-dependencies) them to the project list when it
resolves for the device (`flet_cli/commands/build_base.py`:
`toml_dependencies.extend(platform_dependencies)`), and both mobile targets are covered —
`apk`/`aab` read `[tool.flet.android]`, `ipa`/`ios-simulator` both read `[tool.flet.ios]`.

The cost of that is worth stating plainly: **the package is then absent from `flet run` on
your desktop as well**, because nothing outside a `flet build` run reads those tables. Guard
the import and have something on screen when it fails; the example does exactly this and is
the shape to copy.

**Only numpy comes along, and on Android one runtime library.** `Requires-Dist` is
`numpy>=1.23.2` on all six slices, and it is not optional — `interpreter.py` does
`import numpy as np` at module top. The Android slices add a second line,
`flet-libcpp-shared (>=27.2.12479018)`, which rides along on its own and needs no
configuration. Resolving the way `flet build` does
(`pip download --only-binary=:all: --platform … --index-url https://pypi.flet.dev
--extra-index-url https://pypi.org/simple`, Python 3.14):

| target | wheels | total |
| --- | --- | --- |
| Android arm64-v8a | tflite-runtime 2.17 + numpy 6.53 + flet-libcpp-shared 0.39 MB | 9.09 MB |
| Android armeabi-v7a | 1.89 + 6.16 + 0.33 MB | 8.39 MB |
| Android x86_64 | 2.82 + 7.84 + 0.40 MB | 11.06 MB |
| iOS device | 2.10 + 6.28 MB | 8.39 MB |

**All three Android ABIs are published, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is forced on you** — the opposite of the onnxruntime recipe next door, and worth
knowing if you are porting an app between the two. Eighteen wheels are on the index: Python
3.12, 3.13 and 3.14 across six slices (three Android ABIs, iOS device, and both simulator
architectures).

**The wheel declares no `Requires-Python` at all**, so it imposes no floor of its own — but
only cp312, cp313 and cp314 wheels exist, and `requires-python` is what `flet build` reads to
choose the bundled Python. `>=3.12` is the honest value for an app that pins this package.

No [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
needed. Both conditions hold: the package's three `__file__` uses are pure string operations
(`os.path.splitext(__file__)[0].endswith(...)`, deciding whether this copy is the one inside
the `tensorflow` package) and never touch the filesystem, and the extension carries a CPython
ABI tag on every slice —
`tflite_runtime/_pywrap_tensorflow_interpreter_wrapper.cpython-314-aarch64-linux-android.so`
and its siblings — which is what lets serious_python relocate it into `jniLibs` with an
importable `.soref`.

## Storage

A model is an ordinary file, and `Interpreter` takes either a path or the bytes themselves.
Which you want depends on where the model comes from.

**Shipped with the app** — put the `.tflite` in `src/assets/` and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir):

```python
path = os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "model.tflite")
interpreter = Interpreter(model_path=path)
```

Assets are read-only and are replaced on every app update, which is exactly right for a model
that ships with the build.

**Downloaded on device** — write it to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups. Never keep a
model you cannot cheaply re-fetch in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

**No file at all** is also supported: `Interpreter(model_content=blob)` takes a `bytes`
object, so a model held in a database column, a preferences blob or decoded from the source
itself never has to touch the filesystem. The example does that.

**`model_path` does not save you the memory.** Staged RSS on a 100.7 MB model, desktop, one
mode per process: via `model_path`, `Interpreter(...)` costs +1.5 MB and `allocate_tensors()`
+192.7 MB; via `model_content`, reading the file costs +96.0 MB and `allocate_tensors()`
another +96.7 MB. Both end at **+194.2 MB — about twice the file** — because the mapped pages
become resident when XNNPACK repacks the weights. Twenty further `invoke()` calls added
nothing. Size the model against the handset, not the laptop.

Inference itself writes nothing: the four Python modules contain no `open(` call at all, and
the `Interpreter` API exposes no profiling, tracing or logging switch to turn one on.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`threads-and-delegates`](examples/threads-and-delegates) — a 1 KB TFLite model embedded in
  the app, run on device across thread counts and checked against numpy.

## Threading

**`invoke()` releases the GIL for its whole duration; `allocate_tensors()` holds it.**
That decides where a worker thread is worth having, and it is the mirror image of
onnxruntime, where the *session build* is the blocking half. Measured with a canary thread
recording the longest gap between its own iterations while the call runs — a canary that
never gets a turn is a UI thread that never gets a frame. Two things make the readings mean
something. The window edges count, so a call that finishes before the canary can sample it
even once reads as a *full* stall instead of as a reassuring zero; on an empty window the
canary reports 0.015 ms, and that is the floor every row below has to clear. And the first
two rows are the harness checking itself at two durations each: a call known to release must
sit near 0 and one known to hold near 1, or nothing under them is evidence. Desktop CPython
3.12, 10-core host:

| call | duration | longest canary stall | stall ÷ call |
| --- | --- | --- | --- |
| `hashlib.sha256` of 2 / 128 MB (releases) | 7.0 / 58.9 ms | 0.04 / 0.05 ms | 0.01 / 0.00 |
| `sum(range(200_000 / 12_000_000))` (holds) | 1.4 / 103.3 ms | 1.4 / 97.0 ms | 1.02 / 0.94 |
| `invoke()`, 4,096 rows | 6.3 ms | 0.04 ms | 0.01 |
| `invoke()`, 262,144 rows | 7.6 ms | 0.06 ms | 0.01 |
| `invoke()`, 1,048,576 rows | 12.5 ms | 0.05 ms | 0.00 |
| `allocate_tensors()`, 100 MB model, ×5 | 17.8–49.3 ms | 11.9–43.9 ms | 0.67–0.89 |

So inference in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
genuinely keeps the UI responsive — at every batch size, not only the big one — and moving
*model loading* there does not. `Interpreter(...)` is left off the table deliberately: it
holds the GIL, but only for the 0.13–0.16 ms it takes whether the buffer is 1 KB or 100 MB,
and a row that short says nothing worth acting on. (It is also where a harness that ignores
its window edges goes wrong, reporting a stall of exactly 0.00 ms — no sample taken — and
reading like a call that releases.) What construction costs is +1.4 MB on a 100 MB model,
because it copies and unpacks nothing; everything expensive happens in `allocate_tensors()`.
So load the model once at startup and keep the interpreter; do not build one per tap.

Two standing Flet caveats apply either way: `run_thread` never retrieves the worker's future,
so an exception raised inside one surfaces nowhere at all — wrap the body in
`try/except Exception` — and auto-update does not reach background threads, so end the
handler with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**One `Interpreter` shared across threads is effectively unusable, and under `run_thread` it
fails invisibly.** Six threads running 400 `set_tensor`/`invoke`/`get_tensor` cycles each on
one interpreter raised `RuntimeError: There is at least 1 reference to internal data in the
interpreter in the form of a numpy array or slice…` **2,000 times out of 2,400**. It is not a
data race and no answer came back wrong — it is `Interpreter._ensure_safe()`, which asserts
`sys.getrefcount(self._interpreter) == 2`, and a second thread holding its own temporary
reference trips it. Because `run_thread` swallows what a worker raises, the symptom on device
is a tap that silently does nothing. The same run with **one interpreter per thread** gave 0
exceptions, and so did the shared interpreter with the whole cycle inside a
`threading.Lock` — either fix works; pick per-thread interpreters if the model is small and
the lock if it is not.

**Set `num_threads` yourself, at construction.** It defaults to `1`, not to anything adaptive
— `interpreter.py` passes `int(num_threads or 1)` to both wrapper constructors, and a default
interpreter measured identically to `num_threads=1` and created no extra OS threads. (The
docstring in the same file says "an implementation-dependent default number of threads";
believe the code.) `num_threads=N` creates exactly `N-1` extra OS threads, and creates them at
`allocate_tensors()`, not at construction — verified against `ps -M` at 1, 2, 4 and 8. There
is no way to change it afterwards: the C++ wrapper has a `SetNumThreads`, but `Interpreter`
never exposes it, so a different thread count means a different interpreter. The `ps -M` runs
were desktop, but unlike [`ncnn`](../ncnn#threading) the accounting is not platform-split:
there is no OpenMP in any slice — zero `__kmp`, `omp_`, `GOMP` and `OMP_NUM_THREADS` strings
in the Android and iOS binaries alike — so both platforms use TFLite's own C++ pool, and
`num_threads` is the only knob on either.

**More threads is not monotonically better, and small work regresses.** Over repeated runs of
the example on the same 10-core desktop host, four threads landed between **1.3× and 2.1×**
the 1-thread speed at batch 1,048,576 and at **0.46–0.93× — slower** — at batch 4,096. The
run-to-run spread is wide enough that the shape of the curve, not any one figure, is what to
read; the example prints the whole table for that reason. On a
big.LITTLE phone the crossover is somewhere else again, and a backgrounded app that grabs the
little cores is throttled or killed rather than merely slowed. Start at 2, then measure on the
handset, which is what the example puts on screen.

## Android notes

The extension links six libraries — `libpython3.xx.so`, `libdl.so`, `libm.so`, `liblog.so`,
**`libc++_shared.so`** and `libc.so` — with `SONAME`
`_pywrap_tensorflow_interpreter_wrapper.so` and no `RUNPATH` or `RPATH` at all. That fifth
one is why the Android wheels carry the extra `Requires-Dist: flet-libcpp-shared` the iOS
wheels do not.

All three `PT_LOAD` segments are 16 KB (`0x4000`) aligned on every ABI, which Android 15
requires.

**TFLite's own C++ output goes to logcat, not to `console.log`.** The binary links
`__android_log_vprint` and carries the tag string `tflite`, so the
`INFO: Created TensorFlow Lite XNNPACK delegate for CPU.` banner and every C++ `ERROR` line
land there. Python exceptions are unaffected and read the same on both platforms. Do not
reach for the banner to find out which delegate applied — read it from Python instead, as
[the example](examples/threads-and-delegates) does.

Runtime CPU dispatch reads the kernel: `/proc/cpuinfo`,
`/sys/devices/system/cpu/{possible,present,kernel_max}` and per-CPU `cpufreq`/`topology`
paths, plus `getauxval` and `sysconf`. Which kernels that selects on a given SoC is not
something the wheel can tell you — measure it.

The extensions are stripped (`llvm-nm` reports *no symbols*; 6,449 dynamic symbols on
arm64-v8a).

| slice | wheel | unpacked | the `.so` alone |
| --- | --- | --- | --- |
| arm64-v8a | 2.17 MB | 6.03 MB | 5.97 MB |
| armeabi-v7a | 1.89 MB | 4.19 MB | 4.13 MB |
| x86_64 | 2.82 MB | 7.70 MB | 7.64 MB |

## iOS notes

The extension links only the OS: `CoreFoundation`, `/usr/lib/libSystem.B.dylib`,
`/usr/lib/libc++.1.dylib` and `/usr/lib/libobjc.A.dylib`. There is no companion wheel and no
extra `Requires-Dist` — iOS uses the system C++ runtime where Android needs
`flet-libcpp-shared`. Nor is there a link-time dependency on Python: **152 of the 429
undefined symbols are CPython API**, resolved at `dlopen` through dyld.

**The extension needs no fixing up.** All three slices are `MH_DYLIB` marked
`NOUNDEFS TWOLEVEL` (`otool -hv`), so the `MH_BUNDLE` conversion other recipes on this index
depend on never engages here. Their `LC_ID_DYLIB` install name is
`@rpath/_pywrap_tensorflow_interpreter_wrapper.dylib` even though the file on disk is a
`.so`; nothing resolves against it, and it is noted only so a `otool -L` reading is not
mistaken for a missing dependency.

C++ log output goes somewhere else than on Android: this binary imports `___stderrp`,
`_fprintf`, `_vfprintf` and `_os_log_create` where the Android one links
`__android_log_vprint`. Where stderr surfaces in a Flet iOS run is not something the wheel can
answer, so read the applied delegate from Python on both platforms rather than hunting for the
banner.

Runtime CPU dispatch goes through sysctl: `hw.cpufamily`, `hw.machine`,
`hw.physicalcpu_max`, `hw.logicalcpu_max`, `machdep.cpu.brand_string` and eleven
`hw.optional.arm.FEAT_*` keys (`DotProd`, `I8MM`, `BF16`, `FP16`, `SME`, `SME2`, `LSE`,
`RDM`, `FCMA`, `JSCVT`, `FHM`).

**The iOS extensions keep a partial symbol table**, which is most of why they are slightly
larger than the Android ones at the same architecture. `nm -a` counts 13,841 entries on the
device slice and `__LINKEDIT` is 1,622,016 of 6,424,128 bytes; `strip -S -x` on a copy takes
it to 5,386,320. That is about 1.0 MB of 6.4 — a far smaller gap than onnxruntime's 11.9 MB.

| slice | wheel | unpacked | the `.so` alone |
| --- | --- | --- | --- |
| arm64 (device) | 2.10 MB | 6.18 MB | 6.13 MB |
| arm64 (simulator) | 2.19 MB | 6.31 MB | 6.25 MB |
| x86_64 (simulator) | 3.04 MB | 8.47 MB | 8.41 MB |

Two slice-comparison traps, recorded because opening one binary and generalising gets them
wrong. The `LC_BUILD_VERSION` minimum is not the same across the three despite the `ios_13_0`
in every filename — device and x86_64 simulator say 13.0, the arm64 simulator says 14.0 (SDK
26.5 throughout). And **both simulator wheels ship an extension with the same filename**,
`_pywrap_tensorflow_interpreter_wrapper.cpython-3xx-iphonesimulator.so`; only the wheel tag
tells arm64 from x86_64.

## Things to know

- **XNNPACK on the CPU is the only backend, and it is applied by default.** There is no GPU,
  NNAPI, CoreML or Hexagon delegate anywhere in this build: zero hits for
  `TfLiteGpuDelegate`, `ANeuralNetworks`/`libneuralnetworks`/`nnapi`,
  `coreml`/`MLModel`/`MLMultiArray` and `hexagon` across all six binaries, and `otool -L` on
  the iOS slices links no `CoreML.framework`. XNNPACK itself is compiled into every slice
  including 32-bit ARM: `TfLiteXNNPackDelegateCreate` is defined on all three Android ABIs
  (718 / 715 / 752 `xnn_` strings) and the iOS symbol table lists 14 `TfLiteXNNPackDelegate*`
  entry points — and, the part a symbol list cannot tell you, the default-delegate hook
  `tflite::MaybeCreateXNNPACKDelegate` disassembles on every ABI to a real call to
  `TfLiteXNNPackDelegateCreateWithThreadpool` rather than to the `return nullptr` stub it
  compiles down to when XNNPACK is off. From Python it shows up as an extra op named
  `DELEGATE` appended to
  `interpreter._get_ops_details()`; selecting
  `experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES` removes
  it, and there is no reason to.
- **There is no Flex (Select TF ops) delegate either, and asking for one cannot work.**
  `tflite::AcquireFlexDelegate()` is present in all six slices, but it never returns one: on
  iOS it `dlsym`s `TF_AcquireFlexDelegate`, which nothing in the wheel defines and no bundled
  library provides, and on Android it is a four-instruction stub that hands back an empty
  pointer without looking (the string `TF_AcquireFlexDelegate` is in the three iOS binaries
  and in none of the Android ones).
  `tensorflowlite_flex` appears zero times in every slice. Convert with
  [`target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]`](https://ai.google.dev/edge/litert/models/ops_select)
  only — never `SELECT_TF_OPS`, and never `allow_custom_ops`.
- **A model whose ops this build lacks fails at `allocate_tensors()`, not at
  `Interpreter(...)`** — so a `try/except` wrapped only around construction catches nothing.
  Reproduced with three different Select-TF-op models: `Interpreter(model_path=…)` returned
  normally each time, then `allocate_tensors()` raised `RuntimeError: Select TensorFlow
  op(s), included in the given model, is(are) not supported by this interpreter … Node number
  1 (FlexMatrixDeterminant) failed to prepare.` The sibling messages
  `Encountered unresolved custom op: %s.` and *Didn't find op for builtin opcode … Are you
  using an old TFLite binary with a newer model?* are in every shipped binary too. Wrap
  `allocate_tensors()` in `try/except RuntimeError`; the message names the offending node. The
  Gradle advice inside that message is for the Java path and does not apply to a Flet app.
- **A bad model produces five different messages, none of which says "empty".** All are
  `ValueError` from `Interpreter(...)`: a zero-length file at `model_path` gives
  `Mmap of '3' at offset '0' failed with error '22'.`; a truncated *file* gives
  `No subgraph in the model.`; truncated or garbage *bytes* give
  `The model is not a valid Flatbuffer buffer`; a missing path gives `Could not open '<path>'.`
  And `Interpreter(model_content=b"")` reports `model_path` or `model_content` must be
  specified — an empty download looks like a missing argument. Check the size of whatever you
  downloaded or copied, and catch `ValueError` around construction separately from
  `RuntimeError` around `allocate_tensors()`.
- **`set_tensor` is strict about dtype in a way that catches almost everyone.** A plain Python
  list, or any array not explicitly `float32`, is rejected: `ValueError: Cannot set tensor:
  Got value of type FLOAT64 but expected type FLOAT32 for input 0, name: serving_default_x:0`.
  A wrong shape gives `Cannot set tensor: Dimension mismatch. Got 5 but expected 4 for
  dimension 1 of input 0.` Always pass `np.asarray(x, dtype=details["dtype"])` with the dtype
  read from `get_input_details()`.
- **`resize_tensor_input()` invalidates the allocation, and the failure surfaces on the next
  `set_tensor`** as `Cannot set tensor: Tensor is unallocated. Try calling allocate_tensors()
  first`. Always call `allocate_tensors()` again after a resize, and re-read
  `get_input_details()` because the shape changed. Done properly it is powerful: the example
  drives a 1 KB static-shape model up to 1,048,576 rows this way.
- **Use `get_tensor()`, not `tensor()`, in app code.** `tensor(i)` returns a *callable*, and
  the callable is safe to keep — but the numpy array it returns is a live view of interpreter
  memory, and holding that array makes the very next `invoke()` raise `RuntimeError: There is
  at least 1 reference to internal data in the interpreter…` until it is dropped.
  `get_tensor()` copies and has no such rule. It also works on constant tensors even with the
  delegate attached, which is how the example reads a model's own weights back out and
  recomputes the answer independently.
- **Nothing here can produce or analyse a model.** `tflite_runtime.interpreter` exposes
  exactly `Interpreter`, `InterpreterWithCustomOps`, `OpResolverType`, `Delegate`,
  `load_delegate` and `SignatureRunner`. Everything else in `tf.lite` — `TFLiteConverter`,
  `OpsSet`, `Optimize`, `RepresentativeDataset`, `TargetSpec`, and the experimental
  `Analyzer`, `QuantizationDebugger` and `authoring` helpers — is absent, and `tensorflow`
  itself is not published for mobile. Convert and quantize on a laptop.
- **Quantize to int8 rather than hoping for an NPU.** int8 models are delegated to XNNPACK
  too — an int8 `CONV_2D` model reads `['CONV_2D', 'CONV_2D', 'DELEGATE']` — and the two arm64
  slices carry the *same* wide-integer kernels: **1,056 `SMMLA` (i8mm) and 18 `SMSTART` (SME)
  in both**, with 3,954 and 2,306 `SDOT` respectively. That is a better starting point than
  onnxruntime, whose iOS slices carry no `SMMLA` at all — though what the kernels are worth on
  a given SoC is a measurement, not a symbol count.
- **Every `Interpreter()` construction warns, and the warning points somewhere you cannot
  go.** `UserWarning: Warning: tf.lite.Interpreter is deprecated and is scheduled for deletion
  in TF 2.20. Please use the LiteRT interpreter from the ai_edge_litert package. …` (a
  migration-guide link follows) fires from
  `interpreter.py` line 457 because `_IS_LITERT_PACKAGE` is false for a package named
  `tflite_runtime`. Under default filters it prints once per process, to stderr. `ai-edge-litert`
  is not published on pypi.flet.dev (404), and neither are `tensorflow`, `tflite-support`,
  `litert` or `ai-edge-torch` — so there is nothing to migrate to, and the deadline in the
  message has already passed. Silence it with
  `warnings.filterwarnings("ignore", category=UserWarning, module=r"tflite_runtime\.interpreter")`
  before you construct anything.
- **Importing it is cheap.** `from tflite_runtime.interpreter import Interpreter` pulls in all
  five modules the wheel ships and nothing else of its own — the package itself, `interpreter`,
  the native `_pywrap_tensorflow_interpreter_wrapper`, `metrics_interface` and
  `metrics_portable` — plus numpy, ctypes and platform. `metrics_portable` is a no-op stub: every
  `TFLiteMetrics` method is `pass`.
- **These wheels are newer than anything upstream publishes, and there is nothing to compare
  them against.** PyPI's `tflite-runtime` stops at 2.14.0 and at cp311, with no sdist at any
  version and nothing for iOS or Android ever. Its only non-Linux files are 2.5.0's cp35–cp38
  Intel-macOS and `win_amd64` wheels, uploaded in 2021 and dropped in every release since.
  So there is no reference build to check a surprise against: treat behaviour questions as
  answerable only by running it, and record what you find here.

## Build notes (maintainers)

`patches/mobile.patch` accounts for its three added files in its own preamble, and
`meta.yaml` explains its `script_env` entries inline. What is left is shape, one known
inconsistency, and the bump checklist.

The shape is a PEP 517 shim, like [`onnxruntime`](../onnxruntime), and for the same reason:
TensorFlow ships no sdist and no `setup.py` for `tflite-runtime` anywhere in its tree, only
`build_pip_package_with_cmake.sh`, whose cmake dispatch has no Android case at all. The patch
adds a backend that replicates that script inside the PEP 517 hooks rather than trying to
drive it. Everything else follows from that choice, and there is deliberately no
`flet-libtensorflowlite` recipe under this one: the wrapper statically absorbs the interpreter,
XNNPACK, ruy, abseil, Eigen, flatbuffers and pytorch/cpuinfo, which is what makes the shipped
wheel exactly eleven entries with one `.so`.

**The `meta.yaml` comment above the Android `FORGE_CMAKE_ARGS` contradicts the shipped
wheels** and should be corrected on the next touch of that file. It says XNNPACK is off for
`armeabi-v7a`; the shim's own comment says the opposite ("XNNPACK stays ON for every ABI …
the python wheel cannot be built with `TFLITE_ENABLE_XNNPACK=OFF` at all"), and the wheel
agrees with the shim. A symbol check alone would not settle this — `MaybeCreateXNNPACKDelegate`
is defined either way, as a real function or as a `return nullptr` stub — so disassemble it:
on all three ABIs, armeabi-v7a included, it calls `TfLiteXNNPackDelegateOptionsDefault` and
`TfLiteXNNPackDelegateCreateWithThreadpool`. The sections above take the wheel's word. This
README was not the place to fix it.

A version bump can falsify the consumer-facing claims without the build going red. What to
re-verify:

- **The delegate set.** The negative scan in [Things to know](#things-to-know) — GPU, NNAPI,
  CoreML, Hexagon, Flex — is the check, and it is the claim a consumer will plan a feature
  around. `tests/` covers inference, not what accelerated it; an assertion that
  `_get_ops_details()` ends in `DELEGATE` would pin the XNNPACK half cheaply.
- **The Android ABI list.** All three publishing today is what makes `target_arch`
  unnecessary in [Install](#install) and is the headline difference from onnxruntime. If
  armeabi-v7a ever drops out, that paragraph and the example's `pyproject.toml` both change.
- **`Requires-Dist` and the absence of `Requires-Python`.** Both feed [Install](#install)
  directly, and upstream moves the numpy floor without ceremony.
- **The Python matrix.** cp312/cp313/cp314 today; `requires-python = ">=3.12"` in the
  example's `pyproject.toml` is derived from it, and that value is what `flet build` uses to
  pick the bundled Python.
- **Whether upstream has published anything for a desktop OS.** The whole
  `[tool.flet.android]`/`[tool.flet.ios]` argument in [Install](#install) rests on there being
  no desktop wheel *at a Python this recipe targets*. `curl
  https://pypi.org/pypi/tflite-runtime/json` settles it, but read the interpreter tags and
  not just the platform tags: 2.5.0 does carry macOS and Windows files, and they are cp35–cp38.
- **The sizes, the download totals and the strip figure.** All measured off the cp314 wheels
  and a `pip download` against pypi.flet.dev. The iOS slices' ~1.0 MB of recoverable symbol
  table is the obvious size win nobody has taken.
- **The GIL, thread-accounting and memory measurements.** All desktop, from a version-matched
  `tensorflow==2.21.0` control venv whose `tensorflow/lite/python/interpreter.py` is
  byte-identical to the shipped `tflite_runtime/interpreter.py` — which is what makes that
  venv a legitimate stand-in for every Python-layer claim, and what stops being true the
  moment the two files diverge. None of it is device evidence; the example's screen exists to
  be the thing you read the device's own numbers off.
