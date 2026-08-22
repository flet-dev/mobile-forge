# scikit-learn

[scikit-learn](https://scikit-learn.org/) is Python's general-purpose machine-learning
toolkit — classifiers, regressors, clustering, decomposition, preprocessing, model
selection — all of it over NumPy arrays. What it buys you on a phone is a closed loop with
no server in it: fit a small model on data the user just produced, or load one you trained
on a laptop, and predict on device, offline.

It is a heavy dependency, and not only on its own account: the wheel drags scipy and numpy
in behind it. Budget for that before you commit — see [App size](#app-size).

## Install

Add scikit-learn to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "scikit-learn",
]

[tool.flet.android]
extract_packages = ["sklearn"]
```

The `extract_packages` entry is **not optional on Android**. Flet ships pure-Python
site-packages inside `sitepackages.zip` and imports from it with `zipimport`, and `import
sklearn` reaches a module that reads three `.css` files next to itself through
`Path(__file__).parent` — a plain filesystem read a zip cannot serve. Leave the entry out
and the app builds cleanly, then dies on the very first `import sklearn` with a
`NotADirectoryError` whose path has `sitepackages.zip` as a directory component and ends in
`sklearn/utils/_repr_html/estimator.css`.
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) ships the
listed package to disk instead, which makes the read work again. Two traps: it is the
**import** name (`sklearn`, never `scikit-learn`), and it has to be in *your*
`pyproject.toml` — this recipe declares the same list in its `meta.yaml`, but that copy is
read only by mobile-forge's own test app. iOS needs no equivalent; the zip is an Android
packaging detail.

Wheels are published for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a,
x86_64) and all three iOS slices (device, and both simulator architectures), on Python
3.12, 3.13 and 3.14.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`petals`](examples/petals) — fits a classifier on device and reuses it after a restart.

## Usage in a Flet app

Fit an estimator, ask it about one new sample, and put the answer in a control such as
[`ft.Text`](https://flet.dev/docs/controls/text/):

```python
import flet as ft
from sklearn.linear_model import LogisticRegression

model = LogisticRegression().fit(measurements, species)

[predicted] = model.predict([[4.5, 1.4]])
confidence = model.predict_proba([[4.5, 1.4]]).max()
page.add(ft.Text(f"{predicted} — {confidence:.0%} confident"))
```

Everything crossing that boundary is a [numpy](https://numpy.org/doc/stable/) array.
[`predict`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html#sklearn.linear_model.LogisticRegression.predict)
takes a 2-D array and returns one even for a single row, so unpack it as above rather than
putting an array in a control, and
[`predict_proba`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html#sklearn.linear_model.LogisticRegression.predict_proba)
returns a row of class probabilities whose largest entry is the confidence in the label
`predict` chose. Its `.max()` is a `numpy.float64` and formats in an f-string directly; an
integer label is a `numpy.int64` and does not, so cast that one where it leaves the array.

### Storage

Fitting is the expensive half and predicting is the cheap one, so the shape that works on a
phone is: fit once, write the fitted estimator to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, backed up, never auto-deleted — and reload it on every launch after that.

```python
import os

import joblib

MODEL_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "model.joblib")

if os.path.exists(MODEL_PATH):
    model = joblib.load(MODEL_PATH)
else:
    model = LogisticRegression().fit(X, y)
    joblib.dump(model, MODEL_PATH)
