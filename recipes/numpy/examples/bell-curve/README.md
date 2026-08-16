# numpy bell curve

Each sample on this screen is the average of *k* uniform random draws. Move the slider to
change *k*, tap **Draw**, and the histogram redraws: flat at k=1, a triangle at k=2,
unmistakably bell-shaped by k=4, a narrow spike by k=12. The measured standard deviation
sits next to the 1/√(12k) the central limit theorem predicts, and the two land within half
a percent of each other every time.

What it demonstrates:

- **One array, one call, no Python loop** —
  [`Generator.random((100_000, k))`](https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.random.html)
  fills up to 1.2 million doubles, `.mean(axis=1)` collapses them along one axis, and
  [`np.histogram`](https://numpy.org/doc/stable/reference/generated/numpy.histogram.html)
  bins the result. The Python interpreter sees three calls; everything else happens in
  compiled code, which is the entire reason numpy is worth shipping to a phone.
- **Which BLAS is in play** — the header line reports it from
  [`np.show_config()`](https://numpy.org/doc/stable/reference/generated/numpy.show_config.html).
  On device it says `none`, and the histogram still redraws in single-digit milliseconds:
  a BLAS only ever backs matrix products and `numpy.linalg`, so its absence costs nothing
  here. Run the same code on a desktop Mac and the line says `accelerate` instead.
- **How wide `long double` is on this device** — also in the header, from
  `np.dtype(np.longdouble).itemsize`. It reads 128-bit on a 64-bit Android phone and
  64-bit on iOS, which is the one place these wheels differ from each other.
- **Compute off the UI thread** — the sampling runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a
  background thread needs.

The bars are plain [`Container`](https://flet.dev/docs/controls/container/) heights scaled
against the tallest bin, so the app depends on nothing but Flet and numpy.

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
