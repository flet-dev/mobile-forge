# cv2 shape finder

Nine shapes are drawn on a grid, then buried under Gaussian noise you control with a
slider. [OpenCV](https://opencv.org/) segments them back out, names each one from its
contour, and the annotated picture comes back on screen as JPEG bytes. The table reports
what was placed against what was found, how many contours survived the threshold before the
area filter, and how long the pipeline took.

What it demonstrates:

- **Showing an OpenCV result without a GUI backend** — the mobile wheels have none, so
  [`cv2.imshow`](https://docs.opencv.org/5.x/main_modules/highgui.html#imshow) raises. The
  frame is encoded with
  [`imencode`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imencode) and
  handed straight to [`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src),
  which accepts `bytes` as well as a path. JPEG rather than PNG because the buffer
  crosses the Flet transport on every run — at the top of the slider a PNG of the same
  frame is about four times larger.
- **A real segmentation pipeline in one call** —
  [`cvtColor`](https://docs.opencv.org/5.x/main_modules/imgproc_color_conversions.html#cvtcolor),
  an Otsu [`threshold`](https://docs.opencv.org/5.x/main_modules/imgproc_misc.html#threshold)
  that picks its own cut point,
  [`findContours`](https://docs.opencv.org/5.x/main_modules/imgproc_shape.html#findcontours),
  and [`approxPolyDP`](https://docs.opencv.org/5.x/main_modules/geometry_shape.html#approxpolydp),
  whose vertex count is what names the shape. All compiled native code in the wheel,
  identical on Android and iOS.
- **Compute off the UI thread** — the pipeline runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a
  background thread needs. The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end), not
  [`on_change`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change), so one drag
  runs the pipeline once instead of once per pixel travelled.

Push the slider up and that contour count runs from nine into five figures while the
shape counts hold: it is the area filter, not the threshold, doing the work. Push it all
the way and the labels finally slip — noise roughens the outlines until `approxPolyDP`
reads a circle as a four-sided polygon.

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
