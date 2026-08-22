# scipy signal fit

A damped sinusoid is buried under Gaussian noise you control with a slider. Tap **Fit** and
[scipy](https://scipy.org/) recovers its four parameters — amplitude, decay, frequency and
phase — and prints them next to the true values it was given.

What it demonstrates:

- **A three-stage numerical pipeline in one call** —
  [`signal.butter`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html)
  plus [`signal.sosfiltfilt`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html)
  to low-pass the noise away,
  [`fft.rfft`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.fft.rfft.html) to
  locate the dominant frequency, and
  [`optimize.curve_fit`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.curve_fit.html)
  seeded from that peak to fit the full model. Every one of those is compiled native code
  in the wheel, identical on Android and iOS.
- **Compute off the UI thread** — the fit runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a background
  thread needs.
- **Which BLAS you are actually linked against** — the header line reports it from
  [`scipy.show_config()`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.show_config.html).
  On device it says OpenBLAS on both platforms; on a Mac desktop the same code says
  Accelerate, which is the difference the mobile wheels deliberately remove.
- **Why a local optimiser needs a good seed** — the frequency guess comes from the
  spectrum, not from a constant. Start `curve_fit` more than about half a cycle off and it
  converges onto a harmonic instead.

Push the noise slider to its maximum and the fitted amplitude starts to wander while the
frequency stays put — the spectrum peak is far more robust than the amplitude of a decaying
signal whose tail is mostly noise.

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
