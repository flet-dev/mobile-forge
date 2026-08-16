# scikit-learn

[scikit-learn](https://scikit-learn.org/) is Python's general-purpose machine-learning
toolkit — classifiers, regressors, clustering, decomposition, preprocessing, model
selection — all of it over NumPy arrays. What it buys you on a phone is a closed loop with
no server in it: fit a small model on data the user just produced, or load one you trained
on a laptop, and predict on device, offline.

It is a heavy dependency, and not only on its own account: the wheel drags scipy and numpy
in behind it. Budget for that before you commit — see [Things to know](#things-to-know).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "scikit-learn",
]

[tool.flet.android]
extract_packages = ["sklearn"]
```

List nothing else. The wheel's `Requires-Dist` pulls scipy, numpy, joblib, narwhals and
threadpoolctl, and on Android two further distributions you will see scroll past in the
build log: `flet-libcpp-shared` and `flet-libomp`, which carry the NDK's `libc++_shared.so`
and `libomp.so`. Seventeen of the wheel's extension modules link the first, eighteen the
second.

The `extract_packages` entry is **not optional on Android**. Flet ships pure-Python
site-packages inside `sitepackages.zip` and imports from it with `zipimport`; `import
sklearn` reaches `sklearn/utils/_repr_html/estimator.py`, which at module level reads three
`.css` files sitting next to itself through `Path(__file__).parent` — a plain filesystem
read a zip cannot serve. Leave the entry out and the app builds cleanly, then dies on the
very first `import sklearn` with a `NotADirectoryError` whose path has `sitepackages.zip`
as a directory component and ends in `sklearn/utils/_repr_html/estimator.css`.
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) ships the
listed package to disk instead, which makes the read work again. Two traps: the entry is
the **import** name (`sklearn`, never `scikit-learn`), and it has to be in *your*
`pyproject.toml` — this recipe declares the same list in its `meta.yaml`, but that copy is
read only by mobile-forge's own on-device test app and travels nowhere near your build.
iOS needs no equivalent; the zip is an Android packaging detail.

Wheels are published for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a,
x86_64) and all three iOS slices (device, and both simulator architectures), on Python
3.12, 3.13 and 3.14.

## Storage

Fitting is the expensive half and predicting is the cheap one, so the shape that works on a
phone is: fit once, write the fitted estimator to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, backed up, never auto-deleted — and reload it on every launch after that.

```python
import os

import joblib
from sklearn.linear_model import LogisticRegression

MODEL_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "model.joblib")

if os.path.exists(MODEL_PATH):
    model = joblib.load(MODEL_PATH)
else:
    model = LogisticRegression().fit(X, y)
    joblib.dump(model, MODEL_PATH)
