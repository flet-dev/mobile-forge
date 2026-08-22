# pywavelets

[`PyWavelets`](https://pywavelets.readthedocs.io/) is the wavelet transform library for numpy
arrays: [DWT and IDWT](https://pywavelets.readthedocs.io/en/latest/ref/dwt-discrete-wavelet-transform.html)
in 1-D, [2-D](https://pywavelets.readthedocs.io/en/latest/ref/2d-dwt-and-idwt.html) and
[n-D](https://pywavelets.readthedocs.io/en/latest/ref/nd-dwt-and-idwt.html), the
[stationary](https://pywavelets.readthedocs.io/en/latest/ref/swt-stationary-wavelet-transform.html)
(undecimated) transform, the
[continuous](https://pywavelets.readthedocs.io/en/latest/ref/cwt.html) transform,
[wavelet packets](https://pywavelets.readthedocs.io/en/latest/ref/wavelet-packets.html),
[multiresolution analysis](https://pywavelets.readthedocs.io/en/latest/ref/mra.html) and the
[thresholding functions](https://pywavelets.readthedocs.io/en/latest/ref/thresholding-functions.html)
that turn all of it into a three-line denoiser.

On a phone the appeal is how little comes with it. Four small C extensions and numpy, a little
over 4 MB of wheel, and you get on-device denoising of a sensor trace, a coefficient pyramid of
an image, or a time-frequency view of an audio buffer — none of which has to leave the device.

Import it as `pywt`.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pywavelets",
    "numpy",
]
```

[`numpy`](../numpy) is listed explicitly because you cannot use this package without handling
arrays yourself: every input is an ndarray, and every coefficient that comes back is one.

**If you pin `pywavelets==` in your app, raise `requires-python` to `>=3.11`.** The wheels
declare `Requires-Python: >=3.11`, and uv resolves for every version your project claims to
support, not just the interpreter in use — leave the `>=3.10` that `flet create` writes and
`flet build` fails outright with *No solution found when resolving dependencies for split*.

Builds for Android arm64-v8a, armeabi-v7a and x86_64, and for iOS device and simulator, on
Python 3.12, 3.13 and 3.14.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`wavelet-denoise`](examples/wavelet-denoise) — denoises a signal and an image, and proves on
  screen that the transform itself lost nothing.

## Usage in a Flet app

Decompose, reconstruct, show the result:

```python
import flet as ft
import numpy as np
import pywt

coeffs = pywt.wavedec(samples, "db4", level=6)
rebuilt = pywt.waverec(coeffs, "db4")[: samples.size]   # waverec returns an even length
page.add(ft.Text(f"residual {np.max(np.abs(samples - rebuilt)):.1e}"))
```

Everything crossing that boundary is a numpy array. `samples` is an ndarray, `coeffs` is a list
of ndarrays, and the reconstruction is an ndarray — which is why `numpy` is in the snippet
above.

A scalar result goes straight into an [`ft.Text`](https://flet.dev/docs/controls/text/). An
image-shaped one needs encoding first:
[`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src) takes PNG or JPEG bytes,
not an array, and this example keeps its dependencies to Flet, numpy and pywavelets rather than adding one to convert it — an app that already wants an image library can use
[`pillow`](../pillow), published for the same slices. The
[example](examples/wavelet-denoise) carries a small PNG writer built from `zlib` and `struct`
for exactly that.

### Storage

Coefficients are plain arrays, so numpy owns the persistence. Put anything the user expects to
keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
import os

data_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
np.savez_compressed(os.path.join(data_dir, "scan.npz"), *pywt.wavedec(samples, "db4"))
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for a pyramid you can recompute and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch. A recording shipped with the app is an asset: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and reach it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

**The five bundled `pywt.data` datasets read correctly on both platforms as shipped.** They go
through `importlib.resources.as_file`, which materialises a temp copy when the resource lives
in a zip, so `pywt.data.camera()` works the same on iOS, where Flet 0.86 leaves site-packages a
real directory, and on Android, where it serves site-packages as a zip.

That protection covers pywavelets' own files, not yours. Code of your own that locates a data
file relative to `__file__` is on both platforms a different question: with
[`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup) on by default,
`__file__` points at a `.pyc`, and on Android the enclosing directory is inside a zip and the
open fails with `NotADirectoryError: [Errno 20] Not a directory`. Read your own bundled data
through `importlib.resources` too, or from the assets directory.

### Threading

**The transforms release the GIL; wavelet construction does not.** `_dwt`, `_swt` and `_cwt`
reference `PyEval_SaveThread`/`PyEval_RestoreThread` on every shipped slice; `_pywt`, which
builds `Wavelet` objects, does not. Measured on desktop, two threads against one for the same
total work, on 65 536 samples: `dwt` 2.0×, `wavedec` 2.0×, `swt` 2.0×, `cwt` 1.7×, against a
`hashlib.sha256` control at 2.0× and a pure-Python control at 1.0×.

**How far it scales depends on the input size, not on which call you make.** The same
measurement at 4096 samples gives `dwt` 1.8× and `swt` 2.1× but `wavedec` **0.9×** — its
per-level Python loop holds the GIL for longer than the six short C transforms release it — and
at 1024 samples every one of them is ≤1.0×. Threading a small 1-D transform costs more than it
saves.

For scale, desktop best-of-20 on an M-series Mac: `wavedec` of 4096 samples with `db4` at
level 6 is 0.027 ms and the round trip 0.050 ms; `swt` of the same signal at level 4 is
0.079 ms; a `wavedec2`/`waverec2` round trip on 512×512 is 5.1 ms; a 48-scale `cwt` of 4096
samples is 8.6 ms. A phone is several times slower, which is exactly why the 2-D and CWT paths
belong off the UI thread.

Put anything bigger than a short 1-D transform in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end the
handler with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
— auto-update does not reach background threads. `run_thread` also swallows exceptions, so wrap
the body if you want to see a `ValueError` from a bad level rather than a screen that never
changes.

**Nothing in the wheel starts a thread of its own**, so all the concurrency is whatever your app
introduces — and there is no shared handle to serialise, because coefficients are plain numpy
arrays that move between threads freely. `run_thread` still hands work to a pool, so two quick
events can overlap; take a lock around the controls you write, as the example does, if a stale
run must not overwrite a fresh one.

### Choosing a wavelet

**All 127 wavelets are compiled into the extension.** 106 discrete (`haar`, `db1`–`db38`,
`sym2`–`sym20`, `coif1`–`coif17`, 15 `bior`, 15 `rbio`, `dmey`) and 21 continuous
(`gaus1`–`gaus8`, `mexh`, `morl`, `cgau1`–`cgau8`, `cmor`, `shan`, `fbsp`), across 14 families.
Outside `pywt/tests`, the only data files in the wheel are the five demo `.npz`, so the filter
tables travel inside the extension itself and `pywt.wavelist()` returns the same names on both
platforms.

**Round-trip exactness varies by wavelet, and one of them does not invert at all.** Over all
106 discrete wavelets, level 5 on 4096 standard-normal samples, measuring
`max|x - waverec(wavedec(x))| / max|x|` — the relative residual the example puts on screen —
81 land under 1e-14: `haar`, all 38 Daubechies and all 17 coiflets (worst 1.5e-15), `sym9`, and
24 of the 30 biorthogonals. The other 18 symlets run 4e-14 up to **4e-11** for `sym20`, and
`bior4.4`/`bior5.5`/`bior6.8` with their `rbio` twins reach 3e-12; their stored filter
coefficients are truncated decimals. `dmey` is another eight orders of magnitude worse,
**5e-3**, because it is an FIR *approximation* of the Meyer wavelet rather than an exact filter
bank. The figures move by a factor of two or so between random draws, and by about 4× if you
quote the absolute residual instead, so state the metric with any tolerance you assert and key
it to the wavelet you chose. Do not reach for `dmey` where invertibility matters.

**[`cwt`](https://pywavelets.readthedocs.io/en/latest/ref/cwt.html) needs a *continuous*
wavelet, and says so very badly.** Pass any of the 106 discrete names and you get
`AttributeError: 'pywt._extensions._pywt.Wavelet' object has no attribute 'complex_cwt'`, which
names neither the problem nor the fix. Drive any picker from
`pywt.wavelist(kind="continuous")`. Spell the parameters out too — bare `cmor`, `shan` and
`fbsp` are deprecated and print a `FutureWarning` on every call; use `cmor1.5-1.0`,
`shan0.5-1.0`, `fbsp2-1.0-0.5`.

**Nine [boundary modes](https://pywavelets.readthedocs.io/en/latest/ref/signal-extension-modes.html)
ship, and the default expands the coefficients.** With `symmetric` (the default), a
1024-sample level-4 `db4` decomposition produces 1050 coefficients; only `periodization` gives
exactly 1024 — that count is the reason to prefer it for per-band shares. It is not the only
mode that preserves the signal's energy exactly, though: `zero` does too, since zero-extension
adds none. The extending modes do not, and by how much depends on how far the signal disagrees
with its own extension — negligible for a smooth or near-periodic signal, but several percent
for noise (`symmetric` 1.036× and `periodic` 1.044× on standard-normal input at db4 level 4,
n=1024), so a per-band share computed against the signal is off by that much. Normalising the shares
by their own total hides it completely — they will add to 100% in any mode — so divide by the
signal's energy if you want the discrepancy to be visible.

### App size

Each wheel is approximately 4.2–4.4 MB compressed and 7.7–8.6 MB unpacked, depending on the
slice. Only 0.9–1.8 MB of that is the four compiled transforms.

**About 6.0 MB of every slice — 69–77% of the unpacked payload — is `pywt/tests`**, upstream's
own test suite and the MATLAB reference `.npz` files it compares against. No application
imports it, and Flet's
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) can drop it:

```toml
[tool.flet.cleanup]
package_files = ["**pywt/tests"]
```

The missing slash after the leading wildcard is not a typo: serious_python matches each glob
with Dart's `Glob` against the absolute entry path, so `**/pywt/tests` would insist on a
separator there and miss a top-level `pywt/`. The globs also run *after* serious_python has
compiled the package and deleted the `.py` files, which is why the pattern names the directory
rather than `*.py`. **That glob has not been verified against a build for this package** —
check the result before relying on it:

```bash
unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l /tmp/sp.zip | grep pywt
```

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These figures describe the package payload, not the amount
added to the final APK or IPA; packaging and compression determine that.

### Other considerations

**A desktop `flet run` is a fair proxy, except for speed.** The pure-Python layer of these
wheels is byte-identical to PyPI's desktop wheel of the same version apart from `version.py`,
and byte-identical between the Android and iOS wheels, so API behaviour, boundary-mode handling
and coefficient bookkeeping carry over exactly. `pywt/_c99_config.py` reads
`_have_c99_complex = True` on both mobile platforms, so the complex CWT wavelets
(`cgau1`–`cgau8`, `cmor`, `shan`, `fbsp`) behave the same there too. What does not carry over is
timing: validate anything you are budgeting a frame for on a device.

## Things to know

- **`pywt.__version__` reports the wrong number.** Every 1.9.0 wheel — ours and PyPI's desktop
  one — ships a `pywt/version.py` that says `1.8.0`; only `git_revision` differs between them.
  It is upstream's bug, not the recipe's, but it means an app that prints `pywt.__version__` on
  screen shows a version that does not exist on the index. Read
  `importlib.metadata.version("pywavelets")` instead, which returns `1.9.0`.

- **[`waverec`](https://pywavelets.readthedocs.io/en/latest/ref/idwt-inverse-discrete-wavelet-transform.html)
  always returns an even length.** Reconstruct a 1001-sample signal and you get 1002 back, so a
  bare `x - rec` raises instead of reporting the residual. Always slice:
  `pywt.waverec(coeffs, w)[: len(x)]`, and `[:h, :w]` in 2-D.

- **[`swt`](https://pywavelets.readthedocs.io/en/latest/ref/swt-stationary-wavelet-transform.html)
  needs a length divisible by `2**level`, and blames the level when it is not.** A 30-sample
  input at level 2 raises `ValueError: Level value too high (max level for current data size and
  start_level is 1).`; 32 samples works. Clamp with `pywt.swt_max_level(len(x))`, or pad to a
  power of two.

- **The stationary transform is a memory hazard on a phone; `wavedec` is not.** `swt2`
  coefficients come to `4 × level ×` the input, so a level-5 `swt2` of a 1024×1024 float64
  image holds about 168 MB for an 8.4 MB input, and `trim_approx=True` only brings that to
  134 MB. A `wavedec2` pyramid of the same image is 8.4–8.6 MB, about 1.0× the input, with a
  transient peak of roughly 2.7× while the transform runs (desktop measurement). Prefer
  `wavedec2` for images; if you genuinely need shift invariance, keep the level low and cast to
  float32.

- **Integer input is silently promoted to float64.** That bites on exactly the bundled data an
  example reaches for — `pywt.data.ecg()` is `int32` and `camera()` is `uint8`. Cast explicitly
  (`camera().astype(np.float32)`) if you wanted the half-size coefficients; float32 input does
  give float32 coefficients.

- **Demo data ships inside the wheel, so an example needs no asset and no download.**
  `ascent()`, `aero()` and `camera()` are 512×512 `uint8` images, `ecg()` is 1024 `int32`
  samples, `nino()` is a 264-point sea-surface-temperature series — 0.64 MB of `.npz` in total
  — and
  [`demo_signal`](https://pywavelets.readthedocs.io/en/latest/ref/other-functions.html#pywt.data.demo_signal)
  generates 20 classic test signals in pure numpy with no file at all. `Gabor` and
  `sineoneoverx` reject an explicit length outright; call them with none and you get their
  natural 512 and 1024. `Riemann` accepts one but raises `IndexError` at some lengths — 512 and
  8192 fail where 1024, 2048 and 4096 work — so validate before wiring `demo_signal` to a
  picker.

## Build notes (maintainers)

### Recipe shape

The whole recipe is a short `meta.yaml` and four tests: no patches — there never have been —
and no `build.sh`. Nothing else was needed because the package is genuinely self-contained: its
C is its own, and the undefined symbols in the built extensions are only the
`malloc`/`memcpy`/`sin`/`cos`/`pow` class — **no `cpow`, `clog` or `cexp`** — which is why
`_have_c99_complex = True` holds at Android API 24 with none of the bionic complex-math
workarounds `scipy` needs.

`pywt/tests` is left in the wheel deliberately. Stripping it would shrink every slice by about
6.0 MB, but it takes a patch, and patch-free is what makes bumps here cheap. The consumer-side
`[tool.flet.cleanup]` glob documented under [App size](#app-size) gets the same payload
reduction without that cost; revisit the trade only if that glob turns out not to work.

### Upgrade hazards

- **`pywt.__version__`.** The 1.8.0-in-a-1.9.0-wheel mismatch is upstream's; if a later release
  fixes it, that Things-to-know bullet should go rather than be updated. Do not add a version
  assert to `tests/` while it stands.
- **The `importlib.resources` read in `pywt/data/_readers.py`** is the only reason Android needs
  no [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry. It
  holds while the five `.npz` stay behind `importlib.resources` and nothing new opens a bundled
  file by path. `pywt/_pytest.py:54` already does a `__file__`-relative read of `pywt/tests/data`
  — harmless because only the test suite imports it, and the reason to check at each bump that
  no such read has moved into the package proper.
- **iOS Mach-O filetype.** These wheels predate forge's `MH_BUNDLE → MH_DYLIB` converter, so
  meson-python's iOS link is producing dylibs on its own rather than being fixed up afterwards.
  A toolchain change could take that away, and the symptom is a link failure in the consumer's
  `flet build ipa`, not a failure here.

### Re-verification checklist

Re-checked against the six published cp314 wheels on 2026-08-22 and held: the `_c99_config`
flag, the Mach-O filetypes, the Android `DT_NEEDED` list and segment alignment, the
threading-symbol scan, and every size in the table. The two items below that name a prior pass
were not re-run.

- **`_have_c99_complex` in the built wheel**, on both platforms. If it flips to `False` the
  build stays green, the complex CWT wavelets silently stop working, and only a device run
  notices. The supporting fact is the undefined-symbol set: no `cpow`, `clog` or `cexp` in any
  of the 24 cp314 extensions, on either platform.
- **Mach-O filetype on the three iOS slices** — `otool -hv` reports `DYLIB` for all twelve
  extensions (four per slice). A `BUNDLE` fails at the consumer's link, not here.
- **Android `DT_NEEDED` and segment alignment** — `llvm-readelf -d` shows only
  `libpython3.X.so`, `libc.so` and, for `_cwt` and `_pywt`, `libm.so`; no NDK C++ runtime, so no
  `flet-libcpp-shared` tags along. Every `PT_LOAD` is `0x4000`-aligned, which is what Android 15
  devices with 16 KB pages require.
- **No thread of its own** — no `pthread_create`, `omp_*` or `GOMP_*` among the dynamic symbols
  of any of the 24 cp314 extensions. Rescan on a bump before leaving the Threading section
  standing.
- **Android zipped site-packages.** The claim was established by loading all five `.npz` out of
  a stored `sitepackages.zip` through `zipimport`, with the extensions resolved off disk by a
  `.soref`-style finder, alongside a control module in the same zip reading its data by
  `__file__`, which failed there with the expected `NotADirectoryError: [Errno 20] Not a
  directory`. A built APK of the [`wavelet-denoise`](examples/wavelet-denoise) example matched
  that topology exactly: all five `.npz` stored inside `assets/sitepackages.zip`, the four
  extensions moved to `lib/<abi>/libpywt-_extensions-_*.so` behind their `.soref` markers, and
  `assets/extract.zip` the 22-byte empty archive that means no package was extracted.
- **The wavelet inventory.** The `wavelist()` counts and per-family breakdown quoted above are
  asserted nowhere; re-derive them. The 14 family names are plain strings in `_pywt`, but the
  106 discrete filter tables are numeric — a prior pass located every one of them inside the
  shipped `_pywt` on all six slices, and that scan is what backs the "compiled in" claim.
- **All sizes, per slice, decimal.** Re-measure from the wheels rather than scaling old numbers,
  and do not use `du`, which is binary and will read a correct figure as a regression:

  ```bash
  curl -sLO <wheel-url>
  stat -f%z <wheel>                                                    # compressed bytes
  unzip -l <wheel> | tail -1                                           # unpacked total
  unzip -l <wheel> | grep 'pywt/tests/' | awk '{s+=$1} END {print s}'  # the tests share
  ```

  cp314, in MB, as measured on 2026-08-22:

  | | wheel | unpacked | `pywt/_extensions` | `pywt/tests` |
  | --- | ---: | ---: | ---: | ---: |
  | Android arm64-v8a | 4.27 | 8.18 | 1.37 | 5.95 |
  | Android armeabi-v7a | 4.18 | 7.70 | 0.88 | 5.95 |
  | Android x86_64 | 4.28 | 8.17 | 1.35 | 5.95 |
  | iOS device arm64 | 4.31 | 8.61 | 1.79 | 5.95 |
  | iOS simulator arm64 | 4.35 | 8.61 | 1.79 | 5.95 |
  | iOS simulator x86_64 | 4.32 | 8.40 | 1.58 | 5.95 |

  armeabi-v7a is the 32-bit slice, and the `swt2` memory figures under
  [Things to know](#things-to-know) matter most there.

### Coverage gaps

`tests/test_pywavelets.py` exercises four things: `dwt`/`idwt`, `wavedec`/`waverec`, `swt`/`iswt`
and a complex `cwt`. Nothing on device touches `wavedec2`/`waverec2`, `pywt.threshold`,
`pywt.data` (the `importlib.resources` read out of Android's zipped site-packages), or
`wavelist()` completeness — all of which the sections above make claims about, resting on wheel
inspection and on the example app rather than on a test. Adding tests for those four is the
single highest-value change to this recipe.