```

[joblib](https://joblib.readthedocs.io/en/stable/generated/joblib.dump.html) is already
installed — scikit-learn depends on it — and
[`joblib.load`](https://joblib.readthedocs.io/en/stable/generated/joblib.load.html) is what
upstream recommends over bare `pickle`, because it stores the estimator's NumPy arrays
efficiently. Never put a model in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) — losing it means re-fitting on the next cold start.

To ship a model you trained elsewhere, put the `.joblib` file in your app's `src/assets/`
and read it from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).
Assets are read-only and reset on every app update, so if your app ever re-fits, copy the
shipped model into `FLET_APP_STORAGE_DATA` first and treat that copy as the live one.

Do not reach for the
[`sklearn.datasets.fetch_*`](https://scikit-learn.org/stable/api/sklearn.datasets.html)
loaders on device: they download on first use and cache into `~/scikit_learn_data`
(overridable with `SCIKIT_LEARN_DATA`). The small `load_*` datasets are different — their
data files ship inside the wheel and read through `importlib.resources`, so they work
offline.

### Model files

A saved estimator is a pickle, so
[loading one executes code](https://scikit-learn.org/stable/model_persistence.html). Only
ever load a model your own build produced, never one fetched over the network.

It is also tied to the versions that wrote it: reload a model under a different
scikit-learn and you get an
[`InconsistentVersionWarning`](https://scikit-learn.org/stable/modules/generated/sklearn.exceptions.InconsistentVersionWarning.html)
at best and a broken estimator at worst. If you train on a laptop and ship the result,
install the same scikit-learn, scipy and numpy versions there that your app resolves — and
re-check that after any dependency bump, because a bump on either side silently invalidates
the file you shipped.

### Threading

`fit` is CPU-bound and can run for seconds on a phone, so call it from
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
that handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads. `predict` on a handful of rows is fast enough to stay on the
event handler.

**The linear algebra runs on one core on both platforms.** scikit-learn links no BLAS of
its own; it borrows scipy's, and the OpenBLAS compiled into these scipy wheels is built
`USE_THREAD=0 NUM_THREADS=1`. So
[`LinearRegression`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LinearRegression.html),
`PCA`, the SVM and linear-model solvers and everything else that spends its time in `gemm`
see one core on Android and one on iOS, and `OPENBLAS_NUM_THREADS` does nothing.

**OpenMP is Android-only, and it covers a different set of estimators.** The k-means
kernels, the histogram gradient-boosting kernels, the pairwise-distance reductions and the
loss functions are compiled with
[OpenMP](https://scikit-learn.org/stable/computing/parallelism.html#lower-level-parallelism-with-openmp)
on Android and do spread across cores, so
[`KMeans`](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.KMeans.html)
and `HistGradientBoostingClassifier` are the calls that get the win. On iOS none of them do:
Apple ships no libomp, so this recipe builds single-threaded there. Same API, same results,
different wall clock — do not size an iOS feature from an Android measurement. Where OpenMP
is active its pool defaults to the core count; cap it with `OMP_NUM_THREADS`, set before the
first `sklearn` import, if a background fit should not take every core the device has.

`n_jobs` on estimators and `joblib.Parallel` is a *different* mechanism —
[process-based parallelism](https://scikit-learn.org/stable/computing/parallelism.html#higher-level-parallelism-with-joblib)
that has to start worker interpreters, and Flet supports no
[`multiprocessing`](https://flet.dev/docs/cookbook/multiprocessing/) on Android or iOS. The
Android OpenMP threading above is the only parallelism this build ships; leave `n_jobs` at
its default.

### App size

Roughly 8 MB compressed and 27–32 MB unpacked per architecture — and scikit-learn is the
small part of what you are shipping. scipy adds about 30 MB compressed and 84 MB unpacked,
numpy about 7 MB and 22 MB, so budget around 45 MB compressed and 130 MB unpacked per
architecture for the three together.

About 11 MB of the unpacked scikit-learn is its 69 compiled extension modules, which is the
floor — nothing removes those. A further 5.8 MB is its own `tests` packages, which your app
never imports. Flet's
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) already deletes
`.pyx` and `.pxd` for you, along with headers, static archives, `py.typed` and
`__pycache__`; what it does not delete is test suites, so name those:

```toml
[tool.flet.cleanup]
package_files = [
    "sklearn/tests",
    "sklearn/*/tests",
    "sklearn/*/*/tests",
    "sklearn/**/*.pyx.tp",
]
```

`.pyx.tp` needs naming because the default `**.pyx` glob does not match it — a Tempita
template is not a `.pyx` file by name.

Three `tests` patterns because those packages sit at three depths under `sklearn/`. scipy
and numpy ship test suites of the same kind — about 17 MB and 6.6 MB unpacked — so adding
`"scipy/**/tests"`, `"numpy/tests"` and `"numpy/*/tests"` to the same list clears those too.
Leave `cleanup.packages` on: Flet compiles `.py` to `.pyc`, and on Android zips
site-packages as well — but not `sklearn`, which `extract_packages` puts back on disk.

On Android, also use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI. These are package figures, not the amount added to the
final APK or IPA, and they are decimal — re-measuring with `du -h`, which reports binary
units and turns 27 MB into 26 M, reads as a regression that is not there.

### Other considerations

A desktop `flet run` resolves PyPI's own scikit-learn, scipy and numpy wheels rather than
these, and differs in four ways that each hide a device failure. Validate all four on a
device or emulator/simulator rather than under `flet run`.

- **Desktop scikit-learn has OpenMP everywhere**, macOS included, where the PyPI wheel
  bundles a libomp. Here it exists on Android and not on iOS, so a `KMeans` fit you timed
  under `flet run` says nothing about an iPhone.
- **Desktop BLAS is multi-threaded**, and here it is single-threaded on both platforms, so
  every `gemm`-bound timing transfers badly in the same direction.
- **`n_jobs` works on a laptop.** Set it above 1 in development and the speed-up is real; on
  device the worker interpreters have nowhere to start.
- **`sklearn.datasets.fetch_*` works on a laptop**, because there is a network and a
  writable home directory. Bundle the arrays you need as assets instead.

## Things to know

- **The linear algebra is borrowed from scipy, not bundled.** `sklearn.utils._cython_blas`
  takes BLAS function pointers out of
  [`scipy.linalg.cython_blas`](https://docs.scipy.org/doc/scipy/reference/linalg.cython_blas.html)'s
  Cython capsule at import, and the estimators that need `gemm` — `_k_means_lloyd`,
  `_cd_fast`, the libsvm and liblinear wrappers, the pairwise-distance reductions — go
  through it. Nothing in the wheel links a BLAS of its own. So scipy is not an optional
  companion here, it is where half of scikit-learn's arithmetic happens, and a scipy that
  fails to import takes scikit-learn down with it.
- **Do not pin numpy or scipy.** They are resolved for you, and the binding constraint is
  scipy's own `numpy<2.8,>=2.0.0`. Pin numpy to a 1.x release — pypi.flet.dev still carries
  one — and the resolution fails outright rather than degrading quietly.
- **Size the dataset for a phone, not for a laptop.** Nothing stops you fitting a
  [`RandomForestClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html)
  on 100k rows on device, but a backgrounded app that asks for too much memory gets killed
  rather than slowed down. The estimators with `partial_fit` —
  [`SGDClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.SGDClassifier.html),
  [`MiniBatchKMeans`](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.MiniBatchKMeans.html)
  — exist for exactly the case where data arrives over time and you do not want to hold all
  of it at once.
- **pandas and matplotlib are separate recipes**, so
  [DataFrame-shaped transformer output](https://scikit-learn.org/stable/auto_examples/miscellaneous/plot_set_output.html)
  and the plotting helpers in
  [`sklearn.inspection`](https://scikit-learn.org/stable/api/sklearn.inspection.html) are
  reachable. Neither is pulled in by scikit-learn, and both are additions you feel:
  [`pandas`](../pandas) is roughly 10 MB compressed and 32–41 MB unpacked per architecture,
  [`matplotlib`](../matplotlib) roughly 8 MB and 20 MB.

## Build notes (maintainers)

### Recipe shape

A plain meson-python sdist recipe: no `build.sh`, no vendored source, no native library of
its own. Both patches explain themselves at the top of the file, and `meta.yaml` justifies
the host pins, the two Android-only runtime libraries and the `extract_packages` entry
inline. Two things neither records.

**Single-threaded iOS is a decision, not a limitation hit by accident.** Apple ships no
libomp, and rather than building one — or a serial stub — as a `flet-lib*` recipe, this
recipe takes the fallback scikit-learn already supports on plain macOS. That is where the
platform asymmetry in [Threading](#threading) comes from, and it is what would have to
change if someone wants it gone.

**The forced not-found `dependency()` must not carry a `language:` keyword.** meson rejects
that on a dependency name it does not know, so the obvious-looking
`dependency('openmp', language: 'c', required: false)` fails outright rather than returning
not-found.

### Upgrade hazards

**`relax-scipy-build-cap.patch` hard-codes version numbers.** Re-read the cap in the new
`pyproject.toml` and re-derive the patch. It is right only while the build environment's
scipy and the `requirements.host` scipy are the same release, which is the entire point of
it — a `cython_blas.pxd` compiled against one release and linked against another is what the
capsule binding cannot survive. Move the numpy and scipy pins to whatever pypi.flet.dev
carries at the same time.

**A `flet-libopenblas` bump can falsify this page without touching this recipe.** The
single-core BLAS claim under [Threading](#threading) tracks that recipe building
`USE_THREAD=0 NUM_THREADS=1`, by way of scipy; nothing here would show it had changed.

**Upstream owns the `estimator.css` read.** If scikit-learn moves `_repr_html` to
`importlib.resources`, the mandatory `extract_packages` entry in [Install](#install) stops
being mandatory, and that is a rewrite of the section rather than an edit. Deciding the
requirement has lapsed needs an on-device check, not a reading of upstream's source.

### Re-verification checklist

- **The Android runtime-library dependencies.** The wheel's C++ extensions must still
  receive `libc++_shared.so` and its OpenMP ones `libomp.so` through the `meta.yaml` host
  requirements. Re-scan the built Android wheel; nothing in CI counts them.
- **The `numpy<2.8,>=2.0.0` bound** quoted under [Things to know](#things-to-know) is
  scipy's constraint, not scikit-learn's. Re-read it from the scipy that actually resolves.
- **Every size on this page**, quoted **decimal** (MB = 10⁶ bytes): the compressed and
  unpacked ranges, the 5.8 MB of `tests` and 1.3 MB of Cython sources the
  [App size](#app-size) snippet removes, and the scipy, numpy, pandas and matplotlib figures
  that make the budget concrete. Measure in bytes — `ls -l` on the wheel, `du -k` × 1024 on
  the unpacked tree — then divide by 10⁶; `du -h` reports binary units, and a straight copy
  of it reads as a regression that did not happen. Re-run the cleanup globs against a staged
  tree if upstream moves a test package or stops shipping `.pyx` sources.
- **The three claims that have tests** — the OpenMP asymmetry, the BLAS borrowed from scipy,
  and the `estimator.css` read — go red rather than stale, subject to the caveat in
  [Coverage gaps](#coverage-gaps) about how the OpenMP one is written.

### Coverage gaps

`tests/test_scikit_learn.py` runs seven tests on device: a `LinearRegression` fit through
the BLAS path, an `SVC` through the vendored libsvm C++, a `KMeans` through the
Cython/OpenMP kernels, the `estimator.css` read, the OpenMP-per-platform check, the scipy
BLAS identity, and a joblib round trip through `FLET_APP_STORAGE_DATA`. A green run is
narrower than it looks:

- **`test_openmp_matches_the_platform` asserts nothing off the two mobile platforms.** It is
  an `if sys.platform == "android"` / `elif == "ios"` with no `else`, so on any other value
  it passes without checking anything. Only the mobile legs are cover for the asymmetry.
- **Nothing exercises the single-core BLAS claim.** `test_blas_comes_from_scipy` pins where
  the symbols come from, not how many threads they use; that rests on reading
  `flet-libopenblas`.
- **Nothing exercises the rest of the page.** `n_jobs`, `partial_fit`, `OMP_NUM_THREADS`,
  the `fetch_*`/`load_*` distinction, `InconsistentVersionWarning`, the size figures, the
  `[tool.flet.cleanup]` globs and the numpy/scipy resolution bound all rest on inspection
  and on the example app, which CI does not run. Verify the cleanup snippet against a built
  app before relying on it to shrink one.
