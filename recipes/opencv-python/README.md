# opencv-python

[`opencv-python`](https://github.com/opencv/opencv-python) provides the `cv2` bindings for
[OpenCV](https://opencv.org/): image filtering and geometry, contours and shape analysis,
feature detection, camera calibration, stitching, optical flow, and a
[`dnn`](https://docs.opencv.org/5.x/main_modules/dnn.html) module that runs ONNX models.
In a Flet app, those operations run on the device, so camera frames and model inputs do not
need to be uploaded for processing.

## Install

Add one OpenCV distribution to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "opencv-python",
]
```

**Install exactly one OpenCV distribution.** All three choices below provide the same
top-level package, `cv2`. Installing more than one lets their files overwrite each other and
leaves the result dependent on installation order. This is the same restriction documented
in upstream's [installation guidance](https://github.com/opencv/opencv-python#installation-and-usage).

| Distribution | Choose it when | Android arm64 wheel |
| --- | --- | ---: |
| `opencv-python` | The default. It contains OpenCV's main modules, including `imgproc`, `imgcodecs`, `features`, `calib`, `objdetect`, `video`, `videoio` and `dnn`. | ~14.4 MB |
| [`opencv-contrib-python`](../opencv-contrib-python) | You need a named contrib module such as `face`, `legacy`, `ximgproc`, `xphoto`, `optflow`, `wechat_qrcode`, `text`, `dnn_superres`, `gapi` or `ml`. OpenCV 5 moved `cv2.ml` into contrib, so it raises `AttributeError` with the base wheel. | ~21.5 MB |
| [`opencv-python-headless`](../opencv-python-headless) | Another dependency requires this distribution name. On mobile it is the same build as `opencv-python`, because neither wheel has a GUI backend; choosing it does not reduce the payload. | ~14.4 MB |

The sizes are approximate compressed-wheel measurements for the current recipe and are shown
only to make the distribution choice visible. Final application size depends on the selected
architectures and packaging format.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`shape-finder`](examples/shape-finder) — segments shapes out of a noisy scene and shows the
  annotated frame.

## Usage in a Flet app

### Storage

[`imread`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imread) and
[`imwrite`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imwrite) accept ordinary
filesystem paths. Put images the user expects to keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
out_path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "capture.png")
cv2.imwrite(out_path, frame)
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for regenerable derivatives and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for throwaway frames. Images and models shipped with the app are assets: put them in the
[assets directory](https://flet.dev/docs/cookbook/assets) and use
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
when an API needs their absolute filesystem path.

Often no file is needed. [`imencode`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imencode)
and [`imdecode`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imdecode) move complete
images between `numpy` arrays and `bytes`, including the result sent to a Flet image control.

### Threading

OpenCV parallelises many native operations itself. Android uses a pthreads backend and iOS
uses Grand Central Dispatch; work routed through OpenCV's `parallel_for_`, including many
resizes, warps, filters and `dnn` operations, can use multiple cores without application-level
threads. [`cv2.setNumThreads(n)`](https://docs.opencv.org/5.x/main_modules/core_utils.html#setnumthreads)
caps that internal parallelism, while `cv2.setNumThreads(0)` makes it serial.

Internal parallelism does not protect the Flet UI thread. Move a full-resolution pipeline or
model inference into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch and
display exceptions inside the worker, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). Arrays and results can
move between threads, but concurrent writes to the same `numpy` array remain a data race that
OpenCV will not detect.

On the GCD backend, [`cv2.getNumThreads()`](https://docs.opencv.org/5.x/main_modules/core_utils.html#getnumthreads)
may continue to report the core count after `setNumThreads()` changes the effective limit.
Measure the operation if the distinction matters; the getter is not reliable evidence that
the setting was ignored.

### App size

Depending on the architecture, the wheel is approximately 12.8–18.1 MB compressed and 25–52 MB
unpacked. Almost all of that is the single `cv2` extension, so there is no test suite or data
directory worth removing with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup).

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. Wheel size is not the amount added directly to the final
APK or IPA; packaging and compression determine that result.

### Android

Android includes TIFF and JPEG 2000 support in addition to JPEG, PNG, WebP, GIF, HDR, PXM,
PFM and Sun raster. The same TIFF or `.jp2` operation does not work on iOS. Neither platform
includes AVIF or OpenEXR.

The Android `dnn` build includes arm64 MLAS kernels, and some `imgproc` operations can use the
Carotene HAL. These are transparent optimisations: code and results stay portable, while
throughput may differ from iOS.

OpenCV reports Android camera and MediaNDK video backends, but this recipe does not validate
[`VideoCapture`](https://docs.opencv.org/5.x/main_modules/videoio.html) inside a Flet app. A
known consumer path is [`flet-camera`](https://pypi.org/project/flet-camera/) for capture and
`cv2` for processing. Direct camera access would also require the Android
[`CAMERA` permission](https://flet.dev/docs/publish/android/#permissions).

### iOS

iOS has no TIFF or JPEG 2000 codec. `imwrite` and `imencode` raise a `cv2.error` saying that
no writer or encoder exists; `imdecode` returns `None` for an unsupported input just as it
does for corrupt data, so check the return value. JPEG, PNG and WebP are the portable choices.

The iOS `dnn` build uses OpenCV's built-in SGEMM instead of the vendored MLAS kernels. It
returns the same result for the same model, but the throughput difference has not been
measured. OpenCV reports an AVFoundation `videoio` backend; direct capture through it remains
unvalidated by this recipe.

### Other considerations

Leave Flet's package compilation enabled on mobile. Advice to set
[`[tool.flet.compile].packages = false`](https://flet.dev/docs/publish/#compilation-and-cleanup)
addresses the stock desktop wheel, whose loader executes a source `config.py`. This mobile
wheel uses a different loader and is tested with package compilation enabled. If a desktop
target in the same project needs that workaround, scope it to that target instead:

```toml
[tool.flet.macos.compile]
packages = false
```

## Things to know

- **There is no GUI, so `cv2.imshow` raises.** Neither mobile build has a windowing backend —
  Android reports `GUI: NONE` and iOS leaves that value empty — and the
  [highgui](https://docs.opencv.org/5.x/main_modules/highgui.html) window functions fail with
  `cv2.error: (-213:The function/feature is not implemented)`. Encode a still image for
  [`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src):

  ```python
  view.src = cv2.imencode(".jpg", frame)[1].tobytes()
  ```

  Set [`gapless_playback=True`](https://flet.dev/docs/controls/image/#flet.Image.gapless_playback)
  when replacing frames. For a continuous stream,
  [`ft.RawImage`](https://flet.dev/docs/controls/rawimage/#rawimage-vs-image) avoids repeatedly
  encoding images and sends paced raw RGBA data over a dedicated channel.

- **On device, `cv2` is the extension module rather than the original package.** Native
  functions, constants and submodules such as `cv2.dnn`, `cv2.aruco`, `cv2.utils` and
  `cv2.videoio_registry` are present. The desktop wheel's pure-Python additions are not:
  `cv2.Mat`, `cv2.typing`, `cv2.data`, `cv2.mat_wrapper` and `cv2.misc` do not exist, and
  `import cv2.typing` raises `ModuleNotFoundError: No module named 'cv2.typing'; 'cv2' is not
  a package`. This can also break a dependency that imports `cv2.typing` at runtime. Use
  `numpy.ndarray` for annotations in your own code.

- **There is no FFmpeg, so video-file support is not portable.**
  `cv2.VideoCapture("clip.mp4")` has no FFmpeg backend to fall back on. Android's MediaNDK and
  iOS's AVFoundation may decode formats supported by the OS, but those paths are not exercised
  by this recipe. Still images are the supported path.

- **Haar cascades are absent because OpenCV 5 moved them out of the main modules.**
  `cv2.CascadeClassifier` is also absent from the desktop wheel of the same OpenCV generation
  — it is in `opencv-contrib-python` instead — and no cascade XML files ship. For faces, use
  [`cv2.FaceDetectorYN`](https://docs.opencv.org/5.x/main_modules/objdetect.html) with a YuNet
  ONNX model bundled as an app asset. `cv2.QRCodeDetector`, `cv2.barcode` and `cv2.aruco` remain
  available in the base wheel.

## Build notes (maintainers)

### Recipe shape

The three OpenCV distributions share one recipe shape: OpenCV's own CMake tree is built with
the Python bindings enabled, and the distribution name selects the base, contrib or headless
flavour. Keep the three `meta.yaml` files in step. A fix applied to only one can produce wheels
claiming the same OpenCV generation but exposing different behavior, and CI does not compare
their contents.

The patch preamble owns the explanation of the binding, loader and iOS `dnn` changes;
`meta.yaml` comments own individual build settings. Do not duplicate those mechanisms here.

### Re-verification checklist

- **Loader shape:** Confirm whether `cv2` still becomes the single-phase extension module and
  whether `cv2.typing`, `cv2.Mat` and the other pure-Python additions remain absent. If
  upstream moves to multi-phase module initialisation, rewrite the consumer note rather than
  carrying the old limitation forward.
- **Android package layout:** Test the wheel from zipped site-packages. Add
  `extract_packages` to consumer guidance only if a real runtime filesystem read makes it
  mandatory, and include the failure symptom.
- **Codec and backend lists:** Regenerate the `Media I/O`, `Video I/O` and `GUI` sections from
  `cv2.getBuildInformation()` on both platforms before repeating the TIFF, JPEG 2000,
  camera-backend and no-GUI claims.
- **Base versus contrib:** Check the built module list, especially `ml`, ArUco and every module
  named in the Install comparison.
- **Headless equivalence:** Reconfirm that it remains the same mobile build as the base wheel.
  That stops being true if a working mobile GUI backend is added.
- **iOS inference:** Confirm that MLAS remains disabled there and that `dnn` inference still
  succeeds with OpenCV's fallback implementation.
- **Size:** Re-measure the distribution comparison and compressed/unpacked ranges from the
  resulting wheels rather than scaling old figures.

### Coverage gaps

The device tests cover importing `cv2`, its numpy dependency, image encode/decode and resize.
They do not exercise GUI failure, TIFF or JPEG 2000, video files, direct camera capture,
`dnn` inference, the pure-Python submodule boundary, or zipped-package behavior without the
recipe's current extraction setting. Treat those as inspection or example-backed claims until
the corresponding device coverage exists.
