# onnxruntime

[`onnxruntime`](https://onnxruntime.ai/docs/) runs a trained neural network that somebody
else exported. You hand it an `.onnx` file — from PyTorch, TensorFlow, scikit-learn,
Hugging Face, anything with an ONNX exporter — and it gives you an
[`InferenceSession`](https://onnxruntime.ai/docs/api/python/api_summary.html) that turns
numpy arrays into numpy arrays. On a phone it is the shortest path from *"we have a model"*
to *"the app answers offline"*: classification, embeddings, keyword spotting, small language
models. Training stays on a laptop, only the forward pass ships, and nothing in the inference
path reaches the network. Embeddings are the common case: [`faiss-cpu`](../faiss-cpu) searches
the vectors a model here produces, and [`safetensors`](../safetensors) memory-maps a large side
table instead of holding it resident.

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
32-bit one, after the other two have already resolved, with `ERROR: Could not find a version
that satisfies the requirement onnxruntime (from versions: none)`. Spell the ABI names out in
full; `arm64`/`x64` are the macOS spellings and Flet rejects them. Dropping 32-bit ARM costs
nothing else — 64-bit has been mandatory for Play Store uploads since 2019.

**`Requires-Python` is `>=3.11`, which is higher than the `>=3.10` `flet create` writes.**
It only bites if you pin onnxruntime with `==`, and then it bites hard: uv resolves for every
version in the declared range, so the 3.10 split becomes unsatisfiable and the build stops
with *your project's requirements are unsatisfiable*. Raise `requires-python` to `>=3.11`
alongside any pin, and check it the way a consumer meets it — copy the `pyproject.toml` alone
into an empty directory and run `uv lock` there.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`hand-built-mlp`](examples/hand-built-mlp) — an ONNX graph written in the app, run on
  device and checked against numpy.

## Usage in a Flet app

Build the session once and keep it; `run` is the call you make per tap:

```python
import flet as ft
import numpy as np
import onnxruntime as ort

options = ort.SessionOptions()
options.intra_op_num_threads = 2
SESSION = ort.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])

answer = ft.Text()

def classify(x: np.ndarray):
    (y,) = SESSION.run(None, {"x": x})
    answer.value = f"class {int(y.argmax(axis=-1)[0])} at {float(y.max()):.1%}"
    page.update()
```

`None` asks for every output. The input dict is keyed by the graph's own input names —
`[i.name for i in SESSION.get_inputs()]`, whatever the exporter wrote; `"x"` is only this
model's. Pass `providers` explicitly: there is exactly one to pass here.

### Storage

A model is an ordinary file, and `InferenceSession` takes either a path or the bytes
themselves. Which one you want depends on where the model comes from.

**Shipped with the app** — put the `.onnx` in `src/assets/` and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).
Assets are read-only and replaced on every app update, which is what you want for a model
that ships with the build:

```python
path = os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "model.onnx")
session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
```

**Downloaded or generated on device** — write it to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups. Never keep a
model you cannot cheaply re-fetch in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

**No file at all** is also supported: `ort.InferenceSession(model_bytes, …)` takes a serialised
`ModelProto` directly, so a model held in a database column, a preferences blob or built at
runtime never has to touch the filesystem — the example does exactly that. Inference itself
writes nothing, except that `SessionOptions.enable_profiling`, if you turn it on, drops a JSON
trace in the process working directory.

### Threading

**`sess.run(...)` releases the GIL for the whole computation; `InferenceSession(...)` holds
it.** That is the opposite arrangement from the one most people assume, and it decides where a
worker thread is worth having. Measured on desktop with a canary thread timing its own stalls:
eight `sess.run` calls over 32,768 rows took 657 ms and stalled the canary 0.9 ms, where
session construction stalls it for nearly the whole call — 15.5 of 15.6 ms for a 30 MB model,
95.8 of 124.0 ms for a 254 MB one.

So inference in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
genuinely keeps the UI responsive and session construction does not — though at 2 ms for a
2.6 MB model and 11 ms for a 34 MB one, it only matters for a large model on a slow device.
Load the model once and keep the session; do not build one per tap.

