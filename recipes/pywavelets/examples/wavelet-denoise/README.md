# pywavelets wavelet denoise

One screen. Pick a test signal, a wavelet and a noise level; the app adds the noise, removes
it again with [VisuShrink](https://pywavelets.readthedocs.io/en/latest/ref/thresholding-functions.html)
and shows you what it cost — for a 4096-sample signal and for the 512×512 `camera` image that
ships inside the wheel. Nothing is bundled, nothing is downloaded, nothing is random between
runs.

What it demonstrates:

- **A round-trip number that grades the transform itself.** The headline line under the pickers
  is `max|x - waverec(wavedec(x))| / max|x|`, for the signal and for the image, computed
  independently of the denoising. `haar` and `db4` land on double round-off (~1e-15);
  `sym8` sits near 5e-13 because its stored filter coefficients are truncated decimals; pick
  `dmey` and it jumps to ~1e-2 and turns red, because dmey is an FIR *approximation* of the
  Meyer wavelet and does not invert. A good denoising SNR cannot hide a filter bank that
  loses information — that is the point of showing both.
- **Denoising that actually works, and a lesson about picking a basis.** SNR before and
  after, for the signal and the image. At sigma 0.10, `HeaviSine` goes 14.3 → 27.2 dB with
  `db4`; on the piecewise-constant `Blocks`, plain `haar` beats `db4` (20.3 dB against
  18.4 dB), which is the whole "match the wavelet to the signal" argument in two taps.
- **Where the energy went.** A bar per band of the clean signal's 6-level decomposition —
  the sigma slider does not move these, only the signal and the wavelet do. Computed with
  `mode="periodization"`, the only mode whose coefficient count equals the signal length
  (4096 against `symmetric`'s 4134 for `db4` at level 6), so a bar is the band's share of the
  *signal's* energy. Under `symmetric` the coefficients hold 1.00014× the signal's energy and
  under `periodic` 1.00024×, and the bars would be shares of that padded total instead. They
  are normalised either way, so the displayed percentages always add to about 100 and cannot
  tell you which mode you are in.
- **`pywt.data` read on device.** The signals come from
  [`demo_signal`](https://pywavelets.readthedocs.io/en/latest/ref/other-functions.html#pywt.data.demo_signal)
  (pure numpy, no file) and the image from `pywt.data.camera()`, which reads a `.npz` out of
  the installed package through `importlib.resources` — the path that has to work from
  Android's zipped site-packages.
- **The compute off the UI thread.** The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/) into
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), behind
  a `threading.Lock` so two overlapping runs cannot interleave their writes, and ending with
  the explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that
  a background thread needs.
- **Images without an image library.** Both panes are
  [`ft.Image(src=<bytes>)`](https://flet.dev/docs/controls/image/) fed by a 25-line PNG writer
  built from `zlib` and `struct`, because the app depends on nothing past Flet, pywavelets and
  numpy — there is no image library on device to do it.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
