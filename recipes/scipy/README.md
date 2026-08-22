# scipy

[`scipy`](https://scipy.org/) is the standard scientific-computing library built on NumPy:
optimisation, signal processing, FFTs, interpolation, sparse matrices, spatial queries,
statistics and linear algebra. On mobile it is what lets the numerics ship *inside* the app —
these wheels carry a full BLAS/LAPACK, so a curve fit or a filter runs offline on the device
instead of round-tripping to a server.

## Install

Add scipy to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "scipy",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`signal-fit`](examples/signal-fit) — filters a noisy waveform and fits its parameters back out.

## Usage in a Flet app

Filter a sampled signal, fit a model to what is left, and put the answer in a control:

```python
from scipy import optimize, signal

sos = signal.butter(4, 8.0, btype="low", fs=500.0, output="sos")
filtered = signal.sosfiltfilt(sos, samples)

fitted, _ = optimize.curve_fit(model, t, filtered, p0=[1.0, 0.5, 3.0, 0.0])
readout = ft.Text(f"{fitted[2]:.3f} Hz at amplitude {fitted[0]:.2f}")
```

scipy takes and returns [numpy](https://numpy.org/doc/stable/) arrays throughout. Scalars come
back as `numpy.float64`, which subclasses `float` and formats in an f-string directly; an array
does not go into a Flet control at all, so pull out the values you want to show, as above.
[`curve_fit`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.curve_fit.html)
is a local optimiser — seed `p0` from something real, such as a spectrum peak or a previous
fit, rather than from a constant, or it settles into the nearest wrong minimum without
complaining.

### Storage

**scipy reads nothing from disk that you did not ask it to.** Its one runtime data file,
`scipy/stats/_sobol_direction_numbers.npz`, is loaded through
[`importlib.resources`](https://docs.python.org/3/library/importlib.resources.html) rather than
a `__file__`-relative path, so it works unchanged from Android's zipped site-packages and needs
no [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry.

What you store is your own data, and scipy's readers and writers take ordinary paths:
[`scipy.io`](https://docs.scipy.org/doc/scipy/reference/io.html) —
[`loadmat`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.io.loadmat.html)/[`savemat`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.io.savemat.html),
[`wavfile`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.io.wavfile.write.html)
and [Matrix Market](https://docs.scipy.org/doc/scipy/reference/generated/scipy.io.mmwrite.html)
— and
[`sparse.save_npz`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.save_npz.html)/[`load_npz`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.load_npz.html)
all want somewhere to put a file:

```python
data_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
sparse.save_npz(os.path.join(data_dir, "model.npz"), matrix)
```

Anything the user expects to keep belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data);
a matrix or a spectrum you can recompute belongs in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache);
an intermediate that dies with the run belongs in
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp).
Data shipped with the app is an asset: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and read
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir) when
a call needs an absolute path.

[`scipy.datasets`](https://docs.scipy.org/doc/scipy/reference/datasets.html) is the exception,
and it is not a Flet directory at all: it caches through `pooch` into
`pooch.os_cache("scipy-data")`. Bundle what you need as an asset instead.

### Threading

**BLAS and LAPACK here are single-threaded.** OpenBLAS is built `USE_THREAD=0 NUM_THREADS=1`,
so [`linalg.solve`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.solve.html),
[`svd`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.svd.html),
[`eigh`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.eigh.html), the
covariance step of `curve_fit` — everything routed through
[`scipy.linalg`](https://docs.scipy.org/doc/scipy/reference/linalg.html) — runs on one core, and
`OPENBLAS_NUM_THREADS` does nothing. Desktop scipy parallelises these; budget for a phone that
will not. (Ignore the `MAX_THREADS` line in
[`scipy.show_config()`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.show_config.html):
it is copied verbatim from OpenBLAS's default makefile variables and does not describe this
build.)

[`scipy.fft`](https://docs.scipy.org/doc/scipy/reference/fft.html) is the exception. It vendors
ducc, which brings its own C++ thread pool, so `workers=` genuinely spreads a transform across
cores and `DUCC0_NUM_THREADS` / `OMP_NUM_THREADS` cap it. Nothing else in the wheel uses
threads, and nothing at all uses OpenMP. The *default* worker count is derived differently on
Android — from the total core count rather than from the process's CPU affinity mask, because
bionic has no `pthread_getaffinity_np` — so pass `workers=` explicitly if the exact number
matters.

Numerics on the UI thread freeze the UI. Push anything non-trivial to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end the
handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does not
reach background threads. scipy itself imposes no thread rules: arrays and results move between
threads freely, and there is no shared handle to serialise.

### Compiled kernels

**On Android, three modules are interpreted rather than compiled.** scipy uses
[pythran](https://pythran.readthedocs.io/) to compile a handful of pure-Python numerical kernels
ahead of time; pythran is disabled for Android, so those three ship as the `.py` files scipy
provides for exactly this case. iOS keeps the compiled versions.

Nothing is missing: both platforms expose exactly the same set of modules, and the answers are
identical to the last digit. Only these six entry points are affected, and only in speed:

- [`interpolate.RBFInterpolator`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html)
- [`linalg.funm`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.funm.html)
  and [`linalg.signm`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.signm.html)
- [`stats.somersd`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.somersd.html)
- [`stats.mstats.siegelslopes`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mstats.siegelslopes.html)
- [`stats.ks_2samp(method="exact")`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html),
  with unequal sample sizes only

The cost varies enormously by call, which is what decides whether any of these is shippable.
Swapping the compiled module for the exact `.py` file the Android wheel ships, on one desktop
machine and the same inputs, `RBFInterpolator` took 50–95× longer, `somersd` 25×, `ks_2samp`
7×, `funm`/`signm` 6× and `mstats.siegelslopes` 4.5×. So `funm` on a background thread is
usually fine and `RBFInterpolator` on a path a user waits for is not. Those are desktop
ratios, not device ones — treat them as the shape of the problem and time the call on the
device before shipping it. Everything *else* in scipy is compiled identically on both
platforms.

### App size

Expect roughly 27–34 MB of compressed wheel and 76–107 MB unpacked per architecture. About
17 MB of every unpacked wheel, on every architecture, is scipy's own `tests/` packages, which
your app never imports. Flet's
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) strips headers and
static archives, not test suites, so name them:

```toml
[tool.flet.cleanup]
package_files = ["scipy/**/tests"]
```

Leave `cleanup.packages` on. `flet-libopenblas`, which scipy's wheel requires, holds nothing
your app runs: it is a static archive of roughly 70 MB plus headers, and OpenBLAS is already
linked into scipy's own extensions. `flet build` installs it and the default cleanup then
deletes it again, so you pay build time and disk rather than app size. Turn cleanup off and all
70 MB of it ships inside the app.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI. These figures describe the package payload, not the exact amount
added to the final APK or IPA; packaging and compression determine that.

### Other considerations

A desktop `flet run` uses PyPI's own scipy wheel, and it differs from these in four ways at
once. Its BLAS is usually the platform's — Accelerate on macOS — rather than OpenBLAS, so the
last digits of a linear-algebra result can differ. That BLAS is multi-threaded, so desktop
timings do not transfer. [`scipy.odr`](https://docs.scipy.org/doc/scipy/reference/odr.html)
imports there and does not here. And the three pythran kernels are compiled on desktop, so the
six calls that depend on them are fast there and interpreted on Android.

The consequence is that a laptop is not a rehearsal for any of those four. Print
`scipy.show_config()` on both machines when a number disagrees, and validate the parts that
depend on it on a device or emulator/simulator.

## Things to know

- **`scipy.odr` is not in these wheels, and it is the only thing missing.** There is no Fortran
  compiler in the cross toolchain, so the build drops it. `import scipy.odr` raises
  `ModuleNotFoundError: No module named 'scipy.odr'` and `scipy.odr` raises
  `AttributeError: Module 'scipy' has no attribute 'odr'`. Upstream deprecated
  [`scipy.odr`](https://docs.scipy.org/doc/scipy/reference/odr.html) in 1.17.0 and will remove
  it in 1.19.0, pointing users at the standalone
  [`odrpack`](https://pypi.org/project/odrpack/) package — which has no recipe here either, and
  wraps the same Fortran.

- **The same BLAS on both platforms.** OpenBLAS is linked *statically* into scipy's own
  extensions — there is no separate library to load, and iOS does **not** use the system
  Accelerate framework. Numerical results and BLAS version therefore do not drift between
  Android and iOS, or across iOS releases. `scipy.show_config()` on the device reports what you
  actually got.

- **`scipy.datasets` needs a network and an optional package.** `pooch` is not installed with
  scipy, and every dataset downloads on first use, so on a device the first call fails without a
  connection and never succeeds offline. Ship the arrays you need in the assets directory
  instead.

## Build notes (maintainers)

### Recipe shape

A plain meson-python sdist recipe: no `build.sh`, no vendored source. Each patch carries its
rationale at the top of the file and each build flag is justified in `meta.yaml` next to the
flag, so this section is only what neither of those records.

**Accelerate on iOS was rejected, not overlooked.** Linking Apple's framework would drop the
`flet-libopenblas` host dependency and a good deal of build time, and it is what most iOS ports
of a numerical stack do. The reason not to is that one BLAS on both platforms means results
that do not drift between Android and iOS, or across iOS releases — a promise the consumer
sections above make. Dropping `scipy.odr` is the same kind of trade: cheaper than sourcing a
cross Fortran compiler or translating ODRPACK for one module upstream has already deprecated.

The `clog`/`cpow` substitutes the Android patch compiles in were measured before being
accepted, since every Android device gets them regardless of its OS version: away from the unit
circle they agree with a 50-digit reference to about 1e-13 relative on the real part, and in the
one region where they do lose digits (`|z|` within ~1e-9 of 1, where `log|z|` cancels) numpy's
own complex log loses nearly as many. That is why the alternative — raising the target API level
to 26 for the sake of two libm symbols — was not taken.

Twenty-three of the shipped Android extensions link the NDK C++ runtime, which is why
`flet-libcpp-shared` is a host requirement on that platform and not on iOS.

### Upgrade hazards

The pythran flag is conditional on the NDK's clang rejecting pythran's headers. If a newer NDK
compiles them, the Android flag and the whole [Compiled kernels](#compiled-kernels) subsection
go away together — that is a rewrite of a consumer section, not a flag flip.

Upstream removes `scipy.odr` in 1.19.0. At that point `_without-fortran` stops being the reason
anything is absent, and the consumer bullet needs rewriting rather than updating.

The single-threaded BLAS claim tracks `flet-libopenblas`, not scipy: it holds only while that
recipe builds `USE_THREAD=0 NUM_THREADS=1`. The `MAX_THREADS` values `show_config()` reports —
4 on Android and 3 on iOS, copied from OpenBLAS's default makefile variables — move with that
recipe too, so a libopenblas bump can change what a user sees on screen without touching this
recipe at all.

### Re-verification checklist

In rough order of how quietly each can go wrong:

- **The pythran fallback list.** Re-derive it by listing which modules ship as `.py` in the
  Android wheel and as `.so` in the iOS one. The test exercises two of the six entry points, so
  a fourth module quietly joining the fallback set is invisible otherwise.
- **"`scipy.odr` is the only thing missing."** The test pins odr's absence and that the other
  submodules import — not the module-for-module count against the desktop wheel. Re-run that
  diff; the last run removed exactly nine module files (`scipy.odr` and its eight submodules),
  leaving 1085 of 1094.
- **Single-threaded BLAS.** After a `flet-libopenblas` bump, confirm the shipped
  `_fblas`/`_flapack` extensions still contain no reference to `pthread_create`, and re-read
  the `MAX_THREADS` defaults quoted above.
- **No `extract_packages` entry.** This rests on `_sobol_direction_numbers.npz` remaining the
  only runtime data file and still being read through `importlib.resources`. Look for new
  `__file__`-relative data reads across the tree before repeating the claim.
- **Sizes.** Measured per architecture, quoted **decimal** (MB = 10⁶ bytes). Re-measure rather
  than scaling the old numbers, and measure in bytes — `ls -l` on the wheel, `du -k` × 1024 on
  the unpacked tree — then divide by 10⁶. `du -h` reports binary units and a straight copy of
  its output reads as a regression that did not happen.

### Coverage gaps

The device tests cover `linalg` solve/svd/eigh/cholesky through OpenBLAS, an `fft` round trip,
real and complex `special`, sparse `spsolve`, `optimize.minimize`, `integrate.quad`,
`interpolate.interp1d`, `stats.norm`, odr's absence, the BLAS identity, two pythran fallbacks,
and the Sobol data-file read. They leave real ground uncovered:

- **`scipy.signal` is not tested at all.** The example app is its only exercise, and it is not
  run by CI.
- **Four of the six pythran entry points are untested** — `signm`, `somersd`,
  `mstats.siegelslopes` and `ks_2samp(method="exact")`. A broken fallback in any of them ships
  green.
- **`scipy.io`, `ndimage`, `spatial` and `cluster` are imported but never called**, so the
  storage guidance above rests on reading their source rather than on a device run.
- **Only arm64 has an on-device run recorded.** Nothing above has been observed on x86_64 or
  armeabi-v7a.
- **The two headline claims are inferred, not observed.** "Single-threaded BLAS" comes from
  inspecting the extensions for `pthread_create`, and the on-device `show_config()` test reports
  how the build was *configured*, not what the loaded binary does.
- **The `[tool.flet.cleanup]` pattern above is not exercised by anything.** Verify it against a
  built app before relying on it to shrink one.