Two standing Flet caveats apply either way: `run_thread` never retrieves the worker's future,
so an exception raised inside one surfaces nowhere at all — wrap the body in
`try/except Exception` — and auto-update does not reach background threads, so end the handler
with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**Set `intra_op_num_threads` yourself.** onnxruntime creates exactly
`intra_op_num_threads - 1` extra OS threads and runs the remaining share on the calling thread
(checked against `ps -M` at 1, 2, 3, 4 and 8). Left at its default of `0` it resolved to half
the logical cores; on a big.LITTLE phone that reaches the little cores as well, and a
backgrounded app which grabs them is throttled or killed rather than merely slowed. Start at
`2`, or `max(1, os.cpu_count() // 4)`. You cannot ask a session what it settled on —
`sess.get_session_options().intra_op_num_threads` reads back `0` for a default session while
`ps -M` shows the extra threads are live — so set it explicitly, and time the same batch at two
settings if you want the answer for a given handset. That is what the example puts on screen.

`inter_op_num_threads` applies only when `execution_mode` is `ORT_PARALLEL`, and the default is
`ORT_SEQUENTIAL`, so on a default session it does nothing. There is no OpenMP in either build —
no `GOMP_`, `omp_get_max_threads` or `libomp` strings in either binary — so
`intra_op_num_threads` is the one knob, and it means the same thing on both platforms.

### Model files