```

[joblib](https://joblib.readthedocs.io/en/stable/generated/joblib.dump.html) is already
installed — scikit-learn depends on it — so this costs no extra dependency, and
[`joblib.load`](https://joblib.readthedocs.io/en/stable/generated/joblib.load.html) is what
upstream recommends over bare `pickle` because it stores the estimator's NumPy arrays
efficiently. Never put a model in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) — losing it means re-fitting on the next cold start.

To ship a model you trained elsewhere, put the `.joblib` file in your app's
`src/assets/` and read it from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir),
which is exactly what Flet documents that variable for. Assets are read-only and reset on
every app update, so if your app ever re-fits, copy the shipped model into
`FLET_APP_STORAGE_DATA` first and treat that copy as the live one.

Two things to get right about the file itself. It is a pickle, so
[loading one executes code](https://scikit-learn.org/stable/model_persistence.html) — only
ever load a model your own build produced, never one fetched over the network. And it is
tied to the versions that wrote it: reload a model under a different scikit-learn and you
get an
[`InconsistentVersionWarning`](https://scikit-learn.org/stable/modules/generated/sklearn.exceptions.InconsistentVersionWarning.html)
at best and a broken estimator at worst. If you train on a laptop and ship the result,
install the same scikit-learn, scipy and numpy versions there that your app resolves — and
re-check that after any dependency bump, because a bump on either side silently
invalidates the file you shipped.

Finally, do not reach for the `sklearn.datasets.fetch_*` loaders on device: they download
on first use and cache into `~/scikit_learn_data` (overridable with `SCIKIT_LEARN_DATA`).
The small `load_*` datasets are different — their data files ship inside the wheel and read
through `importlib.resources`, so they work offline.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`petals`](examples/petals) — fits a classifier on device and reuses it after a restart.

## Threading

`fit` is CPU-bound and can run for seconds on a phone, so call it from
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
that handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads. `predict` on a handful of rows is fast enough to stay on the
event handler.

What happens *inside* one `fit` differs by platform. On Android, 18 of the wheel's 69
extension modules link `libomp.so` — the k-means kernels, the histogram gradient-boosting
kernels, the pairwise-distance reductions, the loss functions — and those run
[OpenMP-parallel](https://scikit-learn.org/stable/computing/parallelism.html#lower-level-parallelism-with-openmp)
across cores. On iOS not one of them does: Apple ships no libomp, so this recipe builds
single-threaded there and every kernel runs on one core. Same API, same results, different
wall clock — do not size an iOS feature from an Android measurement.

Where OpenMP is active, its pool defaults to the core count. Cap it by setting
`OMP_NUM_THREADS` before the first `sklearn` import if you would rather a background fit
did not take every core the device has.

`n_jobs` on estimators and `joblib.Parallel` is a *different* mechanism —
[process-based parallelism](https://scikit-learn.org/stable/computing/parallelism.html#higher-level-parallelism-with-joblib)
that has to start worker interpreters. The OpenMP threading above is the only parallelism
this build ships; leave `n_jobs` at its default.

## Things to know

- **The linear algebra is borrowed from scipy, not bundled.** `sklearn.utils._cython_blas`
  is the single extension in the wheel that names
  [`scipy.linalg.cython_blas`](https://docs.scipy.org/doc/scipy/reference/linalg.cython_blas.html);
  it takes BLAS function pointers from that module's Cython capsule at import, and nine
  other extensions (`_k_means_lloyd`, `_cd_fast`, the libsvm and liblinear wrappers,
  `_middle_term_computer`, …) go through it. Nothing in the wheel links a BLAS library —
  the code that actually runs `gemm` is the OpenBLAS compiled into scipy. The practical
  consequence: scipy is not an optional companion here, it is where half of scikit-learn's
  arithmetic happens, and a scipy that fails to import takes scikit-learn down with it.
- **Do not pin numpy or scipy.** They are resolved for you, and the binding constraint is
  scipy's own `numpy<2.8,>=2.0.0`. Pin numpy to a 1.x release — pypi.flet.dev still carries
  one — and the resolution fails outright rather than degrading quietly.
- **Size.** The Android arm64-v8a wheel is 7.9 MiB and unpacks to 26 MiB (iOS: 7.9 MiB, 30
  MiB); scipy adds a 28 MiB wheel that unpacks to 80 MiB, numpy 6.5 MiB and 21 MiB. Of the
  unpacked scikit-learn, 11.4 MiB is the 69 extension modules, 5.5 MiB is its own `tests/`
  packages and 1.2 MiB is `.pyx`/`.pxd`/`.pyx.tp` Cython sources — upstream ships the last
  two in its own wheels and so does this one, and your app will import none of it. Flet
  compiles `.py` to `.pyc` and zips site-packages, so what lands on the device is smaller
  than the unpacked figure; the wheel sizes are the honest floor.
- **pandas and matplotlib are separate recipes on pypi.flet.dev**, so
  [DataFrame-shaped transformer output](https://scikit-learn.org/stable/auto_examples/miscellaneous/plot_set_output.html)
  and the plotting helpers in
  [`sklearn.inspection`](https://scikit-learn.org/stable/api/sklearn.inspection.html) are
  reachable — at the cost of two more large wheels. Neither is pulled in by scikit-learn.
- **Size the dataset for a phone, not for a laptop.** Nothing stops you fitting a
  [`RandomForestClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html)
  on 100k rows on device, but a backgrounded app that asks for too much memory gets killed
  rather than slowed down. The estimators with `partial_fit` —
  [`SGDClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.SGDClassifier.html),
  [`MiniBatchKMeans`](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.MiniBatchKMeans.html)
  — exist for exactly the case where data arrives over time and you do not want to hold all
  of it at once.

## Build notes (maintainers)

Both patches explain themselves at the top of the file, and `meta.yaml` justifies the host
pins, the two Android-only runtime libraries and the `extract_packages` entry inline. Two
things neither of them records.

**Single-threaded iOS is a decision, not a limitation hit by accident.** Apple ships no
libomp, and rather than building one — or a serial stub — as a `flet-lib*` recipe, this
recipe takes the fallback scikit-learn already supports on plain macOS. That is where the
platform asymmetry in [Threading](#threading) comes from, and it is what would have to
change if someone wants it gone.

**The forced not-found `dependency()` must not carry a `language:` keyword.** meson
rejects that on a dependency name it does not know, so the obvious-looking
`dependency('openmp', language: 'c', required: false)` fails outright rather than
returning not-found.

What to re-verify on a bump:

- **`relax-scipy-build-cap.patch` hard-codes version numbers**, so re-read the cap in the
  new `pyproject.toml` and re-derive the patch. It is right only while the build
  environment's scipy and the `requirements.host` scipy are the same release, which is the
  entire point of it — a `cython_blas.pxd` compiled against one release and linked against
  another is what the capsule binding cannot survive. Move the numpy and scipy pins to
  whatever pypi.flet.dev carries at the same time.
- **The counts quoted to consumers** — 69 extension modules, 17 linking
  `libc++_shared.so`, 18 linking `libomp.so`, and the 11.4 MiB / 5.5 MiB / 1.2 MiB split of
  the unpacked wheel — all come from a scan of the Android wheel. Run it again; nothing in
  CI checks them.
- **The `numpy<2.8,>=2.0.0` bound** under *Things to know* is scipy's constraint, not
  scikit-learn's. Re-read it from the scipy that actually resolves.
- The OpenMP asymmetry, the BLAS borrowed from scipy, and the `estimator.css` read that
  makes `extract_packages` mandatory are each pinned by a test in `tests/`, so those three
  claims go red rather than going stale. Deciding the `extract_packages` requirement has
  lapsed needs an on-device check, though, not a reading of upstream's source.
