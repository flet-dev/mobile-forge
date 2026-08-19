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

On a phone the appeal is what it does *not* need. Four small C extensions and numpy: no BLAS,
no C++ runtime, no companion native library, no data files to download, no network. About
4 MB of wheel buys on-device denoising of a sensor trace, a coefficient pyramid of an image,
or a time-frequency view of an audio buffer — none of which has to leave the device.

Import it as `pywt`.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pywavelets",
]
```

`numpy` comes along automatically — it is the *only* thing the wheel requires
(`Requires-Dist: numpy<3,>=1.25`, on every slice). Add it to your own list only if your code
imports it directly. There is no `flet-lib*` companion package.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed, and no `[tool.flet.android] target_arch` restriction either: all three Android
ABIs are published. See [Android notes](#android-notes) for why the bundled data files survive
Android's zipped site-packages.

Builds for Android arm64-v8a, armeabi-v7a and x86_64, and for iOS device and simulator, on
Python 3.12, 3.13 and 3.14.

**If you pin `pywavelets==` in your app, raise `requires-python` to `>=3.11`.** The wheels
declare `Requires-Python: >=3.11`, and uv resolves for every version your project claims to
support, not just the interpreter in use — leave the `>=3.10` that `flet create` writes and
`flet build` fails outright with *No solution found when resolving dependencies for split*.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`wavelet-denoise`](examples/wavelet-denoise) — denoises a signal and an image, and proves on
  screen that the transform itself lost nothing.

## Threading

**The transforms release the GIL; wavelet construction does not.** `_dwt`, `_swt` and `_cwt`
reference `PyEval_SaveThread`/`PyEval_RestoreThread` on every shipped slice; `_pywt`, which
builds `Wavelet` objects, does not. Measured on desktop, two threads against one for the same
total work, on 65 536 samples: `dwt` 2.0×, `wavedec` 2.0×, `swt` 2.0×, `cwt` 1.7×, against a
`hashlib.sha256` control at 2.0× and a pure-Python control at 1.0×.

**How far it scales depends on the input size, not on which call you make.** The same
measurement at 4096 samples gives `dwt` 1.8× and `swt` 2.1× but `wavedec` **0.9×** — its
per-level Python loop holds the GIL for longer than the six short C transforms release it — and
at 1024 samples every one of them is ≤1.0×. Threading a small 1-D transform costs more than it
saves; the sizes worth handing to a thread are the ones in the paragraph below.

**Nothing in the wheel starts a thread of its own.** No shipped extension references
`pthread_create` or any OpenMP symbol — checked over all 72, four per wheel on every published
slice — so all the concurrency is whatever your app introduces, and there is no shared handle to
serialise: coefficients are plain numpy arrays that move between threads freely.

Put anything bigger than a short 1-D transform in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end the
handler with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
— auto-update does not reach background threads. `run_thread` also swallows exceptions, so wrap
the body if you want to see a `ValueError` from a bad level rather than a screen that never
changes.

For scale, desktop best-of-20 on an M-series Mac: `wavedec` of 4096 samples with `db4` at
level 6 is 0.027 ms and the round trip 0.050 ms; `swt` of the same signal at level 4 is
0.079 ms; a `wavedec2`/`waverec2` round trip on 512×512 is 5.1 ms; a 48-scale `cwt` of 4096
samples is 8.6 ms. A phone is several times slower, which is exactly why the 2-D and CWT paths
belong off the UI thread.

## Android notes

The extensions link their slice's `libpython3.X.so`, `libc.so` and — for `_cwt` and `_pywt` —
`libm.so`, and nothing else. No NDK C++ runtime, so no `flet-libcpp-shared` tags along. Every
`PT_LOAD` segment is 16 KB-aligned, so the wheels load on Android 15 devices with 16 KB pages.

Flet 0.86 serves Android site-packages as a zip, which breaks any package that opens a bundled
data file by path. pywavelets' five `.npz` demo datasets are read through
`importlib.resources.as_file`, which materialises a temp copy when the resource lives in a zip,
so they need no `extract_packages` entry — and `pywt/_pytest.py` is the only `__file__`-relative
read left in the tree, imported by the bundled test suite alone. Confirmed by loading all five
out of a stored `sitepackages.zip` through `zipimport`, with the extensions resolved off disk by
a `.soref`-style finder, alongside a control module in the same zip that reads its data by
`__file__` and fails there with the expected
`NotADirectoryError: [Errno 20] Not a directory`. A built APK of the
[`wavelet-denoise`](examples/wavelet-denoise) example matches that topology exactly: all five
`.npz` sit stored inside `assets/sitepackages.zip`, the four extensions have moved to
`lib/<abi>/libpywt-_extensions-_*.so` behind their `.soref` markers, and
`assets/extract.zip` is the 22-byte empty archive that means no package was extracted.

| cp314 | arm64-v8a | armeabi-v7a | x86_64 |
| --- | --- | --- | --- |
| `pywt/_extensions` | 1.31 MB | 0.85 MB | 1.29 MB |
| **wheel / unpacked** | **4.07 / 7.94 MB** | **3.98 / 7.47 MB** | **4.08 / 7.92 MB** |

Every size on this page is `du` on the extracted tree, in MiB — what the files occupy, not the
sum of their lengths, which is about 0.13 MiB lower. armeabi-v7a is the 32-bit slice, and the
memory figures under [Things to know](#things-to-know) matter most there.

## iOS notes

Every shipped iOS extension is Mach-O `MH_DYLIB`, which is what `flet build ipa` and
`ios-simulator` require — a `MH_BUNDLE` fails at link rather than at import. They link
`/usr/lib/libSystem.B.dylib` and `@rpath/Python.framework/Python`, nothing else. Site-packages
stays a real directory here, so the zip question above does not arise.

Functionally the two platforms are the same package: the pure-Python tree is byte-identical
between the Android and iOS wheels, and `pywt/_c99_config.py` reads `_have_c99_complex = True`
on both, so the complex CWT wavelets (`cgau1`–`cgau8`, `cmor`, `shan`, `fbsp`) work on both.

| cp314 | device arm64 | simulator arm64 | simulator x86_64 |
| --- | --- | --- | --- |
| `pywt/_extensions` | 1.71 MB | 1.71 MB | 1.51 MB |
| **wheel / unpacked** | **4.11 / 8.34 MB** | **4.15 / 8.34 MB** | **4.12 / 8.14 MB** |

## Things to know

- **`pywt.__version__` reports the wrong number.** Every 1.9.0 wheel — ours and PyPI's desktop
  one — ships a `pywt/version.py` that says `1.8.0`; only `git_revision` differs between them.
  It is upstream's bug, not the recipe's, but it means an app that prints `pywt.__version__` on
  screen shows a version that does not exist on the index. Read
  `importlib.metadata.version("pywavelets")` instead, which returns `1.9.0`.
- **All 127 wavelets are compiled in.** 106 discrete (`haar`, `db1`–`db38`, `sym2`–`sym20`,
  `coif1`–`coif17`, 15 `bior`, 15 `rbio`, `dmey`) and 21 continuous (`gaus1`–`gaus8`, `mexh`,
  `morl`, `cgau1`–`cgau8`, `cmor`, `shan`, `fbsp`), across 14 families. Every one of the 106
  discrete filter tables was located inside the shipped `_pywt` extension on all six platform
  slices, so this is a property of the wheel and not of a data file that might go missing.
- **Round-trip exactness varies by wavelet, and one of them does not invert at all.** Over all
  106 discrete wavelets, level 5 on 4096 standard-normal samples, measuring
  `max|x - waverec(wavedec(x))| / max|x|` — the relative residual the example puts on screen —
  81 land under 1e-14: `haar`, all 38 Daubechies and all 17 coiflets (worst 1.5e-15), `sym9`,
  and 24 of the 30 biorthogonals. The other 18 symlets run 4e-14 up to **4e-11** for `sym20`,
  and `bior4.4`/`bior5.5`/`bior6.8` with their `rbio` twins reach 3e-12; their stored filter
  coefficients are truncated decimals. `dmey` is another eight orders of magnitude worse,
  **5e-3**, because it is an FIR *approximation* of the Meyer wavelet rather than an exact
  filter bank. The figures move by a factor of two or so between random draws, and by about
  4× if you quote the absolute residual instead, so state the metric with any tolerance you
  assert and key it to the wavelet you chose. Do not reach for `dmey` where invertibility
  matters.
- **[`waverec`](https://pywavelets.readthedocs.io/en/latest/ref/idwt-inverse-discrete-wavelet-transform.html)
  always returns an even length.** Reconstruct a 1001-sample signal and you get 1002 back, so a
  bare `x - rec` raises instead of reporting the residual. Always slice:
  `pywt.waverec(coeffs, w)[: len(x)]`, and `[:h, :w]` in 2-D.
- **[`cwt`](https://pywavelets.readthedocs.io/en/latest/ref/cwt.html) needs a *continuous*
  wavelet, and says so very badly.** Pass any of the 106 discrete names and you get
  `AttributeError: 'pywt._extensions._pywt.Wavelet' object has no attribute 'complex_cwt'`,
  which names neither the problem nor the fix. Drive any picker from
  `pywt.wavelist(kind="continuous")`. Spell the parameters out too — bare `cmor`, `shan` and
  `fbsp` are deprecated and print a `FutureWarning` on every call; use `cmor1.5-1.0`,
  `shan0.5-1.0`, `fbsp2-1.0-0.5`.
- **[`swt`](https://pywavelets.readthedocs.io/en/latest/ref/swt-stationary-wavelet-transform.html)
  needs a length divisible by `2**level`, and blames the level when it is not.** A 30-sample
  input at level 2 raises `ValueError: Level value too high (max level for current data size and
  start_level is 1).`; 32 samples works. Clamp with `pywt.swt_max_level(len(x))`, or pad to a
  power of two.
- **The stationary transform is a memory hazard on a phone; `wavedec` is not.** `swt2`
  coefficients come to `4 × level ×` the input — a level-5 `swt2` of a 1024×1024 float64 image
  holds 160 MiB for an 8 MiB input, and `trim_approx=True` only brings that to 128 MiB. A
  `wavedec2` pyramid of the same image is 8.0–8.2 MiB, about 1.0× the input, with a transient
  peak of roughly 2.7× while the transform runs (desktop measurement). Prefer `wavedec2` for
  images; if you genuinely need shift invariance, keep the level low and cast to float32.
- **Nine
  [boundary modes](https://pywavelets.readthedocs.io/en/latest/ref/signal-extension-modes.html)
  ship, and the default expands the coefficients.** With `symmetric` (the default), a 1024-sample
  level-4 `db4` decomposition produces 1050 coefficients; only `periodization` gives exactly
  1024. It is also the one mode under which the coefficients hold exactly the signal's energy:
  `symmetric` comes out at 1.00014× and `periodic` at 1.00024× on the same signal, so a
  per-band share computed against the signal is quietly off by that much. Normalising the
  shares by their own total hides it completely — they will add to 100% in any mode — so
  divide by the signal's energy if you want the discrepancy to be visible.
- **Integer input is silently promoted to float64.** That bites on exactly the bundled data an
  example reaches for — `pywt.data.ecg()` is `int32` and `camera()` is `uint8`. Cast explicitly
  (`camera().astype(np.float32)`) if you wanted the half-size coefficients; float32 input does
  give float32 coefficients.
- **Demo data ships inside the wheel, so an example needs no asset and no download.**
  `ascent()`, `aero()` and `camera()` are 512×512 `uint8` images, `ecg()` is 1024 `int32`
  samples, `nino()` is a 264-point sea-surface-temperature series — 0.6 MB of `.npz` in total —
  and
  [`demo_signal`](https://pywavelets.readthedocs.io/en/latest/ref/other-functions.html#pywt.data.demo_signal)
  generates 20 classic test signals in pure numpy with no file at all. Two of those 20,
  `Gabor` and `sineoneoverx`, raise if you pass an explicit length; call them with none and you
  get their natural 512 and 1024.
- **Size, and where it goes.** The wheel is about 4 MB and unpacks to 7.5–8.3 MB. Only
  0.85–1.71 MB of that is the compiled transforms: **5.72 MB, 69–77% of the unpacked payload
  depending on the slice, is `pywt/tests`** — upstream's own test suite and its MATLAB reference
  `.npz` files, which no app will ever import. See [Build notes](#build-notes-maintainers) for
  why the recipe leaves it in.
- **A desktop `flet run` is a fair proxy, except for speed.** The pure-Python layer of these
  wheels is byte-identical to PyPI's desktop wheel of the same version apart from `version.py`,
  and identical between Android and iOS, so API behaviour, boundary-mode handling and
  coefficient bookkeeping carry over exactly. What does not carry over is timing.

## Build notes (maintainers)

The whole recipe is a 17-line `meta.yaml` and four tests: no patches — there never have been —
and no `build.sh`. Nothing else was needed because the package is genuinely self-contained:
its C is its own, and the undefined symbols in the built extensions are only the
`malloc`/`memcpy`/`sin`/`cos`/`pow` class — **no `cpow`, `clog` or `cexp`**, which is why
`_have_c99_complex = True` holds at Android API 24 with none of the bionic complex-math
workarounds `scipy` needs.

**The test suite covers four things and the README claims many more.** `tests/test_pywavelets.py`
exercises `dwt`/`idwt`, `wavedec`/`waverec`, `swt`/`iswt` and a complex `cwt` — nothing else. In
particular nothing on device touches `wavedec2`/`waverec2`, `pywt.threshold`, `pywt.data` (the
`importlib.resources` read out of Android's zipped site-packages), or `wavelist()`
completeness. Those claims above rest on inspecting the wheel and on the example app. Adding
tests for them is the single highest-value change to this recipe; do not add a version assert,
since `pywt.__version__` is wrong upstream anyway.

What to re-verify on a bump, in rough order of how quietly it can go wrong:

- **`_have_c99_complex` in the built wheel**, on both platforms. If it ever flips to `False` the
  build stays green, the complex CWT wavelets silently stop working, and only a device run
  notices.
- **Mach-O filetype `MH_DYLIB` on all three iOS slices.** These wheels predate forge's
  `MH_BUNDLE → MH_DYLIB` converter, so meson-python's iOS link is producing dylibs on its own
  rather than being fixed up afterwards. A toolchain change could take that away, and the
  symptom is a link failure in the consumer's `flet build ipa`, not a failure here.
- **Whether `extract_packages` is still unnecessary.** It holds only while the five `.npz` files
  stay behind `importlib.resources` and nothing new opens a bundled file by path. Note that
  `pywt/_pytest.py` already does a `__file__`-relative read of `pywt/tests/data` — harmless
  because only the test suite imports it, and a reason to check that no such read moves into the
  package proper.
- **The wavelet inventory.** `wavelist()` counts and the per-family breakdown are quoted above
  and asserted nowhere; re-derive them, and re-run a filter-table scan of the shipped `_pywt`
  extension if the claim that all 106 discrete tables are compiled in is to survive.
- **`pywt.__version__`.** The 1.8.0-in-a-1.9.0-wheel mismatch is upstream's; if a later release
  fixes it, that bullet should go rather than be updated.
- **All sizes, and the `pywt/tests` share.** Re-measure per slice; do not scale the old numbers.

**Worth doing, not done:** strip `pywt/tests` from the wheel. It is 5.72 MB of every slice
against 0.85–1.71 MB of actual transform code, so it is the one change that would meaningfully
shrink the payload. No recipe here does that today — apsw's wheel ships upstream's `apsw/tests`
too — so it would take a new patch, and it was left alone to keep this recipe patch-free, which
is what makes bumps cheap. Weigh that trade deliberately rather than by default.
