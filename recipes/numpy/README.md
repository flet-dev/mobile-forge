# numpy

[`numpy`](https://numpy.org/) is the array library the rest of scientific Python is built
on: one contiguous typed buffer per array, and whole-array operations that run as compiled
loops instead of Python ones. That is what makes serious computation affordable on a phone
— the interpreter never sees an individual element, so a hundred thousand of them cost one
call instead of a hundred thousand. Much of the rest of this index sits on top of it —
scipy, pandas, scikit-learn, opencv-python, pyarrow and matplotlib among them — so if you
install any of those you already have numpy.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "numpy",
]
```

Nothing else to configure. On Android one extra wheel comes along and needs no entry of its
own: `flet-libcpp-shared`, the NDK C++ runtime that two of numpy's nineteen extensions
(`_multiarray_umath` and `_pocketfft_umath`) link against. On iOS the wheel has no runtime
dependencies at all.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed either: numpy reads no data file from disk at import or in normal use, so
it runs as-is out of Android's zipped site-packages.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for
iOS, on Python 3.12, 3.13 and 3.14.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`bell-curve`](examples/bell-curve) — averages uniform random draws until a bell curve
  appears, and bins it.

## Threading

**Nothing in these wheels starts a thread, and nothing in them uses more than one core.**
None of the nineteen extensions references `pthread_create` or any OpenMP symbol, on either
platform. Desktop numpy hands `@` and `numpy.linalg` to a multi-threaded BLAS; there is no
BLAS here at all (see [Things to know](#things-to-know)), so `OPENBLAS_NUM_THREADS` and
`OMP_NUM_THREADS` have nothing to act on. Everything scales with clock speed, not with core
count.

You can still use threads yourself — numpy releases the GIL around its large loops, and
arrays and results move between threads freely with no handle to serialise. Numerics on the
UI thread freeze the UI, so push anything non-trivial to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads.

## Android notes

**`long double` is 128 bits wide on 64-bit Android and 64 bits wide everywhere else**,
which makes [`numpy.longdouble`](https://numpy.org/doc/stable/reference/arrays.scalars.html#numpy.longdouble)
the one type in numpy whose precision depends on which phone the app is running on. The
width comes from the platform's C ABI, not from a choice this recipe makes:

| target | `long double` | `numpy.longdouble` |
| --- | --- | --- |
| Android arm64-v8a, x86_64 | 16 bytes, IEEE quad | true quad precision |
| Android armeabi-v7a | 8 bytes | a second name for double precision |
| iOS arm64 — every device, and the simulator on Apple Silicon | 8 bytes | a second name for double precision |

Two things follow. First, an extended-precision calculation that works on a 64-bit Android
phone silently drops to `float64` precision on iOS and on 32-bit Android — no error, no
warning, just fewer digits. Second, the aliases numpy derives from the width are there on
some targets and missing on others:
[`numpy.float128`](https://numpy.org/doc/stable/reference/arrays.scalars.html#numpy.float128)
and `numpy.complex256` exist on 64-bit Android, and on iOS arm64 and armeabi-v7a they do
not exist at all — `np.float128` raises `AttributeError`. (numpy registers `float<bits>`
from `dtype(longdouble).itemsize * 8`; at 8 bytes that name comes out as `float64`, which
is already taken.) `numpy.longdouble` itself is always defined, so write that, and treat
anything it gives you beyond `float64` as a bonus rather than something to depend on.

## Things to know

- **There is no BLAS or LAPACK behind these wheels, and
  [`numpy.linalg`](https://numpy.org/doc/stable/reference/routines.linalg.html) works
  anyway.** numpy is built `-Dblas=none -Dlapack=none`, which is not the same as building
  it crippled: numpy then compiles its own bundled f2c-translated reference LAPACK into
  `linalg/lapack_lite` and `linalg/_umath_linalg` — 1.2 MB and 1.3 MB here, against 52 KB
  and 152 KB for the same two files in the Accelerate-backed desktop wheel, where they are
  thin forwarding shims and the real code lives in the OS.
  `solve`, `inv`, `det`, `slogdet`, `svd`, `eig`, `eigvals`, `eigh`, `qr`, `cholesky`,
  `pinv`, `lstsq`, `matrix_rank`, `cond`, `norm`, `matrix_power`, `tensorsolve`, `matmul`,
  `dot`, `inner`, `vdot`, `einsum` and `tensordot` all work, and all of them agree with the
  BLAS-backed desktop build: run side by side on identical inputs, the worst relative
  difference across those 23 entry points was 4e-13. What you lose is speed, and only on
  one family of operations.
- **How much speed.** Building numpy twice on the same desktop Mac from the same sources —
  once against Accelerate, once with the `-Dblas=none -Dlapack=none` this recipe uses — and
  timing identical inputs:

  | operation | 128×128 | 384×384 |
  | --- | --- | --- |
  | `A @ B` (matmul) | 22× slower | 172× slower |
  | `A @ v` (matrix-vector) | 3.7× | 33× |
  | `linalg.inv` | 6.5× | 14× |
  | `linalg.qr` | 2.7× | 11× |
  | `linalg.solve`, `det` | 3.7–4.2× | 10× |
  | `linalg.svd`, `eigh`, `pinv` | 3.0–3.8× | 8–13× |
  | `exp`, `sin`, `sum`, `sort`, `fft` | 1.0× | 1.0× |

  Those are desktop ratios against a multi-threaded BLAS, so read them as the shape of the
  problem rather than numbers to plan against. The shape is what matters: the penalty is
  confined to matrix products and decompositions, it grows with matrix size, and
  `A @ B` is far and away the worst of it — a blocked, cache-aware GEMM beats a plain
  triple loop by more than a blocked decomposition beats its textbook form. Everything
  else in numpy —
  elementwise maths, reductions, sorting, FFTs, random number generation, indexing,
  broadcasting — never touched BLAS on any platform and is exactly as fast here as it is
  on your desktop.
- **If the linear algebra is the point, use scipy.** The
  [`scipy`](../scipy) wheels on this index link a full OpenBLAS statically into their own
  `_fblas`/`_flapack` extensions, and
  [`scipy.linalg`](https://docs.scipy.org/doc/scipy/reference/linalg.html) reaches it
  directly through `get_lapack_funcs` rather than calling back into numpy — so it really is
  a separate, faster path, not a wrapper over the same slow one. On the same desktop
  machine, with numpy forced through the bundled `lapack_lite` these wheels use,
  `scipy.linalg` was 5–16× faster than `numpy.linalg` for `solve`, `inv`, `svd`, `eigh` and
  `qr` on a 384×384 matrix, and agreed with it to 1e-13. Expect less of a gap on device,
  where scipy's OpenBLAS is single-threaded. One thing scipy does not fix is `@`, which is
  numpy's operator whatever else is installed: for a large matrix product call
  `scipy.linalg.blas.dgemm(1.0, a, b)` instead — 100× faster than `a @ b` in the same
  desktop process.
- **Nothing has been removed.** The mobile wheels ship exactly the same 911 files as the
  desktop macOS wheel of the same version, module for module — every subpackage, including
  [`fft`](https://numpy.org/doc/stable/reference/routines.fft.html),
  [`random`](https://numpy.org/doc/stable/reference/random/index.html), `polynomial`, `ma`,
  `strings` and [`f2py`](https://numpy.org/doc/stable/f2py/). Only the extension filenames
  differ. `f2py` is a Fortran-to-Python source generator and needs a Fortran compiler to be
  of any use, so on a phone it is there to import rather than to run. (Nothing in the
  wheel itself is Fortran: the bundled LAPACK was translated to C by f2c upstream, which is
  what makes `-Dblas=none` viable in a toolchain that has no Fortran compiler.) The one
  thing the mobile wheels lack that a desktop wheel may carry is the bundled library
  directory: the macOS 11 wheel ships OpenBLAS, libgfortran, libquadmath and libgcc under
  `numpy/.dylibs`, which is most of why it is 15 MB where these are 7 MB.
- **Ask the wheel rather than trusting this page.**
  [`numpy.show_config()`](https://numpy.org/doc/stable/reference/generated/numpy.show_config.html)
  runs on device and reports `blas: none`, `lapack: none` and `cross-compiled: True`;
  `numpy.show_config(mode="dicts")` gives you the same thing as a dict, which is what the
  example app puts in its header line.
- **Size.** The wheel is 6.5–8.2 MB depending on architecture and unpacks to 21–28 MB
  (Android arm64-v8a: 6.8 MB and 24 MB). About 6.6 MB of that unpacked total — 30% of it,
  490 files — is numpy's own `tests` packages, which your app will never import. Another
  0.9 MB is the C headers and the `libnpymath.a`/`libnpyrandom.a` static libraries that
  exist so *other* extensions can build against numpy.

## Build notes (maintainers)

The recipe carries no patches for the current version: `mobile-1.26.4.patch` is gated to
numpy < 2.0, where it forced numpy's vendored meson to link extensions with `-dynamiclib`
instead of `-bundle`. Forge's `fix_wheel` now converts `MH_BUNDLE` to `MH_DYLIB` itself,
so 2.x needs nothing. Three build settings remain:

- `-Dblas=none -Dlapack=none` leave numpy on its bundled f2c reference LAPACK, so nothing
  here depends on `flet-libopenblas` — neither at build time nor in `Requires-Dist`. The
  consumer-visible consequences are in [Things to know](#things-to-know); verify them
  against the wheel by checking that `_multiarray_umath` has no `cblas_*` undefined symbol
  and that `lapack_lite` carries the LAPACK routine names in its own text (it does, on both
  platforms).
- `meson.properties.longdouble_format` is not optional. numpy detects the format by
  compiling *and running* a probe program (`numpy/_core/meson.build`), which meson cannot
  do on a cross build; without the property the configure step fails with `Unknown long
  double format`. The values follow the NDK's and Apple's own ABIs — `clang -dM -E` reports
  `__LDBL_MANT_DIG__` 113 for `aarch64-linux-android` and `x86_64-linux-android`, 53 for
  `armv7a-linux-androideabi`, `i686-linux-android` and `arm64-apple-ios` — and the shipped
  wheels' `_numpyconfig.h` matches. Note that the Jinja conditional is written on `#`
  comment lines: Jinja runs before the YAML parser, so the branch not taken never reaches
  YAML, and only one `longdouble_format` key survives.
- `NPY_DISABLE_SVML=1` is inherited from the numpy 1.x recipe and does nothing for 2.x.
  numpy's meson build does not read that environment variable (the knob is now
  `-Ddisable-svml`), and it gates SVML on `host_machine.system() == 'linux'` and
  `cpu_family == 'x86_64'` with AVX-512, which no Android or iOS target can ever satisfy.
  Nothing is lost by it and nothing would be lost by dropping it.
