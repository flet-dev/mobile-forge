# xgboost

[XGBoost](https://xgboost.readthedocs.io/en/stable/) is gradient-boosted decision trees — the
model family that still wins most problems shaped like a spreadsheet: rows of measurements,
one label to predict. On a phone its job is usually the second half of a workflow that starts
on a laptop: train there, save the model, and ship the file inside the app so predictions run
on the device, offline, in milliseconds.

## Install

```toml
dependencies = [
    "flet",
    "xgboost",
    "joblib",
]

[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

`joblib` is only there to read `.joblib` files; leave it out if you load models some other
way.

**The [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
line is required.** XGBoost assumes a 64-bit `size_t` and does not compile for 32-bit ARM, so
no `armeabi-v7a` wheel exists, and a default `flet build apk` targets that ABI too and fails
with `No matching distribution found for xgboost`. Spell the ABI names out in full: short
forms such as `arm64` or `x64` are not Android ABI names, and Flet rejects them.

**If scikit-learn is in the app at all** — because your file holds a `Pipeline`, a scaler or
an encoder, or because another dependency pulls it in — Android also needs it
[extracted](https://flet.dev/docs/publish/android/#extract-packages):

```toml
[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
extract_packages = ["sklearn"]
```

`import xgboost` imports scikit-learn whenever it is installed, and scikit-learn reads a file
beside its own code through a plain path, which Flet's zipped Android site-packages cannot
serve. Without the entry, `import xgboost` itself fails with a `NotADirectoryError` ending in
`sklearn/utils/_repr_html/estimator.css`.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`iris-explainer`](examples/iris-explainer) — loads a desktop-trained `.joblib`
  classifier, predicts from four sliders, and shows which measurements drove the answer.

## Usage in a Flet app

Put the model file in your app's `src/assets/`, load it from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
on a worker thread — the first load also imports xgboost and scipy — and show the answer:

```python
import os

import flet as ft
import joblib

result = ft.Text()

def load_and_predict():
    path = os.path.join(os.getenv("FLET_ASSETS_DIR"), "model.joblib")
    model = joblib.load(path)
    proba = model.predict_proba([[5.8, 3.0, 4.4, 1.3]])[0]
    result.value = f"class {proba.argmax()} · {proba.max():.0%}"
    page.update()          # a background thread needs this explicitly

page.add(result)
page.run_thread(load_and_predict)
```

A bare [`XGBClassifier`](https://xgboost.readthedocs.io/en/stable/python/python_api.html#xgboost.XGBClassifier)
or `XGBRegressor` unpickles and predicts without scikit-learn installed, even though
scikit-learn was needed to train it. Without it, use only `predict`, `predict_proba`, `apply`
and `get_booster()`: `classes_` raises `ModuleNotFoundError: No module named 'sklearn'`,
and `get_params()`/`set_params()`, `fit`, `score` and the wrapper's own `save_model` all
fail. Classes are always encoded `0..n-1`, so keep your own list of names in the app.

[`pred_contribs=True`](https://xgboost.readthedocs.io/en/stable/python/python_api.html#xgboost.Booster.predict)
is XGBoost's built-in TreeSHAP — one contribution per feature, plus a bias, which together
sum to the model's raw score. It is the way to explain a prediction on device: the `shap`
package depends on numba, a JIT compiler with no build for Flet's mobile targets.

```python
import xgboost as xgb

shap = model.get_booster().predict(xgb.DMatrix(row), pred_contribs=True)
```

For a multi-class model the result has one block per class, `shap[row, class, feature]`.

### Storage

Assets ship inside the app and are replaced by every update. A model the app downloads or
retrains belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
instead; save it there with `model.get_booster().save_model(path)`, which needs no
scikit-learn.

### Threading

**On Android XGBoost uses every core by default; iOS uses one.** The Android wheel is built
with OpenMP and links the NDK's runtime. iOS has no OpenMP runtime, so that build is
single-threaded — same results, different wall clock. A pickled model keeps the thread
count it was trained with, so a model trained with `n_jobs=1` stays on one core on the phone
too. Override it on the booster, which works with or without scikit-learn (`0` means every
core):

```python
model.get_booster().set_param({"nthread": 2})
```

Predicting a few rows with a small model takes milliseconds and can stay in an event handler.
Loading, training and large batches belong in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), ending
with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).
XGBoost is called through `ctypes`, which releases the GIL for each native call, so the UI
keeps running meanwhile.

### Model files

A `.joblib` file is a pickle, and loading a pickle runs code. Load only files your own
build produced, never one fetched over the network.

A pickle is also tied to the versions that wrote it. Files from older XGBoost releases
[still load](https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html#loading-pickled-files-or-rds-files)
— a 2.1 model predicts identically here, after a warning — but nothing promises the reverse.
scikit-learn objects are stricter: from another scikit-learn version they unpickle with an
`InconsistentVersionWarning` and can still fail when called (a 1.7 `SimpleImputer` raises
`AttributeError` inside `predict` on 1.9). So train with the versions the app gets — the
XGBoost you pin, and, if the file holds scikit-learn objects, the scikit-learn release
pypi.flet.dev carries, pinned on the desktop as the example's `train` group does.

For a model that has to outlive version bumps, save it in XGBoost's
[own format](https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html#a-note-on-backward-compatibility-of-models-and-memory-snapshots)
instead and load it into a
[`Booster`](https://xgboost.readthedocs.io/en/stable/python/python_api.html#xgboost.Booster),
which needs no scikit-learn:

```python
model.save_model("model.ubj")                 # on the desktop

booster = xgb.Booster(model_file=path)        # in the app
scores = booster.predict(xgb.DMatrix(rows))
```

For a multi-class model `scores` matches `predict_proba`; for a binary one it is a 1-D array
of the positive class's probability. `XGBClassifier().load_model(path)` reads the same file,
but constructing an `XGBClassifier` requires scikit-learn.

### App size

XGBoost itself is about 2.5 MB compressed and 8–9 MB unpacked per architecture; most of
what it brings is [scipy](https://scipy.org), which `import xgboost` loads unconditionally.
Budget roughly 40 MB compressed and 115–135 MB unpacked per architecture for xgboost, scipy
and numpy together, and 8 MB / 28–32 MB more for scikit-learn if your model needs it. An APK
carries close to the unpacked figure, because Flet stores Python packages and native
libraries uncompressed so it can memory-map them; an IPA, or a Play Store download built
from an app bundle, comes closer to the compressed one.

About 24 MB of the unpacked total is scipy's and numpy's own test suites, which your app
never imports. Flet's cleanup does not remove test suites by default, so
[name them](https://flet.dev/docs/cli/flet-build/#--cleanup-package-files):

```toml
[tool.flet.cleanup]
package_files = ["scipy/**/tests", "numpy/tests", "numpy/*/tests"]
```

On Android, also use an app bundle or split APKs.

### Other considerations

A desktop `flet run` uses PyPI's XGBoost wheel, which is multi-threaded on every desktop
platform. A timing measured at your desk transfers poorly to Android and not at all to iOS,
so measure on a device or emulator/simulator.

## Things to know

- **No GPU.** Both builds are CPU-only. A model saved with `device="cuda"` loads and
  predicts on the CPU.

## Build notes (maintainers)

### Recipe shape

scikit-build-core + CMake, the [`soxr`](../soxr) / [`duckdb`](../duckdb) lanes: XGBoost 3.4
replaced the custom hatchling backend of earlier releases, so `CMAKE_ARGS` is honoured.
`libxgboost` is a plain shared library loaded through `ctypes`, not an extension module, and
the patch is about where each platform's packager puts it; its preamble has the detail.

An earlier draft of this recipe targeted 3.3.0 and had to patch the hatchling backend in
three places — to accept CMake arguments at all, to stop it naming the library after the
build host, and to stop it silently retrying without OpenMP when the cross configure failed.
None of that survives in 3.4.

### Upgrade hazards

- **The library name is decided in two places that must agree**: `_XGB_LIBNAME` in the root
  `CMakeLists.txt` and the candidate list in `xgboost/libpath.py`.
- **The sdist's `pyproject.toml` is generated per variant** (`pypi_variants.py`). Check its
  `dependencies` on every bump: the variant published as the sdist has no `nvidia-nccl-cu*`
  dependency (cu13 as of 3.4, cu12 before), but the wheel variants carry one.
- **Any new `__file__`-relative read breaks `import xgboost` on Android**, where Flet ships
  site-packages as a zip. `grep -rn __file__ xgboost/` on the new sdist; today only
  `libpath.py` and `_c_api._py_version()` matter, and both are patched. A desktop run will not
  show it: put the package in a zip on `sys.path` and import it.

### Re-verification checklist

- Each wheel carries `xgboost/lib/libxgboost.so` and nothing versioned beside it.
- Android: `DT_NEEDED` limited to bionic, `libc++_shared.so` and `libomp.so`; `SONAME`
  `libxgboost.so`; every `LOAD` segment aligned `0x4000`.
- iOS: `otool -L` shows no `libomp`; `LC_BUILD_VERSION` platform 2 on device, 7 on the
  simulators.
- METADATA: `Requires-Dist` numpy and scipy; `flet-libcpp-shared` and `flet-libomp` on
  Android only.
- Sizes: re-measure in decimal MB from the wheels (sum of `zipfile` entry sizes, not `du`),
  including scipy, numpy and scikit-learn as pypi.flet.dev serves them; and confirm
  `import xgboost` still pulls in scipy and still imports scikit-learn when it is present.
- In a venv without scikit-learn, re-check the list in Usage: what works on an unpickled
  model and what fails, and how.
- `tests/iris_classifier.joblib` was written by the version in the test file's header
  comment. It keeps working across bumps; regenerate it (the recipe is in that comment)
  when the version gap starts producing warnings.

### Coverage gaps

The device tests cover native training and prediction, UBJSON round-trips, TreeSHAP, a
desktop-trained `.joblib` classifier with a booster thread cap, and the OpenMP build flag.
They do not cover the scikit-learn wrapper's own `fit`, a scikit-learn `Pipeline`,
categorical features, external memory (`DataIter`), or any multi-threaded speed-up — the
OpenMP test checks the build flag, not that work spreads across cores.
