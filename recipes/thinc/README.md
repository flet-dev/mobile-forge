# thinc

[`thinc`](https://thinc.ai/) is a small functional deep-learning library: composable
[layers](https://thinc.ai/docs/api-layers), a [config system](https://thinc.ai/docs/usage-config)
that builds a model out of a text file, and a pluggable
[ops backend](https://thinc.ai/docs/api-backends) that owns every array operation. It is a
low-level building block rather than something you would normally reach for directly, but it
works perfectly well on its own — and on a phone that means defining a network, training it on
data the device just produced, and predicting from it, offline.

## Install

Add thinc to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "thinc",
]

[tool.flet.android]
extract_packages = ["thinc"]
```

The `extract_packages` entry is **not optional on Android**. The first
`from thinc.api import ...` pulls in `thinc/backends/_custom_kernels.py`, which at module level
reads a `_custom_kernels.cu` next to itself through `Path(__file__).parent` — and Flet serves
pure-Python site-packages out of `sitepackages.zip`, which cannot answer a plain filesystem
read. Leave the entry out and the app builds cleanly, then dies on that import with
`NotADirectoryError: [Errno 20] Not a directory` on a path containing `sitepackages.zip`.
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) writes the package
to disk instead, where the read finds the file the way it does on iOS. The value is the
**import** name, and it has to be in *your* `pyproject.toml` — the copy in this recipe's
`meta.yaml` is read only by mobile-forge's own on-device test app.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`tiny-net`](examples/tiny-net) — resolves a config file into a model, trains it on device,
  and reports the ops backend that ran it.

## Usage in a Flet app

Define a model, train it, predict, and put the answer in a control:

```python
import flet as ft
import numpy
from thinc.api import Adam, Relu, Softmax, chain

model = chain(Relu(nO=32, dropout=0.1), Softmax(nO=3))
optimizer = Adam(0.01)
model.initialize(X=train_x, Y=train_y)

for batch_x, batch_y in model.ops.multibatch(32, train_x, train_y, shuffle=True):
    guesses, backprop = model.begin_update(batch_x)
    backprop((guesses - batch_y) / len(batch_y))
    model.finish_update(optimizer)

scores = model.predict(numpy.asarray([[0.4, 0.1]], dtype="float32"))
caption = ft.Text(f"class {int(scores.argmax())}")
```

Model inputs and outputs are `float32` arrays.

### Storage

A trained model is small. [`model.to_disk(path)`](https://thinc.ai/docs/api-model#to_disk)
writes msgpack — a 2 → 64 → 3 network measured 2075 bytes — so put it in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which is app-private, backed up and never auto-deleted, and reload it on the next launch
instead of retraining:

```python
import os

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "model.bin")
if os.path.exists(path):
    model.from_disk(path)
else:
    model.to_disk(path)
```

[`from_disk`](https://thinc.ai/docs/api-model#from_disk) loads into a model that already exists,
so whatever built the model the first time has to run again before the load — though not a
second `initialize`, because the file carries the layer dimensions with the weights. A mismatch
is caught rather than absorbed: reading a 64-unit file into an 8-unit model raises
`ValueError: Attempt to change dimension 'nO' for model 'relu>>dropout' from 8 to 64`, and
loading into different layers raises
`ValueError: Cannot deserialize model: mismatched structure`. Keep the config that produced a
saved model next to it.

**A config file belongs in assets, not in your package.** Put the `.cfg` in the
[assets directory](https://flet.dev/docs/cookbook/assets) and resolve it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir):

```python
from thinc.api import Config, registry

assets = os.getenv("FLET_ASSETS_DIR", "assets")
config = Config().from_disk(os.path.join(assets, "model.cfg"))
model = registry.resolve(config)["model"]
```

[`Config().from_disk`](https://thinc.ai/docs/api-config#config-from_disk) is an ordinary file
read, so the same `.cfg` shipped inside a Python package fails on Android exactly the way the
missing `extract_packages` entry does; assets are real files on both platforms. Use
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for a checkpoint you can afford to lose and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch.

### Threading

Training is CPU-bound and blocks whatever thread it runs on, so put it in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch
exceptions inside the worker, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

Backend selection is per-thread and does not follow you there:
[`get_current_ops()`](https://thinc.ai/docs/api-backends#get_current_ops) reads a `ContextVar`
and a thread starts with a fresh context, so a worker builds its own `Ops` object and a
[`set_current_ops`](https://thinc.ai/docs/api-backends#set_current_ops) call made on the UI
thread is invisible in it. A `Model` is unaffected — it keeps the ops it was built with in
`model.ops` wherever it runs — so training or predicting in a worker needs no re-selection.

What is not safe is sharing one model between concurrent workers.
[`begin_update`](https://thinc.ai/docs/api-model#begin_update) and
[`finish_update`](https://thinc.ai/docs/api-model#finish_update) write parameters and gradients
into the model object, and `run_thread` uses a pool, so two quick taps can overlap. Train one
model at a time, and treat `predict` on a model no one is training as the only concurrent call.

### The ops backend

thinc routes every array operation through an [`Ops`](https://thinc.ai/docs/api-backends#ops)
object chosen at first use. On both platforms that is `NumpyOps` — print it rather than trust
this page:

```python
from thinc.api import get_current_ops

ops = get_current_ops()
print(type(ops).__name__, ops.name, ops.device_type, ops.xp.__name__, ops.use_blis)
```

`NumpyOps` is the BLIS-backed backend: with `use_blis` on, which is the default, a `float32`
[`ops.gemm`](https://thinc.ai/docs/api-backends#gemm) leaves NumPy entirely and calls
`blis.py.gemm` in the `blis` wheel's own extension — not thinc's `cblas`, which is a second
route to the same library, for Cython code that runs without the GIL. Which of the two
multiplies faster is worth measuring rather than assuming, and neither side is the one your
laptop runs: the mobile NumPy wheel reports `"blas": "none"` and `"lapack": "none"` in
`numpy.__config__`, and the mobile BLIS is compiled with BLIS's portable C reference kernels
rather than any arm64 micro-kernel. The `tiny-net` example times both on the device.

The GPU backends cannot apply: `CupyOps` needs CUDA hardware, `MPSOps` needs PyTorch with
Metal. [`prefer_gpu()`](https://thinc.ai/docs/api-util#prefer_gpu) is safe to leave in shared
code — it returns `False` and changes nothing — while
[`require_gpu()`](https://thinc.ai/docs/api-util#require_gpu) raises
`ValueError: Cannot use GPU, CuPy is not installed` on both Android and iOS. That message is
not a hint to install CuPy; it is the branch thinc takes whenever `platform.system()` is not
`"Darwin"`, which on a phone it never is.

### App size

Expect approximately 0.67–0.82 MB of compressed wheel and 1.7–2.6 MB unpacked per
architecture, across six extension modules. Upstream's own test suite is 0.24 MB of that and is
the one part worth naming yourself:

```toml
[tool.flet.cleanup]
package_files = ["thinc/tests"]
```

Read those as near what lands on the device rather than exactly it:
[`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup) is on by default
and replaces the remaining `.py` files with `.pyc`. On Android, use an app bundle, split APKs,
or narrow [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
when the application does not need every ABI. These figures describe the package payload, not
the amount added to the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's wheel of the same version and the same API, but the numbers
underneath it are different: desktop NumPy is linked against a tuned BLAS, so NumPy's own matmul
beats `ops.gemm` there by a wide margin — 0.02 ms against 0.95 ms for a 256×256 `float32`
product on an Apple-silicon Mac. On mobile NumPy has no BLAS to fall back on, so that is not the
same comparison. Treat a timing taken on your development machine as a shape, not a figure.

Importing the library is itself not free: `import thinc.api` measured 0.10 s on a warm desktop
cache, of which NumPy is about 0.03 s. Against an interpreter with no cached bytecode at all it
took 4.2 s — mobile never pays that, because `compile.packages` ships `.pyc`, but do the import
once and off the first frame if the first frame matters.

## Things to know

- **`ops.gemm` is `float32` only, and says so loudly.** `float64` arrays raise
  `ValueError: BLIS gemm requires float32 arrays`, naming both dtypes and suggesting
  `array.astype('float32')`. `NumpyOps(use_blis=False)` accepts them by delegating to NumPy's
  own matmul, at the cost of the thing BLIS is there for.

- **Selecting a backend that cannot work does not raise.** `get_ops("cupy")` hands back a
  `CupyOps` instance on a phone, and
  [`use_ops("cupy")`](https://thinc.ai/docs/api-backends#use_ops) installs it for a block — that
  one is a context manager, not a factory, so outside a `with` it does nothing at all. The
  failure arrives from the first operation, as `ValueError: Encountered a numpy array when
  processing with cupy`, which reads like a data bug rather than a missing GPU. `use_ops("mps")`
  is quieter still: `MPSOps` subclasses `NumpyOps`, so without PyTorch it computes on the CPU
  under another name.

- **A corrupt weights file leaves the cyclic garbage collector switched off.**
  [`Model.from_bytes`](https://thinc.ai/docs/api-model#from_bytes) — and `from_disk` through it
  — unpacks with `srsly.msgpack_loads`, which calls `gc.disable()`, unpacks, then `gc.enable()`
  with no `try`/`finally` in between. A truncated or damaged file raises straight past the
  re-enable and the collector stays off for the rest of the process, silently. Wrap the load
  wherever the file is not certainly intact:

  ```python
  try:
      model.from_disk(path)
  finally:
      gc.enable()
  ```

- **Config mistakes surface at `resolve`, not at build.** A misspelled layer raises
  `RegistryError` and helpfully lists every registered name; a value of the wrong type raises
  `ConfigValidationError`, because
  [`registry.resolve`](https://thinc.ai/docs/api-config#registry-resolve) validates each
  section against the signature of the function it names. Both happen at runtime on the device,
  so a config shipped as an asset deserves a resolve on a desktop run before it ships.

## Build notes (maintainers)

### Recipe shape

An ordinary Python-package recipe with one patch: thinc's six Cython extensions are the whole
native surface, and the sibling Cython packages it compiles against are plain build requirements
resolved from the index like any other. They compile as C++, so the Android slices — and only
those — carry `Requires-Dist: flet-libcpp-shared` into the wheel. The patch preamble owns what
it changes and why; `meta.yaml` comments own the individual build settings. The
`extract_packages` list in `meta.yaml` reaches the on-device test app only, which is why the
consumer instruction has to be repeated in every consuming `pyproject.toml` — and why a green
recipe test proves nothing about an app that omits it.

### Upgrade hazards

- **The patch tracks upstream's `setup.py`.** If a release starts putting the build
  environment's site-packages on Cython's `include_path` itself, the patch stops being needed
  rather than silently doing nothing. Check before carrying it forward.
- **The BLIS window is narrow.** thinc 8.3.13 requires `blis>=1.3.0,<1.4.0`, and the whole
  `cblas` extension is a cross-package `cimport` of `blis.cy`. A bump that moves that window
  needs a matching mobile `blis` before it can resolve at all, and the kernel set the consumer
  section above describes is a property of that wheel, not this one.
- **`thinc-apple-ops` would change the backend story.** `get_ops("cpu")` prefers an `apple`
  backend over `numpy` when one is registered. No mobile wheel provides it today, which is why
  the page states `NumpyOps` flatly; if that changes, rewrite the ops section rather than
  amend it.
- Upstream declares `Requires-Python <3.15,>=3.10`, so a newer interpreter needs a release
  first.

### Re-verification checklist

- **Extensions per slice:** six `.so` files — `backends/numpy_ops`, `backends/cblas`,
  `backends/linalg`, `layers/premap_ids`, `layers/sparselinear`, `extra/search` — with the right
  ABI tag, `MH_DYLIB` on iOS, and `libc++_shared.so` in `DT_NEEDED` on Android for all of them.
- **The `__file__` read:** confirm `thinc/backends/_custom_kernels.py` still reads its `.cu`
  neighbour at module level and is still reached by importing `thinc.api`. That single line is
  the entire justification for the `extract_packages` instruction.
- **Backend claims:** `use_blis`, the `float32` gemm error text and the `require_gpu()` message
  are quoted verbatim above; re-read them from the built wheel. So is the BLAS state either
  side of the comparison — generic reference kernels in the mobile BLIS, no BLAS at all in the
  mobile NumPy.
- **Sizes:** re-measure compressed and unpacked from the wheels, and the `thinc/tests` figure
  with them.

### Coverage gaps

The device tests cover importing the package, a `NumpyOps.gemm` and a `Linear` forward pass —
but note what each reaches. A bare `import thinc` loads **no** extension module and never
touches `_custom_kernels.cu`; it is the `from thinc.api import ...` in the other two that
imports `numpy_ops`, `cblas`, `linalg`, `premap_ids` and `sparselinear`, and with them the
data-file read. Only `numpy_ops` then has code run in it — the `Linear` test reaches the same
`gemm` as the gemm test, which hands the multiply to the `blis` extension — and `extra/search`
is loaded by nothing at all. The config system, `to_disk`/`from_disk`, a full training loop and
every claim in **Things to know** rest on desktop measurement and on the example app.
