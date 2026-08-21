# Headless cv2 pipeline

A synthetic scene is blurred and run through the Canny edge detector, and all three stages
come back on screen as JPEG. Above them the app prints the GUI backend that
[OpenCV](https://opencv.org/) was compiled against — read out of the wheel itself, not
guessed from the platform. On a desktop `flet run` it names whatever that platform's wheel
was built with — `COCOA` on macOS, `NONE` on Linux; the Android wheel reports `NONE` and the
iOS wheel leaves the field blank, which is the whole reason the pictures travel as bytes.

What it demonstrates:

- **The distribution name changes nothing about the API** — `GaussianBlur`,
  [`cvtColor`](https://docs.opencv.org/5.x/main_modules/imgproc_color_conversions.html#cvtcolor)
  and [`Canny`](https://docs.opencv.org/5.x/main_modules/imgproc_feature.html#canny)
  are the same compiled functions the base `opencv-python` wheel exposes. Nothing in
  `pipeline.py` would need editing to switch distributions.
- **Reading the build configuration at runtime** —
  [`getBuildInformation()`](https://docs.opencv.org/5.x/main_modules/core_utils.html#getbuildinformation)
  returns a report baked into the native library when it was compiled, so the GUI line is
  evidence about the binary actually loaded on this device.
- **Sending a frame to Flet without a window** —
  [`imencode`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imencode) produces a
  buffer, `tobytes()` makes it `bytes`, and
  [`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src) takes those directly.
  [`gapless_playback=True`](https://flet.dev/docs/controls/image/#flet.Image.gapless_playback)
  stops the tile blanking when the next scene replaces it.
- **Compute off the UI thread** — the pipeline runs inside
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button disabled and a spinner up. That worker catches its own exceptions and ends with the
  explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a
  background thread needs.

Run the same source on a Mac and on a phone and `pipeline.py` never changes; the backend line
is the platform's answer, not the app's. That is the useful shape of this package on mobile:
the pipeline is portable, and the only thing the platform takes away is the window you were
never going to get on a phone anyway.

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
