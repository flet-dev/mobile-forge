# numpy

[`numpy`](https://numpy.org/) is the array library the rest of scientific Python is built
on: one contiguous typed buffer per array, and whole-array operations that run as compiled
loops instead of Python ones. That is what makes serious computation affordable on a phone
— the interpreter never sees an individual element, so a hundred thousand of them cost one
call instead of a hundred thousand.

## Install

Add numpy to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "numpy",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`bell-curve`](examples/bell-curve) — averages uniform random draws until a bell curve
  appears, and bins it.

## Usage in a Flet app

Build the array, do the work in one whole-array call, and cast the result to a plain Python
value on its way into a control such as [`ft.Text`](https://flet.dev/docs/controls/text/):

```python
import flet as ft
import numpy as np

samples = np.random.default_rng().random((100_000, 12)).mean(axis=1)
spread = float(samples.std())  # float(), because .std() returns an np.float64

page.add(ft.Text(f"{samples.size:,} samples, std dev {spread:.4f}"))
```

### Storage

[`np.save`](https://numpy.org/doc/stable/reference/generated/numpy.save.html) writes one
array to a `.npy` file and
[`np.load`](https://numpy.org/doc/stable/reference/generated/numpy.load.html) reads it back
with dtype and shape intact. Arrays the user expects to keep belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
data_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
np.save(os.path.join(data_dir, "history"), history)  # writes history.npy
history = np.load(os.path.join(data_dir, "history.npy"))
```

`np.save` appends `.npy` unless the name already ends in it, so the path you write is not
always the path you load. Use
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for arrays you can recompute and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for intermediates. Reach for
[`np.savetxt`/`np.loadtxt`](https://numpy.org/doc/stable/reference/generated/numpy.savetxt.html)
only when something outside the app has to read the file: text is several times larger and
much slower to parse.

An array shipped with the app is an asset: put the `.npy` in the
[assets directory](https://flet.dev/docs/cookbook/assets) and open it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).
On Android the app's Python code stays inside a zip, so a data file dropped next to your own
module is not a file at all and opening it fails with `NotADirectoryError`. numpy itself
reads nothing from disk, at import or in normal use, so the package runs from that zip as
shipped and needs no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry — but
your `.npy` has to live in assets or app storage, which are real directories.

[`np.memmap`](https://numpy.org/doc/stable/reference/generated/numpy.memmap.html) and
`np.load(path, mmap_mode="r")` map a file rather than reading it, so an array larger than
you want in memory can be sliced a piece at a time; both need a real path for the same
reason. `np.load` also refuses object arrays by default, with
`ValueError: Object arrays cannot be loaded when allow_pickle=False`. A numeric dtype keeps
the file a plain buffer; `allow_pickle=True` is unpickling, so keep it to files your own app
wrote.

### Threading

**Nothing in these wheels starts a thread, and nothing in them uses more than one core.**
Desktop numpy hands `@` and `numpy.linalg` to a multi-threaded BLAS; there is no BLAS here
at all (see [Linear algebra](#linear-algebra)), so `OPENBLAS_NUM_THREADS` and
`OMP_NUM_THREADS` have nothing to act on. Everything scales with clock speed, not core count.

You can still use threads yourself: numpy releases the GIL around its large loops, and
arrays move between threads with no handle to serialise — though two threads writing into
one array is a data race numpy will not notice. Numerics on the UI thread freeze the UI, so
push anything non-trivial to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update); auto-update does
not reach background threads.

### Linear algebra

**There is no BLAS or LAPACK behind these wheels, and
[`numpy.linalg`](https://numpy.org/doc/stable/reference/routines.linalg.html) works
anyway.** numpy is built `-Dblas=none -Dlapack=none` and compiles the f2c-translated
reference LAPACK it bundles instead. `solve`, `inv`, `det`, `svd`, `eig`, `eigh`, `qr`,
`cholesky`, `pinv`, `lstsq`, `matrix_rank`, `norm`, `einsum`, `tensordot` and `@` are all
there, and on identical inputs all agree with a BLAS-backed desktop build to within 4e-13.

What you lose is speed, on one family of operations: matrix products and decompositions,
growing with matrix size and worst by far for `A @ B`. Elementwise maths, reductions,
sorting, FFTs, random number generation, indexing and broadcasting never touched BLAS on any
platform. Keep the matrices small and it does not come up.

**If the linear algebra is the point, use scipy.** The [`scipy`](../scipy) wheels on this
index link a full OpenBLAS statically into their own `_fblas`/`_flapack` extensions, and
[`scipy.linalg`](https://docs.scipy.org/doc/scipy/reference/linalg.html) reaches it through
`get_lapack_funcs` rather than calling back into numpy, so `solve`, `inv`, `svd`, `eigh` and
`qr` there really are a separate, faster path. That OpenBLAS is built single-threaded, so
what it wins is kernel quality, not cores. It does not change `@`, which is numpy's operator
whatever else is installed: for a large matrix product call
`scipy.linalg.blas.dgemm(1.0, a, b)` instead.

### Precision

**`long double` is 128 bits wide on 64-bit Android and 64 bits wide everywhere else**,
which makes [`numpy.longdouble`](https://numpy.org/doc/stable/reference/arrays.scalars.html#numpy.longdouble)
the one type in numpy whose precision depends on which phone the app is running on. The
width comes from the platform's C ABI, not from a choice this recipe makes:

| target | `long double` | `numpy.longdouble` |
| --- | --- | --- |
| Android arm64-v8a, x86_64 | 16 bytes, IEEE quad | true quad precision |
| Android armeabi-v7a | 8 bytes | a second name for double precision |
| iOS arm64 — every device, and the simulator on Apple Silicon | 8 bytes | a second name for double precision |

So an extended-precision calculation that works on a 64-bit Android phone silently drops to
`float64` on iOS and on 32-bit Android — no error, no warning, just fewer digits. And the
aliases numpy derives from the width are there on some targets only:
[`numpy.float128`](https://numpy.org/doc/stable/reference/arrays.scalars.html#numpy.float128)
and `numpy.complex256` exist on 64-bit Android and do not exist at all on iOS or
armeabi-v7a, where `np.float128` raises `AttributeError`. `numpy.longdouble` is always
defined, so write that, and treat anything beyond `float64` as a bonus rather than something
to depend on.

### App size

Approximately 6.5–8.2 MB compressed and 19–27 MB unpacked per architecture. About 6.6 MB of
that unpacked payload — about 30% of a 22 MB arm64-v8a wheel, across 490 files — is numpy's own `tests`
packages, which nothing imports unless you call `np.test()`, and which Flet's default
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) leaves alone
because it strips headers, static archives and `__pycache__`, not tests:

```toml
[tool.flet.cleanup]
package_files = ["numpy/tests", "numpy/*/tests"]
```

Two patterns because most subpackages keep tests of their own, and `numpy/testing`, which is
public API, matches neither. On Android, also use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. These are package figures, not the amount added to
the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel, which differs from this build in the two
ways this page has been about.

It has a BLAS — Accelerate or OpenBLAS, and a multi-threaded one — so any `@` or
`numpy.linalg` timing taken under `flet run` says nothing about the device.

Its `long double` differs from the device's in both directions: 8 bytes on an Apple Silicon
Mac, where `np.float128` therefore does not exist; 80-bit extended on an Intel Mac or Linux
desktop, where it does; IEEE quad on a 64-bit Android phone. Neither the presence nor the
absence of that name on your laptop predicts the phone.

Ask the wheel rather than the machine, or this page:
[`numpy.show_config()`](https://numpy.org/doc/stable/reference/generated/numpy.show_config.html)
runs on device and reports `blas: none`, `lapack: none` and `cross-compiled: True`,
`numpy.show_config(mode="dicts")` returns the same as a dict, and
`np.dtype(np.longdouble).itemsize` is the width in bytes.

## Things to know

- **Nothing has been removed.** The mobile wheels ship the same modules as the desktop wheel
  of the same version — every subpackage, including
  [`fft`](https://numpy.org/doc/stable/reference/routines.fft.html),
  [`random`](https://numpy.org/doc/stable/reference/random/index.html), `polynomial`, `ma`,
  `strings` and [`f2py`](https://numpy.org/doc/stable/f2py/) — and only the extension
  filenames differ. `f2py` needs a Fortran compiler to be of any use, so on a phone it is
  there to import rather than to run — and nothing in the wheel is itself Fortran, since the
  bundled LAPACK was translated to C by f2c upstream.

- **A numpy scalar is not a Python one, and exactly one of them pretends otherwise.**
  `np.float64` subclasses `float` and passes anywhere a float does, which is what makes the
  rest surprising: `np.int64`, `np.int32`, `np.float32` and `np.bool_` subclass nothing, and
  `json.dumps(np.int64(3))` raises
  `TypeError: Object of type int64 is not JSON serializable`. Indexing an array or calling
  `.max()` hands you one of those, so cast where the value leaves the array —
  [`.item()`](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.item.html) or
  `int(...)`/`float(...)` for one value,
  [`.tolist()`](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.tolist.html)
  for a whole array — not in the control that receives it.

- **An array is a single allocation, and a slice keeps all of it alive.** A 100,000 × 12
  `float64` array is 9.6 MB in one contiguous block;
  [`arr.nbytes`](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.nbytes.html)
  is the number to read and `sys.getsizeof` is not — on a slice it answers 112 bytes while
  the parent buffer stays in memory. That is how a handful of small-looking arrays becomes
  hundreds of megabytes on a phone. Take `.copy()` of the piece you keep, and drop to
  `float32` where the precision allows: same shape, half the memory.

## Build notes (maintainers)

### Recipe shape

A plain meson-python source build — no `build.sh`, no PEP 517 shim, no native library of its
own. The decision worth recording is what it is *not*: numpy is deliberately not a
`flet-libopenblas` consumer, the way [`scipy`](../scipy) on this index is. Staying on the
bundled reference LAPACK keeps the recipe free of a native-library chain and of every runtime
dependency except `flet-libcpp-shared` on Android, the NDK C++ runtime that two of numpy's
nineteen extensions (`_multiarray_umath` and `_pocketfft_umath`) link against; the iOS wheel
has none. It also keeps the wheels small: a desktop macOS wheel of the same version bundles
OpenBLAS, libgfortran, libquadmath and libgcc under `numpy/.dylibs`, which is most of why it
is around 15 MB where these are 7 MB. Reversing the decision changes the recipe's shape
rather than a flag — a `host` requirement, an entry in `Requires-Dist`, and most of
[Linear algebra](#linear-algebra) rewritten.

The cost is bounded. Building numpy twice on one desktop Mac from the same sources, once
against Accelerate and once with the `-Dblas=none -Dlapack=none` this recipe uses:

| operation | 128×128 | 384×384 |
| --- | --- | --- |
| `A @ B` (matmul) | 22× slower | 172× slower |
| `A @ v` (matrix-vector) | 3.7× | 33× |
| `linalg.inv` | 6.5× | 14× |
| `linalg.qr` | 2.7× | 11× |
| `linalg.solve`, `det` | 3.7–4.2× | 10× |
| `linalg.svd`, `eigh`, `pinv` | 3.0–3.8× | 8–13× |
| `exp`, `sin`, `sum`, `sort`, `fft` | 1.0× | 1.0× |

Those are desktop ratios against a multi-threaded BLAS: the shape of the trade, not numbers
to plan against, and not quotable at a consumer as device figures without a device
measurement behind them.

### Upgrade hazards

The table above, and the scipy comparison in [Linear algebra](#linear-algebra), measure
reference LAPACK against an optimised BLAS rather than a particular numpy release. Reread
them on a bump instead of re-measuring — unless numpy replaces the bundled `lapack_lite`,
which turns them back into a measurement job.

[Other considerations](#other-considerations) and the example app both quote the layout of
`numpy.show_config(mode="dicts")` (`Build Dependencies` → `blas` → `name`), which numpy owns
and can restructure. The example guards that lookup, so a change surfaces as the word
`unknown` in its header line rather than a blank screen; treat it as the signal to re-check
the prose.

### Re-verification checklist

Everything above this section is a claim about one build of numpy, and a bump can falsify
any of it without the build failing. Against the wheels the bump produces, re-verify:

- **That there is still no BLAS.** meson errors on an unknown project option, so a rename of
  `blas`/`lapack` announces itself; a BLAS that quietly comes back does not. Confirm
  `show_config()` on device still says `blas: none`, then check what consumers rely on: no
  undefined `cblas_*` symbol in `_multiarray_umath`, and `linalg/lapack_lite` still the real
  f2c LAPACK — of the order of a megabyte, routine names in its own text — not the few tens
  of KB of shim a system-BLAS build produces. This check is manual; the device tests only
  assert that `numpy.linalg` is *correct*.
- **`longdouble_format`.** numpy normally settles it by compiling *and running* a probe,
  which a cross build cannot do. A missing value fails loudly; a wrong one does not, and
  yields a wheel whose `longdouble` disagrees with the platform ABI. Re-derive it on any NDK
  or iOS SDK move as well as on a numpy bump — `clang -dM -E` reports `__LDBL_MANT_DIG__`
  113 for `aarch64-linux-android` and `x86_64-linux-android`, 53 for
  `armv7a-linux-androideabi`, `i686-linux-android` and `arm64-apple-ios` — and confirm
  `_numpyconfig.h` in each wheel agrees. The whole [Precision](#precision) table follows.
- **The threading promise**, which [Threading](#threading) makes unconditionally. Re-scan
  every extension in every wheel for `pthread_create` and OpenMP symbols (`omp_*`, `GOMP_*`).
  A release that adds a threaded path breaks that section without breaking the build.
- **The counts and sizes**, all per-version: nineteen extensions, two of them linking the NDK
  C++ runtime; the file list matching the same-version desktop wheel module for module; the
  compressed and unpacked ranges; and the 6.6 MB across 490 files of `tests` that makes the
  [App size](#app-size) snippet worth pasting. Total the bytes rather than reading `du -h`,
  whose binary units make a decimal figure look like a regression, and re-run the cleanup
  globs against a staged tree if numpy moves a test package.
- **The absence of an `extract_packages` entry**, which holds only while numpy reads no data
  file from disk. The Android device run is that check: while it passes with no entry, the
  claim stands.

### Coverage gaps

`tests/test_numpy.py` runs five tests on device: elementwise arithmetic, a 500×500 matmul, an
FFT round trip (also the canary for the Android `libc++_shared` dependency), `solve`,
`eigvalsh` and `svd` without an external BLAS, and the `longdouble` width paired with the
presence of `np.float128`. Nothing exercises a `np.save`/`np.load` round trip against app
storage, `mmap_mode` or `np.memmap`, `np.savetxt`/`np.loadtxt`, the `allow_pickle` refusal,
`np.get_include()`, `f2py`, or the `show_config` dict layout quoted above. Those rest on
inspection and on the example app; a green run is not cover for them.
