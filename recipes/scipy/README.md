# scipy

[`scipy`](https://scipy.org/) is the standard scientific-computing library built on NumPy:
optimisation, signal processing, FFTs, interpolation, sparse matrices, spatial queries,
statistics and linear algebra. On mobile it is what lets the numerics ship *inside* the
app — these wheels carry a full BLAS/LAPACK and every compiled kernel, so a curve fit or
a filter runs offline on the device instead of round-tripping to a server.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "scipy",
]
```

`numpy` comes along automatically — add it to the list yourself only if your own code
imports it. Two more wheels come along too, and neither needs configuring:
`flet-libcpp-shared` on Android (the NDK C++ runtime that 23 of scipy's extensions link
against) and `flet-libopenblas` on both platforms (see [Things to know](#things-to-know) —
it is dead weight during the build, not in the app).

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. The one data file scipy loads at runtime,
`scipy/stats/_sobol_direction_numbers.npz`, is read through `importlib.resources`, which
works fine from Android's zipped site-packages.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for
iOS, on Python 3.12, 3.13 and 3.14.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`signal-fit`](examples/signal-fit) — filters a noisy waveform and fits its parameters back out.

## Threading

**BLAS and LAPACK here are single-threaded.** OpenBLAS is built `USE_THREAD=0
NUM_THREADS=1`, and the shipped `_fblas`/`_flapack` extensions contain no reference to
`pthread_create` at all. So `linalg.solve`, `svd`, `eigh`, the covariance step of
`curve_fit` — everything routed through BLAS — runs on one core, and
`OPENBLAS_NUM_THREADS` does nothing. Desktop scipy parallelises these; budget for a phone
that will not. (Ignore the `MAX_THREADS` line in `scipy.show_config()`: it is copied
verbatim from OpenBLAS's default makefile variables, which is why it reads 4 on Android and
3 on iOS, and it does not describe this build.)

[`scipy.fft`](https://docs.scipy.org/doc/scipy/reference/fft.html) is the exception. It
vendors ducc, which brings its own C++ thread pool, so `workers=` genuinely spreads a
transform across cores and `DUCC0_NUM_THREADS` / `OMP_NUM_THREADS` cap it. Nothing else in
the wheel uses threads, and nothing at all uses OpenMP.

Numerics on the UI thread freeze the UI. Push anything non-trivial to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads. scipy itself imposes no thread rules: arrays and results move
between threads freely, and there is no shared handle to serialise.

## Android notes

**Three modules are interpreted rather than compiled.** scipy uses
[pythran](https://pythran.readthedocs.io/) to compile a handful of pure-Python numerical
kernels ahead of time; pythran is disabled for Android (its headers do not compile with the
NDK's clang), so those three ship as the `.py` files scipy provides for exactly this case.
iOS keeps the compiled versions.

Nothing is missing: both platforms expose exactly the same set of modules, and the answers
are identical to the last digit. Only these six entry points are affected, and only in
speed:

| affected call | fallback module |
| --- | --- |
| [`interpolate.RBFInterpolator`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html) | `interpolate/_rbfinterp_pythran.py` |
| [`linalg.funm`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.funm.html), [`linalg.signm`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.signm.html) | `linalg/_linalg_pythran.py` |
| [`stats.somersd`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.somersd.html) | `stats/_stats_pythran.py` |
| [`stats.mstats.siegelslopes`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mstats.siegelslopes.html) | `stats/_stats_pythran.py` |
| [`stats.ks_2samp(method="exact")`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html), unequal sample sizes only | `stats/_stats_pythran.py` |

The cost varies enormously by call. Swapping the compiled module for the exact `.py` file
the Android wheel ships, on the same desktop machine and the same inputs, `RBFInterpolator`
took 50–95× longer, `somersd` 25×, `ks_2samp` 7×, `funm`/`signm` 6× and
`mstats.siegelslopes` 4.5×. Those are desktop ratios, not device ones — treat them as the
shape of the problem, not a number to plan against. Everything *else* in scipy, including
everything the example app uses, is compiled identically on both platforms.

`scipy.fft`'s default worker count is also derived differently on Android — from the total
core count rather than from the process's CPU affinity mask, since bionic has no
`pthread_getaffinity_np`. Pass `workers=` if you care about the exact number.

## Things to know

- **`scipy.odr` is not in these wheels, and it is the only thing missing.** There is no
  Fortran compiler in the cross toolchain, so the build uses scipy's `_without-fortran`
  option. Measured against the desktop wheel of the same version, that removes exactly nine
  module files — [`scipy.odr`](https://docs.scipy.org/doc/scipy/reference/odr.html) and its
  eight submodules — and nothing else; 1085 modules of 1094 remain. `import scipy.odr`
  raises `ModuleNotFoundError: No module named 'scipy.odr'` and `scipy.odr` raises
  `AttributeError: Module 'scipy' has no attribute 'odr'`. Upstream deprecated `scipy.odr`
  in 1.17.0 and will remove it in 1.19.0, pointing users at the standalone
  [`odrpack`](https://pypi.org/project/odrpack/) package — which has no recipe here either,
  and wraps the same Fortran.
- **The same BLAS on both platforms.** OpenBLAS is linked *statically* into scipy's own
  extensions — there is no separate library to load, and iOS does **not** use the system
  Accelerate framework. Numerical results and BLAS version therefore do not drift between
  Android and iOS, or across iOS releases. `scipy.show_config()` on the device reports what
  you actually got.
- **`flet-libopenblas` is a build-time cost only.** It is listed as a runtime dependency of
  the wheel, but there is nothing in it your app runs: what it ships is a ~70 MB static
  archive plus headers, and OpenBLAS is already linked into scipy. `flet build` downloads
  it (~17 MB), installs it, and then deletes it again — Flet's package cleanup strips
  `**.a` and `**.h` and is on by default. You pay build time and disk, not app size. Turn
  `cleanup.packages` off and you will ship all 70 MB of it.
- **Size.** Each wheel is 26–31 MB and unpacks to 76–100 MB depending on architecture
  (iOS arm64: 28 MB and 100 MB). About 18 MB of that unpacked total, on every architecture,
  is scipy's own `tests/` packages, which your app will never import.
- **[`scipy.datasets`](https://docs.scipy.org/doc/scipy/reference/datasets.html) is not
  usable offline.** It needs the optional `pooch` package and downloads on first use,
  caching into `pooch.os_cache("scipy-data")` — not into any of Flet's app-storage
  directories. Bundle the data in `assets/` instead if you need it on device.

## Build notes (maintainers)

Three build flags and three patches, all Android-driven except the first:

- `-D_without-fortran=true` drops the only Fortran left in scipy, which is `scipy.odr`
  wrapping ODRPACK. Everything else Fortran-derived (QUADPACK, FITPACK, ARPACK, the LAPACK
  in OpenBLAS) is already f2c-translated C upstream, or built `NOFORTRAN=1` in the
  `flet-libopenblas` recipe.
- `-Dblas=openblas -Dlapack=openblas` resolve through `flet-libopenblas`'s `openblas.pc`
  on both platforms. iOS deliberately does not use Accelerate: one implementation means one
  set of numerical results and no dependence on the OS release.
- `-Duse-pythran=false` on Android only. pythran 0.18.1's
  `pythonic/types/ndarray.hpp` has an ill-formed ref-qualifier overload the NDK's clang
  rejects; Apple clang accepts it, so iOS keeps pythran. See
  [Android notes](#android-notes) for the six calls this reaches.
- `android-bionic-clog-cpow.patch` supplies `clog`/`cpow`, which bionic only declares from
  API 26, in terms of `log`/`cabs`/`carg`/`cexp`. Because the wheels target API 24 the
  substitutes are compiled in for every Android device regardless of its OS version. They
  are not measurably worse than a real libm: away from the unit circle they agree with a
  50-digit reference to ~1e-13 relative on the real part, and in the one region where they
  do lose digits (`|z|` within ~1e-9 of 1, where `log|z|` cancels) numpy's own complex log
  loses nearly as many.
- `android-ducc-no-affinity.patch` stops vendored ducc from calling the glibc-only
  `pthread_{get,set}affinity_np`. Costs CPU pinning, which is a performance optimisation.
- `android-x86_64-boost-longdouble.patch` routes vendored boost.math to its IEEE binary128
  branch on Android x86_64, whose `long double` is 128-bit rather than the 80-bit the x86
  branch hard-asserts. Without it the build does not compile; with it there is no behaviour
  change, since it selects the branch that matches the target.
