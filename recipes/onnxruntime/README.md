# onnxruntime

[`onnxruntime`](https://onnxruntime.ai/docs/) runs a trained neural network that somebody
else exported. You hand it an `.onnx` file — from PyTorch, TensorFlow, scikit-learn,
Hugging Face, anything with an ONNX exporter — and it gives you an
[`InferenceSession`](https://onnxruntime.ai/docs/api/python/api_summary.html) that turns
numpy arrays into numpy arrays. That is the whole API surface most apps need.

On a phone it is the shortest path from *"we have a model"* to *"the app answers offline"*:
classification, embeddings, keyword spotting, small language models, anything you can export.
Training stays on a laptop; only the forward pass ships. The wheel is one self-contained
extension — no separate `libonnxruntime.so`, no companion runtime to install, and nothing in
the inference path that reaches the network.

Embeddings are the common case, and the two recipes beside this one finish that job:
[`faiss-cpu`](../faiss-cpu) searches the vectors a model here produces, and
[`safetensors`](../safetensors) memory-maps a large side table — a vocabulary or lookup matrix
— that you would rather not hold resident.

What it is **not** here is a route to the phone's NPU. This build has the CPU execution
provider and nothing else, on both platforms — see [Things to know](#things-to-know) before
you size a model.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "onnxruntime",
]

[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

**The [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
line is required, not optional.** No `armeabi-v7a` wheel is published, so a default
`flet build apk` — which targets all three ABIs — fails at dependency resolution for the
32-bit one after the other two have already resolved. Reproduced with the resolve
`flet build` performs: `pip install --dry-run --only-binary=:all: --platform
android_24_armeabi_v7a … onnxruntime` answers `ERROR: Could not find a version that satisfies
the requirement onnxruntime (from versions: none)`, where the same command with
`--platform android_24_arm64_v8a` downloads the wheel. Spell the ABI names out in full;
`arm64`/`x64` are the macOS spellings and Flet rejects them. Dropping 32-bit ARM costs you
nothing else — 64-bit has been mandatory for Play Store uploads since 2019. Everything else
Flet asks for exists: both remaining Android ABIs and all three iOS slices (device, arm64
simulator, x86_64 simulator), on Python 3.12, 3.13 and 3.14.

**Four packages come along, and only one of them is ever imported.** `Requires-Dist` names
`numpy`, `protobuf`, `flatbuffers` and `packaging`; `import onnxruntime` pulls in numpy and
none of the other three, which are imported only by the model-preparation subpackages
(`tools`, `quantization`, `transformers`, `backend`) that a phone has no use for.
Resolving for Android arm64-v8a on 3.14 downloads six wheels totalling 16.0 MB —
onnxruntime 8.40 MB, numpy 6.85 MB, `flet-libcpp-shared` 0.41 MB, protobuf 0.17 MB (the
pure-Python wheel wins the resolve), packaging 0.13 MB, flatbuffers 0.03 MB. iOS resolves the
same set minus `flet-libcpp-shared`, for 16.0 MB. The two extras declared under the `symbolic`
and `quantization` markers, `sympy` and `ml_dtypes`, are not pulled in and are not published
for mobile anyway.

**`Requires-Python` is `>=3.11`, which is higher than the `>=3.10` `flet create` writes.**
It only bites if you pin onnxruntime with `==`, and then it bites hard: uv resolves for every
version in the declared range, so the 3.10 split becomes unsatisfiable and the build stops
with *your project's requirements are unsatisfiable*. Raise `requires-python` to `>=3.11`
alongside any pin, and check it the way a consumer meets it — copy the `pyproject.toml` alone
into an empty directory and run `uv lock` there.

No [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
needed. Both conditions hold: nothing on the import path builds a filesystem path from
`__file__` (the package's single `__file__` use is inside `preload_dlls()`, a CUDA helper
nothing calls), and the Android extension carries a CPython ABI tag
(`onnxruntime_pybind11_state.cpython-3xx.so`), which is what lets Android's zipped
site-packages find it.

## Storage

A model is an ordinary file, and `InferenceSession` takes either a path or the bytes
themselves. Which one you want depends on where the model comes from.

**Shipped with the app** — put the `.onnx` in `src/assets/` and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir):

```python
path = os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "model.onnx")
session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
```

Assets are read-only and are replaced on every app update, which is exactly right for a model
that ships with the build.

**Downloaded or generated on device** — write it to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups. Never keep a
model you cannot cheaply re-fetch in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

**No file at all** is also a supported shape: `ort.InferenceSession(model_bytes, …)` accepts
a serialised `ModelProto` directly, so a model held in a database column, a preferences blob
or built at runtime never has to touch the filesystem. The example does exactly that.

Inference itself writes nothing. Profiling is the one exception — `SessionOptions.enable_profiling`
defaults to `False`, and turning it on drops a JSON trace in the process working directory.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`hand-built-mlp`](examples/hand-built-mlp) — an ONNX graph written in the app, run on
  device and checked against numpy.

## Threading

**`sess.run(...)` releases the GIL for the whole computation; `InferenceSession(...)` holds
it.** That is the opposite arrangement from the one most people assume, and it decides where
a worker thread is worth having. Measured with a canary thread that records the longest gap
between its own iterations while the call runs — a canary that never gets a turn is a UI
thread that never gets a frame. The first two rows are the harness checking itself: a call
known to release must sit near 0 and one known to hold must sit near 1, or nothing below them
means anything. Median of five, desktop CPython 3.12 on a 10-core host:

| call | duration | longest canary stall | stall ÷ call |
| --- | --- | --- | --- |
| `hashlib.sha256` of 400 MB (releases) | 178 ms | 0.9 ms | 0.01 |
| `sum(range(60_000_000))` (holds) | 493 ms | 493.1 ms | 1.00 |
| `sess.run` ×8 over 32,768 rows | 657 ms | 0.9 ms | 0.00 |
| `InferenceSession(34 MB of bytes)` | 11 ms | 10.6 ms | 0.98 |
| `InferenceSession(2.6 MB of bytes)` | 2 ms | 0.0 ms | 0.00 |

The canary only resolves stalls above about 1 ms, so the last row's `0.00` is the harness
hitting its floor rather than a session build that released anything — re-measured on models
big enough to answer, a 30 MB build stalls 15.5 of 15.6 ms and a 254 MB one 95.8 of 124.0.

So inference in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
genuinely keeps the UI responsive, and session construction does not — though at 2 ms for a
2.6 MB model and 11 ms for a 34 MB one, it only matters for a large model on a slow device.
Load the model once and keep the session; do not build one per tap.

Two standing Flet caveats apply either way: `run_thread` never retrieves the worker's future,
so an exception raised inside one surfaces nowhere at all — wrap the body in
`try/except Exception` — and auto-update does not reach background threads, so end the handler
with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**Set `intra_op_num_threads` yourself.** onnxruntime creates exactly `intra_op_num_threads - 1`
extra OS threads and runs the remaining share on the calling thread — verified against
`ps -M` at 1, 2, 3, 4 and 8. Left at its default of `0` it resolved to half the logical cores
(5 threads on a 10-core host). On a big.LITTLE phone half the logical cores reaches the little
cores as well, and a backgrounded app that grabs them is throttled or killed rather than
merely slowed, so `2` — or `max(1, os.cpu_count() // 4)` — is the saner starting point.

You cannot ask a session what it settled on: `sess.get_session_options().intra_op_num_threads`
reads back `0` for a default session while `ps -M` shows the extra threads are live. Set the
value explicitly, and if you want to know what it buys on a given handset, time the same batch
at two settings — which is what the example puts on screen.

`inter_op_num_threads` governs running independent branches of a graph in parallel and applies
only when `execution_mode` is set to `ORT_PARALLEL`; the default is `ORT_SEQUENTIAL`, so on a
default session it does nothing. There is no OpenMP anywhere in either build — no `GOMP_`,
`omp_get_max_threads` or `libomp` strings in either binary — so `intra_op_num_threads` is the
one knob, and it means the same thing on both platforms.

## Android notes

The extension links six libraries: `libdl.so`, `libpython3.xx.so`, `liblog.so`, `libm.so`,
**`libc++_shared.so`** and `libc.so`, with `RUNPATH` `$ORIGIN`. That fifth one is why the
Android wheels carry an extra `Requires-Dist: flet-libcpp-shared (>=27.2.12479018)` the iOS
wheels do not; it rides along on its own and needs no configuration.

All three `PT_LOAD` segments are 16 KB-aligned, which Android 15 requires.

Runtime CPU dispatch reads the kernel rather than a sysctl: the binary carries
`/proc/cpuinfo`, `/sys/devices/system/cpu/{possible,present,kernel_max}` and per-CPU
`cpufreq`/`topology` paths. Which kernels that selects on a given SoC is not something the
wheel can tell you — measure it.

Two ABIs are published against the three Flet targets, which is what makes the `target_arch`
entry in [Install](#install) mandatory:

| slice | wheel | unpacked | the `.so` alone |
| --- | --- | --- | --- |
| arm64-v8a | 8.40 MB | 26.5 MB | 22.1 MB |
| x86_64 | 9.25 MB | 29.4 MB | 24.9 MB |

## iOS notes

The extension links only the OS: `Foundation`, `CoreFoundation`, `/usr/lib/libiconv.2.dylib`,
`/usr/lib/libc++.1.dylib` and `/usr/lib/libSystem.B.dylib`. There is no companion wheel and no
extra `Requires-Dist` — iOS uses the system C++ runtime where Android needs
`flet-libcpp-shared`. Python symbols resolve through dyld instead of a link-time dependency:
182 of the 628 undefined symbols are CPython API — 174 that `nm` spells `_Py*` and 8 more it
spells `__Py*`.

**The extension needs no fixing up.** All three slices are `MH_DYLIB` marked `NOUNDEFS`
(`otool -hv`), which is the filetype Flet's iOS packaging needs, so the `MH_BUNDLE`
conversion other recipes on this index depend on never engages here.

**`import onnxruntime` prints a warning on iOS and it means nothing.**
`UserWarning: Unsupported platform (ios). ONNX Runtime supports Linux, macOS, AIX and Windows
platforms, only.` comes from `check_distro_info()`, called unconditionally at import time on
line 104 of the package `__init__`, which warns for any `platform.system().lower()` outside
`{windows, linux, darwin, aix}`. iOS reports `"iOS"`, so it always fires. The import completes
and inference works — reproduced by monkeypatching `platform.system()` before import:
`'iOS'` and `'Android'` both warn, `'Linux'` and `'Darwin'` do not, and all four import
successfully. Silence it with
`warnings.filterwarnings("ignore", message="Unsupported platform")` before the import if it
clutters your logs. Whether Android warns depends on what Flet's Python build reports for
`platform.system()`; the example prints it, which is the quickest way to find out on a device
you care about.

Runtime CPU dispatch goes through sysctl: `hw.cpufamily`, `hw.machine`, `hw.physicalcpu_max`,
`hw.logicalcpu_max` and eleven `hw.optional.arm.FEAT_*` keys (`DotProd`, `I8MM`, `BF16`,
`FP16`, `SME`, `SME2`, `LSE`, `RDM`, `FCMA`, `JSCVT`, `FHM`).

**The iOS extension ships unstripped**, which is the entire reason it is bigger than the
Android one — not extra code. `size -m` on the device slice puts `__LINKEDIT` at 12,075,008 of
31,965,184 bytes, `nm -a` counts 101,667 symbols in a file that exports exactly one
(`PyInit_onnxruntime_pybind11_state` — the other 628 entries `nm -g` lists are the undefined
imports above), and `strip -S -x` on a copy takes it from 31,919,480 to 20,006,056 bytes. The
Android extension is already stripped and its executable segment is 21.6 MB against iOS's
19.3 MB of `__TEXT`.

| slice | wheel | unpacked | the `.so` alone |
| --- | --- | --- | --- |
| arm64 (device) | 9.07 MB | 36.4 MB | 31.9 MB |
| arm64 (simulator) | 9.39 MB | 36.6 MB | 32.2 MB |
| x86_64 (simulator) | 10.40 MB | 39.9 MB | 35.5 MB |

The `LC_BUILD_VERSION` minimum is not the same across the three despite the `ios_13_0` in every
filename: device and x86_64 simulator say 13.0, the arm64 simulator says 14.0. It bites nothing
on a phone Flet supports, and it is recorded here because a slice comparison that opens one
binary and generalises will get it wrong.

## Things to know

- **CPU only, on both platforms. There is no NNAPI, no CoreML and no XNNPACK.** So
  `get_available_providers()` on device is `['CPUExecutionProvider']` and everything runs
  through MLAS. Verified in the binaries rather than from the build flags: C++ typeinfo names
  survive stripping, and scanning all five mobile slices for
  `N11onnxruntime<n><Name>ExecutionProviderE` yields only `IExecutionProvider`,
  `CPUExecutionProvider` and `PluginExecutionProvider`. The control that proves the scan can
  see a provider that *is* present: the same command on the PyPI macOS wheel of the same
  version additionally yields `CoreMLExecutionProvider` and `AzureExecutionProvider`, and
  `get_available_providers()` there returns exactly those two plus CPU. Corroborating
  negatives on the mobile binaries: zero `xnn_` symbols, zero `libneuralnetworks` strings, no
  `MLMultiArray`/`MLModelConfiguration`, and no `CoreML.framework` in `otool -L` (the desktop
  wheel links it).
- **Asking for a provider that is not there is a warning, not an error.**
  `providers=["NnapiExecutionProvider", "CPUExecutionProvider"]` gives
  `UserWarning: Specified provider 'NnapiExecutionProvider' is not in available provider
  names.` and silently continues on CPU, and an unknown name prints an `EP Error … Falling
  back to ['CPUExecutionProvider'] and retrying` banner and carries on. The names of all
  twenty-odd providers are present as strings in the mobile binaries — that is the static
  table behind `get_all_providers()` and says nothing about what is compiled in. Print
  `sess.get_providers()` rather than assuming.
- **Do not size a mobile feature from a benchmark on your Mac.** The PyPI macOS wheel of the
  same version carries `ArmKleidiAI` GEMM kernels; the iOS binary carries none (checked with
  `nm -a` on the unstripped file, so its symbol table is complete). What that is worth,
  measured on the example's model on an M4 at `intra_op_num_threads=1` by toggling
  `mlas.disable_kleidiai` — with an unrecognised config key as the control, which changes
  nothing — is 6× to 9× from batch 64 upwards: 9.1 ms against 57.2 ms at batch 4096, and 8.0×
  at batch 1024. Only at batch 1, where the whole call is tens of microseconds, does it fall
  to 2.5×.
  The Android binary is stripped, so its symbol table cannot be asked, but it contains zero
  `SMSTART`/`SMSTOP` instructions where the macOS dylib has 22 — so it carries none of the SME
  kernels that fp32 speed comes from either.
- **Quantize to int8 rather than hoping for an NPU.** MLAS's dot-product integer kernels are
  compiled in on both platforms — `MlasGemmS8S8KernelSDot`, `MlasGemmU8X8KernelUdot` and
  `MlasSymQgemmS8KernelSdot` are all in the iOS symbol table, and disassembling the stripped
  Android arm64 `.text` finds 1,068 `SDOT` and 149 `UDOT` instructions against the iOS device
  slice's 1,086 and 149 — and the CPU-feature probes above exist to dispatch to them. The
  wider i8mm kernels are Android-only, though: 320 `SMMLA` (and 320 each of `UMMLA` and
  `BFMMLA`) in the Android arm64 `.text` against **zero** of all three on every iOS slice, so
  the `hw.optional.arm.FEAT_I8MM` probe in the sysctl list above has nothing behind it there.
  Expect int8 to pay off further on Android than on iOS for the same model.
  [Quantize on the desktop](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html):
  `onnxruntime.quantization` cannot run on device (see below).
- **This build tops out at ai.onnx opset 26 and ir_version 13, and both fail at session
  construction rather than at inference.** Opsets 7 through 26 load; 27 and 28 raise
  `onnxruntime.capi.onnxruntime_pybind11_state.Fail` with *ONNX Runtime only \*guarantees\*
  support for models stamped with official released onnx opset versions … Current official
  support for domain ai.onnx is till opset 26*. `ir_version` 9–13 load; 14 raises from
  `model.cc:193`. Both are easy to trip: `onnx` 1.22.0 already reports
  `onnx.defs.onnx_opset_version() == 27`, so a model exported on a laptop with today's
  defaults will not load here. Export with an explicit
  [`opset_version=17`](https://pytorch.org/docs/stable/onnx.html), or downgrade an existing
  model on the desktop with
  [`onnx.version_converter.convert_version`](https://onnx.ai/onnx/api/version_converter.html),
  and wrap `InferenceSession(...)` in `try/except` — the message names the ceiling. The same
  machinery is in the mobile binaries, and their ONNX schema surface matches the desktop
  wheel's for the newest operators — `RMSNormalization`, `RotaryEmbedding`, `TensorScatter`,
  `Attention` and `Swish` are each present exactly once in the Android, iOS and macOS
  binaries alike.
- **The `onnx` package is not published for mobile**, and neither is `ml_dtypes`; both return
  *Not Found* from pypi.flet.dev. That takes the wheel's own model-preparation subpackages out
  of play. With `onnx` blocked, `import onnxruntime.quantization` and
  `import onnxruntime.backend` both raise `ModuleNotFoundError: No module named 'onnx'`;
  `onnxruntime.transformers` and `onnxruntime.tools` import at package level and fail one
  submodule deeper. Prepare models on a laptop. What still works on device without `onnx` is
  everything inference needs, including
  handing `InferenceSession` a `ModelProto` you serialised yourself — the example builds one
  in about sixty lines of protobuf wire format and agrees with numpy to around 4e-09.
- **`onnxruntime.datasets.get_example(...)` will not work on Android.** It joins a name onto
  `os.path.dirname(__file__)` and calls `os.path.exists` — a filesystem read that Flet's zipped
  site-packages cannot serve, so it raises `FileNotFoundError` even though the three example
  models are in every wheel. `extract_packages = ["onnxruntime"]` would fix it at the cost of
  putting the whole 26 MB on disk; shipping your own model, or the bytes route above, is the
  better answer. (Reasoned from the wheel's source, not from a device run.)
- **About 4.3 MB of the unpacked wheel is Python an inference app never imports.** By
  top-level entry on the Android arm64-v8a slice: `capi` 22.14 MB, `transformers` 2.38 MB,
  `quantization` 0.76 MB, `tools` 0.49 MB, `ThirdPartyNotices.txt` 0.33 MB (shipped twice, in
  the package and in `dist-info/licenses/`), `__init__.py` 0.02 MB, `backend` 13 KB,
  `datasets` 1.4 KB. `import onnxruntime` loads ten modules, and apart from the package root
  every one of them is under `onnxruntime.capi`.
- **Budget memory for the batch, not just the model.** Staged peak RSS on desktop, which is
  indicative only and not device evidence: 16.6 MB baseline → 28.9 after `import numpy` →
  43.2 after `import onnxruntime` → 65.7 after building a 2.6 MB model in Python → 75.3 after
  the session → 118.1 after one inference over 4,096 rows. The last step is the one that
  surprises: activations scale with batch size, and a backgrounded app that asks for too much
  is killed rather than slowed.

## Build notes (maintainers)

`patches/mobile.patch` accounts for its four hunks in its own preamble, including which Termux
changes were deliberately not taken, and `meta.yaml` justifies `excluded_arches`,
`BUILD_SHARED_LIB=OFF` and the `USE_*=OFF` switches inline. What is left is shape and the
bump checklist.

The shape is a PEP 517 shim rather than a native-library chain, and that is the whole design.
Upstream publishes no sdist and its `setup.py` cannot build the extension by itself, so the
patch adds a backend that cmake-configures `./cmake` into the source root before every hook.
`BUILD_SHARED_LIB=OFF` then makes the result a single extension that statically absorbs
protobuf, abseil, the ONNX schema library, flatbuffers, Eigen and pytorch/cpuinfo — verified
in the shipped binaries (`N6google8protobuf`, `N4absl`, `N4onnx`, `flatbuffers`, `N5Eigen`,
`cpuinfo` all present; 322 files per wheel and exactly one `.so`). That is what removes the
`libonnxruntime.so` bundling, the rpath work and the preload dance a shared build would need
on Android, and it is why there is no `flet-libonnxruntime` recipe under this one.

A version bump can falsify everything above without the build going red. What to re-verify:

- **The execution-provider set.** The typeinfo scan in [Things to know](#things-to-know) is
  the check, and it needs the desktop wheel of the same version as its control — without one,
  a scan that finds nothing proves nothing. `tests/test_onnxruntime.py::test_providers_and_metadata`
  asserts CPU is *present*, which would not notice CoreML or NNAPI arriving.
- **The opset and ir_version ceilings.** They come from the ONNX submodule that
  `cmake/deps.txt` pins, which moves on most bumps, and they are the two claims most likely to
  break a consumer's existing model file. Nothing in `tests/` covers them; a
  `pytest.raises(Fail)` on an opset one past the ceiling would be cheap to add and would keep
  the number honest.
- **`Requires-Python`.** `>=3.11` today. It is load-bearing for every example
  `pyproject.toml` here, and upstream raises it without ceremony.
- **The ABI list.** `excluded_arches: [armeabi-v7a]` is what makes `target_arch` mandatory in
  [Install](#install); if 32-bit ARM ever builds, that paragraph and the example's
  `pyproject.toml` both stop being necessary.
- **The sizes, the dependency-download totals and the per-entry breakdown.** All measured off
  the cp314 wheels and a `pip download` against pypi.flet.dev. Which protobuf wheel wins the
  resolve is not stable — a pure-Python one wins today — so re-run the download rather than
  adjusting the total by eye.
- **The iOS unstripped symbol table.** 11.9 MB of the 31.9 MB extension, and the only reason
  the iOS slices are ~10 MB larger unpacked than Android's. Stripping it in the iOS lane is
  the obvious size win nobody has taken; until then it is a number to re-measure.
- **The GIL and thread-accounting measurements**, and the KleidiAI factor. All desktop, all
  from a version-matched venv, none re-run on a device. The example's screen is built to be
  the thing you read the device's own numbers off; the desktop table exists to say which way
  round `run` and `InferenceSession` behave, which is a property of the binding rather than of
  the hardware.
