# numpy bell curve

Each sample on this screen is the average of *k* uniform random draws. Move the slider to
change *k*, and the histogram redraws when you let go: flat at k=1, a triangle at k=2,
unmistakably bell-shaped by k=4, a narrow spike by k=12. The measured standard deviation
sits next to the 1/√(12k) the central limit theorem predicts, and the two normally agree to
a couple of tenths of a percent — at 100,000 samples the run-to-run scatter is about 0.2%,
so a run wanders past half a percent every so often.

What it demonstrates:

- **One array, one call, no Python loop** —
  [`Generator.random((100_000, k))`](https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.random.html)
  fills up to 1.2 million doubles — 9.6 MB in one contiguous block, which the table reports
  — `.mean(axis=1)` collapses them along one axis, and
  [`np.histogram`](https://numpy.org/doc/stable/reference/generated/numpy.histogram.html)
  bins the result. The Python interpreter sees three calls; everything else happens in
  compiled code, which is the entire reason numpy is worth shipping to a phone. The table
  reports how long those three calls took on the device in your hand, which is the only
  timing for them worth having.
- **Which BLAS is in play** — the header line reports it from
  [`np.show_config()`](https://numpy.org/doc/stable/reference/generated/numpy.show_config.html).
  On device it says `none`, and the histogram redraws anyway: a BLAS only ever backs matrix
  products and [`numpy.linalg`](https://numpy.org/doc/stable/reference/routines.linalg.html),
  so its absence costs nothing here. Run the same code on a desktop Mac and the line names
  `accelerate` or `openblas` instead.
- **How wide `long double` is on this device** — also in the header, from
  `np.dtype(np.longdouble).itemsize`. It reads 128-bit on a 64-bit Android phone and 64-bit
  on iOS, which is where the two wheels' arithmetic parts company.
- **Plain Python at the UI boundary** — `src/distribution.py` owns everything numpy touches
  and hands back lists and floats, so `src/main.py` never imports numpy. Scaling the bars
  works on ordinary ints only because the counts arrived through `.tolist()`; straight off
  the array, `counts.max()` is an `np.int64`, which is not an `int` and does not encode like
  one.
- **Compute off the UI thread** — the sampling runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  a spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and the handler ends with the explicit
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
