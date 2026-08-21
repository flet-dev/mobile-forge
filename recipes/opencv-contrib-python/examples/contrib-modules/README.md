# cv2 contrib modules

A page of text is rendered, then lit the way a phone actually lights a page — bright at
the top-left corner, falling away into shadow at the bottom-right — and thresholded back
to black-on-white three ways. Two of the three come from any OpenCV build. The third,
Sauvola, is [`cv2.ximgproc`](https://docs.opencv.org/5.x/extra_modules/ximgproc.html)
and only exists in the contrib wheel. Below the picture, fourteen contrib-only functions are
looked up one by one and listed with a tick.

What it demonstrates:

- **A contrib-only call, running on the phone.**
  [`niBlackThreshold`](https://docs.opencv.org/5.x/extra_modules/ximgproc.html#niblackthreshold) with
  `BINARIZATION_SAUVOLA` derives a cut point per pixel from the local mean and standard
  deviation. It is selected on launch, so the first screen is already a result the base
  `opencv-python` wheel could not have produced.
- **Why you would pay for it.** The app draws the page, so it knows exactly which pixels
  are ink and can score each method against the truth. All three keep essentially every
  stroke; what separates them is how much blank paper the shadow talks them into calling
  ink. At 60% shadow, measured in the app: Otsu 37%, `adaptiveThreshold` 14%, Sauvola 2%.
- **Proving which wheel you got** — every row asks for a function, not a module name, so it
  reads the same on the phone and under `flet run`. On device `cv2` is the native extension
  and a missing module is simply absent; on the desktop it is a package, and if
  `opencv-python` overwrote this wheel the orphaned `cv2/ximgproc/` directory still imports
  as an empty module — `hasattr(cv2, "ximgproc")` ticks, `niBlackThreshold` is gone.
- **PNG, not JPEG, for a two-valued image** —
  [`imencode`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imencode) hands
  bytes straight to [`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src),
  and a mask has two colours, so PNG comes out about four times smaller than JPEG at
  quality 82 and crosses the Flet transport on every run.
- **Compute off the UI thread** — each threshold runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the controls disabled and a spinner up, ending in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so a
  drag re-renders the page once instead of once per pixel travelled.

Push the shadow to the top and Sauvola degrades too, from 2% to 8%: where the corner is
crushed to black there is no local contrast left for a local method to read, and the
information is gone before any threshold sees it.

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
