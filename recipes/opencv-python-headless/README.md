# opencv-python-headless

[`opencv-python-headless`](https://github.com/opencv/opencv-python) is one of the PyPI
distributions of the `cv2` bindings for [OpenCV](https://opencv.org/). It installs the same
top-level `cv2` package and the same API as `opencv-python`: image filtering and geometry,
contours, feature detection, and a `dnn` module that runs ONNX models. What "headless" names
is a build choice — OpenCV's [highgui](https://docs.opencv.org/5.x/main_modules/highgui.html)
window functions are compiled without a GUI backend behind them. On Android and iOS there is
no backend to leave out, so on mobile this distribution differs from `opencv-python` in name
and nothing else. Reach for it when something else in your dependency tree asks for it by
name.

## Install

```toml
dependencies = [
    "flet",
    "opencv-python-headless",
]
```

**Install exactly one OpenCV distribution.** [`opencv-python`](../opencv-python),
[`opencv-contrib-python`](../opencv-contrib-python) and this one all provide the same
top-level `cv2` package; installing two lets their files overwrite each other and leaves the
result dependent on installation order. If you are choosing freely rather than satisfying
someone else's pin, choose by module content: `opencv-python` carries OpenCV's main modules,
`opencv-contrib-python` adds the contrib ones such as `ml`, `ximgproc` and `xphoto`, and
this distribution is the first of those under a second name.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`headless-pipeline`](examples/headless-pipeline) — runs a blur-and-edges pipeline and
  prints the GUI backend the wheel was compiled against.

## Usage in a Flet app

Nothing about the distribution name changes the code. Process a frame and hand the result
straight to a Flet control:

```python
import cv2
import flet as ft

edges = cv2.Canny(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 60, 180)
view = ft.Image(src=cv2.imencode(".jpg", edges)[1].tobytes(), gapless_playback=True)
```

### Storage

[`imread`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imread) and
[`imwrite`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imwrite) take ordinary
filesystem paths. Images the user expects to keep belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
regenerable derivatives in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache),
and pictures shipped with the app in the
[assets directory](https://flet.dev/docs/cookbook/assets). Often no file is involved at all:
[`imencode`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imencode) and
[`imdecode`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imdecode) move whole
images between `numpy` arrays and `bytes`.

The codec set is not the same on both platforms. Android builds TIFF and JPEG 2000 in
addition to JPEG, PNG, WebP, GIF, HDR, PXM and Sun raster; iOS builds neither, so `imwrite`
and `imencode` raise a `cv2.error` for `.tif` and `.jp2` there, and `imdecode` returns `None`
for such an input exactly as it does for corrupt data. Neither platform has AVIF or OpenEXR.
JPEG, PNG and WebP are the portable choices.

### Threading

OpenCV parallelises many native operations internally, which does not protect the Flet UI
thread. Run a full-resolution pipeline through
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch
exceptions inside the worker, and end it with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), which a background
thread does not get for free.
[`cv2.setNumThreads(n)`](https://docs.opencv.org/5.x/main_modules/core_utils.html#setnumthreads)
caps the internal parallelism when you want the cores for something else.

### What "headless" removes

highgui itself is compiled into every one of these wheels; what varies between distributions
is the windowing backend behind it, and how much of that backend the wheel has to carry.
Read the answer for the binary you actually loaded with
[`getBuildInformation()`](https://docs.opencv.org/5.x/main_modules/core_utils.html#getbuildinformation),
whose `GUI:` line is baked into the native library at build time. Android prints `NONE`
there and iOS leaves the value empty, on device and on both simulator slices alike.

On desktop Linux that line is the whole story. In the manylinux2014 aarch64 pair at
5.0.0.93, `opencv-python` reports `GUI: QT5` and carries Qt5, xcb, X11 and xkbcommon shared
libraries plus an xcb platform plugin; the headless wheel reports `GUI: NONE` and carries
none of them — 50.6 MB of wheel against 36.5 MB, while the `cv2` extension inside differs
by 0.3 MB. That saving is a packaging artefact of Linux wheels, not a smaller OpenCV: the
macOS arm64 pair are the same size to within 200 bytes and both report `GUI: COCOA`, because
Cocoa is a system framework with nothing to bundle.

On Android and iOS neither distribution has a windowing backend, so `cv2.imshow`,
`namedWindow`, `waitKey` and the rest reach a placeholder that raises `cv2.error` telling you
to rebuild the library with GTK+ or Cocoa support. Encode the frame instead, as in
the snippet above. For a continuous stream,
[`ft.RawImage`](https://flet.dev/docs/controls/rawimage/#rawimage-vs-image) avoids re-encoding
each frame.

### App size

Expect 12.8–18.1 MB of compressed wheel and 25–52 MB unpacked per architecture, almost all
of it the single `cv2` extension, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
worth removing. The arm64 slices a phone actually ships sit near the bottom of that range —
14.4 MB compressed on Android and 13.9 MB on iOS — while the 17.5 MB and 18.1 MB figures
belong to the x86_64 emulator and simulator builds. Choosing this distribution over
`opencv-python` is not a size lever on mobile: measured per architecture, the two wheels of
the same version match in size to within a couple of kilobytes.

The levers that do work are an app bundle, split APKs, or a narrower
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI. Wheel size is not the amount added to the final APK or IPA;
packaging and compression determine that.

### Other considerations

A desktop `flet run` is not a rehearsal for the device here. The distribution name does not
imply the same build everywhere: on macOS the headless wheel reports `GUI: COCOA` and
`cv2.imshow` opens a real window, while on Linux the same name gives you no backend at all.
Validate anything that touches highgui, codecs or `dnn` on a device or emulator/simulator.

## Things to know

- **On device, `cv2` is the extension module rather than the original package.** Native
  functions, constants and submodules such as `cv2.dnn`, `cv2.aruco` and `cv2.utils` are
  present; the pure-Python additions are not. `cv2.typing`, `cv2.Mat`, `cv2.data`,
  `cv2.mat_wrapper` and `cv2.misc` do not exist, and `import cv2.typing` raises
  `ModuleNotFoundError`. This distribution is usually pulled in by another package rather
  than chosen directly, and that package is exactly the code most likely to import one of
  them. Use `numpy.ndarray` for annotations in your own code.

- **A dependency that pins this name and also wants a contrib module cannot be satisfied.**
  OpenCV 5 moved `cv2.ml` and the other contrib algorithms out of the base module set, and
  they are not in this wheel either — "headless" describes the GUI backend, not a reduced
  module list. There is no mobile wheel under a contrib-headless name, so the choice is
  `opencv-contrib-python` under its own name with the pin left unsatisfied, or doing without
  the contrib module.

- **Leave Flet's package compilation enabled on mobile.** Advice to set
  [`[tool.flet.compile].packages = false`](https://flet.dev/docs/publish/#compilation-and-cleanup)
  addresses the stock desktop wheel, whose loader executes a source `config.py`. This mobile
  wheel uses a different loader and is tested with compilation on. Scope the workaround to a
  desktop target if one in the same project needs it.

## Build notes (maintainers)

### Recipe shape

The headless sdist bakes its flavour into the source it ships, so this recipe carries no
headless-specific flag: it is the `opencv-python` recipe with a different package name, and
the diff hunks in `patches/mobile.patch` are identical to that recipe's — only the preamble
differs. Keep all three OpenCV recipes in step. A fix applied to one produces wheels claiming the same
OpenCV generation while behaving differently, and CI does not compare their contents.

`meta.yaml` also declares `extract_packages: [cv2]`, and that value reaches only the
recipe-tester's app — a consumer's `pip install` never sees it. **It is not required, and
Install deliberately does not mention it.** The patched loader resolves the relocated native
and binds it under the top-level name `cv2` before cv2's optional extra-submodule scan runs,
and that scan sits in a bare `try`/`except`. Measured on 2026-08-21 by removing the setting
from this example, rebuilding, and running on an arm64-v8a Android 14 emulator from zipped
site-packages: the pipeline rendered and the log carried no `NotADirectoryError`, no import
error, nothing. The patch preamble's wording — that the loader "pairs with"
`extract_packages` — reads stronger than the behaviour; it is an optimisation, not a
dependency. Re-run that removal test before adding the setting back to any consumer guidance.

### Upgrade hazards

Build numbers drift independently, so two distributions at the same OpenCV version can come
from different recipe states. Rebuild all three together when fixing any of them.

Every equivalence claim above assumes neither flavour gains a mobile windowing backend. If
upstream ever wires one into the base flavour, this page stops describing the wheel: rewrite
it rather than bumping the version underneath it.

### Re-verification checklist

- **Build-config equivalence:** extract the compiled-in build report from the base and
  headless `cv2` extensions for the same architecture and diff them. They should differ only
  in the timestamp, the host string and build paths. That diff, not the recipe files, is what backs the
  "same build" claim; hashing the two patches' diff hunks is the cheap half of it.
- **GUI backend:** confirm the `GUI:` line still shows no backend on both platforms before
  repeating the `cv2.imshow` guidance. Android prints `NONE`; iOS leaves the value empty.
- **Desktop comparison:** re-measure the Linux and macOS desktop pairs from PyPI before
  repeating the Qt figures. They describe upstream's packaging and can change without any
  recipe change here.
- **Size:** re-measure both mobile distributions per architecture rather than scaling old
  figures, and re-check that they still match.
- **Android package layout:** test from zipped site-packages, and keep `extract_packages`
  documented in Install for as long as the device tests are run with it.

### Coverage gaps

The device tests cover resolving the distribution name through `importlib.metadata`, an
encode/decode/grayscale/Canny round trip, and the presence of `cv2.dnn`. They do not exercise
the highgui failure path, `dnn` inference, the pure-Python submodule boundary, or any
comparison against the base distribution at runtime — the equivalence documented here is
established from the wheels, not from a device.