**This build tops out at ai.onnx opset 26 and `ir_version` 13, and both fail at session
construction rather than at inference.** Opsets 7 through 26 load; 27 and 28 raise
`onnxruntime.capi.onnxruntime_pybind11_state.Fail` with *Current official support for domain
ai.onnx is till opset 26*. `ir_version` 9–13 load, 14 raises. Both are easy to trip — `onnx`
1.22.0 already reports `onnx.defs.onnx_opset_version() == 27`, so a model exported on a laptop
with today's defaults will not load here. Export with an explicit
[`opset_version=17`](https://pytorch.org/docs/stable/onnx.html), or downgrade an existing model
on the desktop with
[`onnx.version_converter.convert_version`](https://onnx.ai/onnx/api/version_converter.html),
and wrap `InferenceSession(...)` in `try/except` — the message names the ceiling.

**Prepare models on a laptop, not on the device.** The `onnx` package is not published for
mobile, and neither is `ml_dtypes`; both return *Not Found* from pypi.flet.dev. That takes the
wheel's own model-preparation subpackages out of play: `import onnxruntime.quantization` and
`import onnxruntime.backend` raise `ModuleNotFoundError: No module named 'onnx'`, and
`onnxruntime.transformers` and `onnxruntime.tools` import at package level and fail one
submodule deeper. Everything inference needs still works without `onnx`, including handing
`InferenceSession` a `ModelProto` you serialised yourself — the example builds one in about
sixty lines of protobuf wire format and agrees with numpy to around 4e-09.

**`onnxruntime.datasets.get_example(...)` raises `FileNotFoundError` on Android.** It joins a
name onto `os.path.dirname(__file__)` and calls `os.path.exists`, a filesystem read that
Android's zipped site-packages cannot serve, even though the three example models are in every
wheel. On iOS site-packages stays a real directory, so the same call opens the file. Shipping
your own model, or the bytes route above, is the better answer on both platforms. (Reasoned
from the wheel's source and Flet's packaging, not from a device run.)

### App size

Expect approximately 8–9 MB of compressed wheel and 26–30 MB unpacked per Android ABI, and
9–10 MB compressed and 36–40 MB unpacked per iOS slice. Installing onnxruntime also brings
numpy, which is most of the remaining payload — about 7 MB compressed on Android arm64.

The extension is one statically linked binary, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing to
remove from it, and about 4.3 MB of the unpacked package is model-preparation Python an
inference app never imports with no supported way to drop it. The levers that work are
packaging ones: an Android app bundle or split APKs, and keeping `target_arch` to the ABIs you
actually ship — which [Install](#install) already forces you to write out. These figures
describe the package payload, not the exact amount added to the final APK or IPA; packaging
and compression determine that.

### Other considerations

A desktop `flet run` uses PyPI's wheel, and the Python API is identical — but it is a different
build, in two ways that mislead anyone who benchmarks or feature-tests there.

It has execution providers the mobile wheels do not: `get_available_providers()` on the PyPI
macOS wheel returns CoreML and Azure alongside CPU, where a phone returns CPU alone. And it has
ARM matrix kernels the mobile builds lack — the macOS wheel carries `ArmKleidiAI` GEMM kernels
and SME instructions that neither mobile binary has. Measured on the example's model on an M4
at `intra_op_num_threads=1` by toggling `mlas.disable_kleidiai`, that is worth 6× to 9× from
batch 64 upwards (9.1 ms against 57.2 ms at batch 4096); only at batch 1, where the whole call
is tens of microseconds, does it fall to 2.5×.

A latency budget taken on your Mac therefore does not transfer. Time the model on a device
before committing to it.

## Things to know

- **CPU only, on both platforms. There is no NNAPI, no CoreML and no XNNPACK.**
  `get_available_providers()` on device is `['CPUExecutionProvider']` and everything runs
  through MLAS. Verified in the binaries rather than from the build flags — the typeinfo scan
  under [Build notes](#re-verification-checklist) finds no other provider in any of the five
  mobile slices, and finds two more in the desktop wheel that is its control. Corroborating:
  zero `xnn_` symbols, zero `libneuralnetworks` strings, no `CoreML.framework` in `otool -L`.
- **Asking for a provider that is not there is a warning, not an error.**
  `providers=["NnapiExecutionProvider", "CPUExecutionProvider"]` gives `UserWarning: Specified
  provider 'NnapiExecutionProvider' is not in available provider names.` and silently continues
  on CPU; an unknown name prints an `EP Error … Falling back to ['CPUExecutionProvider'] and
  retrying` banner and carries on. All twenty-odd provider names are present as strings in the
  mobile binaries — that is the static table behind `get_all_providers()` and says nothing
  about what is compiled in. Print `sess.get_providers()` rather than assuming.
- **`import onnxruntime` can print `UserWarning: Unsupported platform (…)`, and it means
  nothing.** `check_distro_info()` runs unconditionally at import and warns for any
  `platform.system().lower()` outside `{windows, linux, darwin, aix}`. iOS reports `"iOS"`, so
  it always fires there; on Android it depends on the Python you built against, because CPython
  only taught `platform` about Android in 3.13 — a 3.13 or 3.14 app reports `"Android"` and
  warns, a 3.12 one reports `"Linux"` and stays quiet. The import completes and inference works
  either way (monkeypatching `platform.system()` before import: `'iOS'` and `'Android'` warn,
  `'Linux'` and `'Darwin'` do not, all four import). Silence it with
  `warnings.filterwarnings("ignore", message="Unsupported platform")` before the import.
- **Quantize to int8 rather than hoping for an NPU.** MLAS's dot-product integer kernels are
  compiled in on both platforms — the Android arm64 `.text` disassembles to 1,068 `SDOT`
  instructions against the iOS device slice's 1,086. The wider i8mm kernels are Android-only,
  though: 320 `SMMLA` (and 320 each of `UMMLA` and `BFMMLA`) on Android against **zero** of all
  three on every iOS slice. Expect int8 to pay off further on Android than on iOS for the same
  model, and
  [quantize on the desktop](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)
  — `onnxruntime.quantization` cannot run on device.
- **Budget memory for the batch, not just the model.** Staged peak RSS on desktop, indicative
  only and not device evidence: 16.6 MB baseline → 28.9 after `import numpy` → 43.2 after
  `import onnxruntime` → 65.7 after building a 2.6 MB model in Python → 75.3 after the session
  → 118.1 after one inference over 4,096 rows. The last step is the one that surprises:
  activations scale with batch size, and a backgrounded app that asks for too much is killed
  rather than slowed.

## Build notes (maintainers)

`patches/mobile.patch` accounts for its four hunks in its own preamble, including which Termux
changes were deliberately not taken, and `meta.yaml` justifies `excluded_arches`,
`BUILD_SHARED_LIB=OFF` and the `USE_*=OFF` switches inline. What is left is shape, hazards, and
what a green run does not prove.

### Recipe shape

A PEP 517 shim rather than a native-library chain, and that is the whole design. Upstream
publishes no sdist and its `setup.py` cannot build the extension by itself, so the patch adds a
backend that cmake-configures `./cmake` into the source root before every hook.
`BUILD_SHARED_LIB=OFF` then makes the result a single extension that statically absorbs
protobuf, abseil, the ONNX schema library, flatbuffers, Eigen and pytorch/cpuinfo — verified in
the shipped binaries (`N6google8protobuf`, `N4absl`, `N4onnx`, `flatbuffers`, `N5Eigen`,
`cpuinfo` all present; 322 files per wheel and exactly one `.so`). That removes the
`libonnxruntime.so` bundling, the rpath work and the preload dance a shared build needs on
Android, and it is why there is no `flet-libonnxruntime` recipe under this one.

Two consequences before touching either lane. On Android the extension links `libdl.so`,
`libpython3.xx.so`, `liblog.so`, `libm.so`, `libc++_shared.so` and `libc.so` with `RUNPATH
$ORIGIN`; that fifth entry is why the Android wheels carry `Requires-Dist: flet-libcpp-shared
(>=27.2.12479018)` and the iOS ones do not. On iOS it links only the OS and resolves Python
through dyld rather than a link-time dependency — 182 of its 628 undefined symbols are CPython
API — and all three slices are already `MH_DYLIB` marked `NOUNDEFS` (`otool -hv`), so forge's
`MH_BUNDLE`-to-`MH_DYLIB` conversion in `fix_wheel` never engages for this recipe.

### Upgrade hazards

- **The opset and `ir_version` ceilings** come from the ONNX submodule that `cmake/deps.txt`
  pins, which moves on most bumps. They are the claims here most likely to break a consumer's
  existing model file, and the build stays green when they change.
- **`Requires-Python`** is `>=3.11` today. It is load-bearing for the example's
  `pyproject.toml` and for the [Install](#install) warning, and upstream raises it without
  ceremony.
- **`excluded_arches: [armeabi-v7a]`** is what makes `target_arch` mandatory in
  [Install](#install). If 32-bit ARM ever builds, that paragraph and the example's
  `pyproject.toml` entry both stop being necessary.
- **The iOS extension ships unstripped**, which is the whole reason the iOS slices unpack about
  10 MB larger than Android's — not extra code. `size -m` on the device slice puts `__LINKEDIT`
  at 12,075,008 of 31,965,184 bytes, `nm -a` counts 101,667 symbols in a file that exports
  exactly one (`PyInit_onnxruntime_pybind11_state`), and `strip -S -x` on a copy takes it from
  31,919,480 to 20,006,056 bytes. Stripping in the iOS lane is the size win nobody has taken;
  until then [App size](#app-size) depends on it staying this way.
- **`LC_BUILD_VERSION` is not uniform across the iOS slices** despite the `ios_13_0` in every
  filename: device and x86_64 simulator say 13.0, the arm64 simulator says 14.0. It bites
  nothing Flet supports; it is here because a slice comparison that opens one binary and
  generalises will get it wrong.

### Re-verification checklist

- **The execution-provider set.** The check is a scan of all five mobile slices for C++
  typeinfo names of the form `N11onnxruntime<n><Name>ExecutionProviderE`, which today yields
  only `IExecutionProvider`, `CPUExecutionProvider` and `PluginExecutionProvider`. It needs the
  desktop wheel of the same version as its control — without one a scan that finds nothing
  proves nothing; on macOS the same scan adds `CoreMLExecutionProvider` and
  `AzureExecutionProvider`.
- **The opset and `ir_version` ceilings**, by loading a model one past each.
- **The sizes**, measured off the cp314 wheels:

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 8.40 MB | 26.5 MB | 22.1 MB |
  | Android x86_64 | 9.25 MB | 29.4 MB | 24.9 MB |
  | iOS arm64 (device) | 9.07 MB | 36.4 MB | 31.9 MB |
  | iOS arm64 (simulator) | 9.39 MB | 36.6 MB | 32.2 MB |
  | iOS x86_64 (simulator) | 10.40 MB | 39.9 MB | 35.5 MB |

- **The dependency-download total.** Resolving for Android arm64-v8a on 3.14 downloads six
  wheels totalling 16.0 MB — onnxruntime 8.40, numpy 6.85, `flet-libcpp-shared` 0.41, protobuf
  0.17 (a pure-Python wheel wins the resolve, which is not stable), packaging 0.13, flatbuffers
  0.03. iOS resolves the same set minus `flet-libcpp-shared` and with a slice-dependent
  onnxruntime wheel, so it has no single total; re-run the `pip download` against
  pypi.flet.dev rather than deriving one by eye.
- **The 4.3 MB never-imported figure.** By top-level entry on Android arm64-v8a: `capi`
  22.14 MB, `transformers` 2.38, `quantization` 0.76, `tools` 0.49, `ThirdPartyNotices.txt`
  0.33 (shipped twice, in the package and in `dist-info/licenses/`), `__init__.py` 0.02,
  `backend` 13 KB, `datasets` 1.4 KB. `import onnxruntime` loads ten modules and, apart from
  the package root, every one is under `onnxruntime.capi`.
- **The GIL and thread-accounting measurements**, and the KleidiAI factor. All desktop, all
  from a version-matched venv, none re-run on a device. The example's screen is built to be the
  thing you read the device's own numbers off; the desktop figures exist to say which way round
  `run` and `InferenceSession` behave, which is a property of the binding rather than of the
  hardware.
- **The kernel surface behind the int8 and KleidiAI claims.** `MlasGemmS8S8KernelSDot`,
  `MlasGemmU8X8KernelUdot` and `MlasSymQgemmS8KernelSdot` are the int8 handles in the
  unstripped iOS binary; `SDOT`/`UDOT` and `SMMLA`/`UMMLA`/`BFMMLA` counts are how the stripped
  Android one is asked; and the macOS dylib's 22 `SMSTART`/`SMSTOP` instructions against zero
  on Android are what make SME desktop-only. Dispatch itself reads `/proc/cpuinfo` and per-CPU
  `cpufreq`/`topology` on Android, and `hw.cpufamily`/`hw.optional.arm.FEAT_*` sysctls on iOS.
- **Android 16 KB alignment.** All three `PT_LOAD` segments must stay 16 KB-aligned.

### Coverage gaps

`tests/test_onnxruntime.py` is three functions over one 170-byte `Gemm`/`Add`/`Relu` graph, so
a green mobile run proves the extension imports and executes, and little else.

- **`test_session_options_threads` asserts only `y.shape`**, so a regression that returns wrong
  numbers at `intra_op=2` passes today. It should check the array `test_inference_session`
  already builds.
- **Nothing loads a model from bytes**, which is the route [Storage](#storage) recommends and
  the example uses; both tests construct from a path.
- **Nothing tests the opset or `ir_version` ceilings.** A `pytest.raises(Fail)` one past each
  would be cheap, and would keep the two most bump-fragile numbers on this page honest.
- **`test_providers_and_metadata` asserts CPU is *present*, not that the others are absent**,
  so CoreML or NNAPI arriving would not fail it.
- **Nothing runs at scale or off float32**: no model large enough for session construction to
  cost anything, no int8 graph, no other dtype, no batch big enough to move memory.
- **No threading or memory claim is device-verified.** Every GIL, thread-count, timing and RSS
  figure above is desktop CPython. The example app is the on-device instrument; the test suite
  is not.
