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
way. It installs from PyPI.

**The [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
line is required.** No `armeabi-v7a` wheel exists — XGBoost assumes a 64-bit `size_t` and
does not compile for 32-bit ARM — so a default `flet build apk`, which targets all three
ABIs, fails at dependency resolution for that one. Spell the ABI names out in full; `arm64`
and `x64` are macOS spellings and Flet rejects them here.

If the file you load holds anything from scikit-learn — a `Pipeline`, a scaler, an encoder —
add `"scikit-learn"` to the dependencies as well, and on Android extract it to disk:

```toml
[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
extract_packages = ["sklearn"]
```

Without that entry `import sklearn` fails on Android with a `NotADirectoryError` ending in
`sklearn/utils/_repr_html/estimator.css`: Flet ships packages zipped there, and scikit-learn
reads that file through a plain filesystem path.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`iris-explainer`](examples/iris-explainer) — loads a desktop-trained `.joblib`
  classifier, predicts from four sliders, and shows which measurements drove the answer.

## Usage in a Flet app

Put the model file in your app's `src/assets/`, load it from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir),
and predict:

```python
import os

import joblib

model = joblib.load(os.path.join(os.getenv("FLET_ASSETS_DIR"), "model.joblib"))

proba = model.predict_proba([[5.8, 3.0, 4.4, 1.3]])[0]
result.value = f"class {proba.argmax()} · {proba.max():.0%}"
page.update()
```

A bare `XGBClassifier` or `XGBRegressor` unpickles and predicts without scikit-learn
installed, even though scikit-learn was needed to train it. Two things on it do import
scikit-learn and fail without it: the `classes_` property and `get_params()`. Classes are
always encoded `0..n-1` in XGBoost, so keep your own list of names in the app.

[`pred_contribs=True`](https://xgboost.readthedocs.io/en/stable/python/python_api.html#xgboost.Booster.predict)
is XGBoost's built-in TreeSHAP — one contribution per feature, plus a bias, which together
sum to the model's raw score. It is the way to explain a prediction on device: the `shap`
package depends on numba, a JIT compiler with no build for Flet's mobile targets.

```python
import xgboost as xgb

shap = model.get_booster().predict(xgb.DMatrix(row), pred_contribs=True)
```

For a multi-class model the result has one block per class, `shap[row, class, feature]`.

### Model files

A `.joblib` file is a pickle, and loading a pickle runs code. Load only files your own
build produced, never one fetched over the network.

A pickle is also tied to the versions that wrote it. Files written by older XGBoost releases
still load — a 2.1 model predicts identically here, after an XGBoost warning about loading an
old serialized model — and scikit-learn objects from another scikit-learn version load with
an `InconsistentVersionWarning`. Nothing promises the reverse, a file from a newer XGBoost
than the app's. Train with the XGBoost version your app pins.

For a model that has to outlive version bumps, save it in XGBoost's own format instead,
which is stable across releases, and load it into a `Booster`, which needs no scikit-learn:

```python
model.save_model("model.ubj")                 # on the desktop

booster = xgb.Booster(model_file=path)        # in the app
proba = booster.predict(xgb.DMatrix(rows))
```

`XGBClassifier().load_model(path)` reads the same file, but constructing an `XGBClassifier`
requires scikit-learn.

Assets ship inside the app and are replaced by every update. A model the app downloads or
retrains belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
instead.

### Threading

**Android runs XGBoost on every core; iOS runs it on one.** The Android wheel is built with
OpenMP and links the NDK's runtime. iOS has no OpenMP runtime, so that build is
single-threaded — same results, different wall clock. To leave cores free on Android, set
the thread count on the model's booster, which works with or without scikit-learn:

```python
model.get_booster().set_param({"nthread": 2})
```

`n_jobs` on an `XGBClassifier` means the same thing — threads, not processes, unlike
scikit-learn's `n_jobs` — but changing it on a loaded model goes through `set_params()`,
which needs scikit-learn.

Predicting one row with a small model is fast enough to do in an event handler. Training,
loading, and predicting large batches belong in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), ending
with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) —
a background thread does not get the automatic one. XGBoost is called through `ctypes`,
which releases the GIL for the duration of each native call, so the UI keeps running.

### App size

XGBoost itself is about 2.5 MB compressed and 8–9 MB unpacked per architecture; most of
what it brings is [scipy](https://scipy.org), which `import xgboost` loads unconditionally.
Budget roughly 40 MB compressed and 115–135 MB unpacked per architecture for xgboost, scipy
and numpy together, and 8 MB / 28–32 MB more for scikit-learn if your model needs it.

About 24 MB of that unpacked total is scipy's and numpy's own test suites, which your app
never imports. Flet's cleanup does not remove test suites by default, so name them:

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
- **No 32-bit ARM.** See [Install](#install).
- **`classes_` needs scikit-learn**, even on a model that otherwise works without it. The
  symptom is `ModuleNotFoundError: No module named 'sklearn'` from inside
  `xgboost/sklearn.py`.

## Build notes (maintainers)

### Recipe shape

scikit-build-core + CMake, the [`soxr`](../soxr) / [`duckdb`](../duckdb) lanes. XGBoost 3.4
replaced the custom hatchling backend of earlier releases with scikit-build-core, which is
why `CMAKE_ARGS` is honoured and the patch only touches how the library is named and found,
and how the package reads its own `VERSION` file. The
Python package loads `libxgboost` through `ctypes`, so the library is a plain shared object
rather than an extension module: on Android Flet relocates it into the APK's native library
directory, on iOS serious_python turns it into an embedded framework behind a `.fwork`
pointer. The patch teaches `libpath.py` both.

An earlier recipe targeted 3.3.0 and had to patch the hatchling backend in three places —
to accept CMake arguments at all, to stop it naming the library after the build host, and
to stop it silently retrying without OpenMP when the cross configure failed. None of that
survives in 3.4.

OpenMP on iOS was not attempted: there is no runtime to link against, and upstream supports
`USE_OPENMP=OFF`.

### Upgrade hazards

- **The library name is decided in two places that must agree**: `_XGB_LIBNAME` in the root
  `CMakeLists.txt` and the candidate list in `xgboost/libpath.py`.
- **The sdist's `pyproject.toml` is generated per variant** (`pypi_variants.py`). Check its
  `dependencies` on every bump: the variant published as the sdist has no
  `nvidia-nccl-cu12`, but that marker exists in the wheel variants.
- **Leaving `USE_OPENMP` on for iOS would not fail loudly** — upstream's Apple OpenMP lookup
  asks Homebrew for the build host's `libomp`.
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
- `tests/iris_classifier.joblib` was written by 3.4.1. It keeps working across bumps, but
  regenerate it (the recipe is in the test file) when the version gap starts producing
  warnings.

### Coverage gaps

The device tests cover native training and prediction, UBJSON round-trips, TreeSHAP, a
desktop-trained `.joblib` classifier and the OpenMP build flag. They do not cover the
scikit-learn wrapper's own `fit`, a scikit-learn `Pipeline`, categorical features, external
memory (`DataIter`), or any multi-threaded speed-up — the OpenMP test checks the build flag,
not that work spreads across cores.
