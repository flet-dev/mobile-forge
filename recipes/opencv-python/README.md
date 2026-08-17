# opencv-python

[`opencv-python`](https://github.com/opencv/opencv-python) is the `cv2` binding for
[OpenCV](https://opencv.org/): image filtering and geometry, contours and shape analysis,
feature detectors, camera calibration, stitching, optical flow, and a
[`dnn`](https://docs.opencv.org/5.x/main_modules/dnn.html) module that runs ONNX models.
On mobile it is what lets a camera frame be measured, corrected or classified *on the
device* — the whole library is compiled into the wheel, so nothing is uploaded and nothing
needs a network. It is the most-upvoted package request Flet has
([flet#3200](https://github.com/flet-dev/flet/discussions/3200)).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "opencv-python",
]

[tool.flet.android]
extract_packages = ["cv2"]
```

**Pick exactly one of the three distributions.** `opencv-python`,
[`opencv-contrib-python`](../opencv-contrib-python) and
[`opencv-python-headless`](../opencv-python-headless) all install a top-level package
called `cv2`, so two of them in one environment silently overwrite each other's files and
you end up running whichever landed last — upstream's own
[warning](https://github.com/opencv/opencv-python#installation-and-usage), and it applies
here unchanged. Which one:

- **`opencv-python`** unless you have a reason otherwise. It is the whole of OpenCV's main
  tree — `core`, `imgproc`, `imgcodecs`, `features`, `flann`, `calib`, `geometry`,
  `stereo`, `objdetect`, `photo`, `ptcloud`, `stitching`, `video`, `videoio` and `dnn`.
- **`opencv-contrib-python`** is a strict superset, adding thirty-seven further modules —
  `face`, `tracking`, `ximgproc`, `xphoto`, `optflow`, `img_hash`, `wechat_qrcode`, `text`,
  `bgsegm`, `dnn_superres`, `gapi` among them — for 20.5 MB of wheel against 13.8 MB on
  Android arm64. The one that catches people out is **`cv2.ml`** (`SVM`, `KNearest`,
  `RTrees`, `ANN_MLP`): OpenCV 5 moved the `ml` module into contrib, so `cv2.ml` raises
  `AttributeError` on the base wheel where OpenCV 4 had it. Take contrib for a named
  module you need, not by default.
- **`opencv-python-headless`** exists so that a pin someone else wrote — albumentations
  and most OCR stacks require `opencv-python-headless` by name — resolves to something.
  It saves you nothing here: on mobile it is *the same build*. Its wheel has the identical
  file list, an extension the same size to within 5 KB, and a `getBuildInformation()` that
  differs from `opencv-python`'s in one line — the CI machine's kernel version — because
  there is no GUI backend in either to leave out (see
  [Things to know](#things-to-know)).

Nothing else is required. `numpy` comes along automatically, and with it
`flet-libcpp-shared` on Android — that dependency belongs to numpy, not to cv2, whose own
extension links libc++ statically and declares nothing beyond `numpy>=2`.

The `extract_packages` entry above is the configuration these wheels are tested in, and it
costs you nothing but a little disk. Be clear about what it is not, though: it is **not**
what makes `import cv2` work. The loader in these wheels resolves the native extension
directly and reads no file out of the package directory, so cv2 imports and every image
operation runs whether the package is extracted or left inside Android's zipped
site-packages. Nor does it bring back `cv2.Mat` or `cv2.typing` — those are gone for an
unrelated reason, described in [Things to know](#things-to-know).

**Leave `[tool.flet.compile]` alone for mobile.** You will find advice to set
`packages = false`; that is a desktop fix. The stock PyPI wheel's loader `exec()`s a
`config.py` at import time, so compiling packages to `.pyc` and stripping the sources
breaks it with `ImportError: OpenCV loader: missing configuration file: ['config.py']`.
The loader in *these* wheels never reads that file, and the recipe's own on-device tests
run with packages compiled. If you build a desktop or web target from the same project,
scope the workaround to that target rather than turning compilation off everywhere:

```toml
[tool.flet.macos.compile]
packages = false
```

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for
iOS device and both simulator slices, on Python 3.12, 3.13 and 3.14.

## Storage

[`imread`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imread) and
[`imwrite`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imwrite) take ordinary
filesystem paths, so anything the app writes belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups:

```python
out_path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "capture.png")
cv2.imwrite(out_path, frame)
```

Use [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for a frame you re-derive on demand and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for something you can afford to lose. Images you ship with the app are assets, not storage,
and belong in `src/assets/`.

Most of the time you want no file at all:
[`imencode`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imencode) and
[`imdecode`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imdecode) move whole
images between `numpy` arrays and `bytes` in memory, which is also how a result reaches the
screen — see [Things to know](#things-to-know).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`shape-finder`](examples/shape-finder) — segments shapes out of a noisy scene and shows the annotated frame.

## Threading

**OpenCV is genuinely multi-threaded here**, which sets it apart from most of the numerical
wheels on this index. Android builds with a pthreads parallel framework, iOS with Grand
Central Dispatch, and everything routed through OpenCV's `parallel_for_` — resizes, warps,
filters, `dnn` inference, most of `imgproc` — spreads across the phone's cores by itself.
[`cv2.setNumThreads(n)`](https://docs.opencv.org/5.x/main_modules/core_utils.html#setnumthreads)
caps that, `cv2.setNumThreads(0)` makes it serial, and the `OPENCV_FOR_THREADS_NUM`
environment variable does the same thing before the first call.

[`cv2.getNumThreads()`](https://docs.opencv.org/5.x/main_modules/core_utils.html#getnumthreads)
does not tell you what you set on the GCD backend. Measured on macOS, which uses the same
backend as iOS: after `setNumThreads(1)`, `setNumThreads(2)` and `setNumThreads(8)` it kept
returning the core count, while the wall-clock time of a large `GaussianBlur` moved by more
than 4× — so the setting takes effect and the getter is not evidence of it. Time the call
rather than reading the number back.

None of that helps the UI thread. A pipeline over a full-resolution camera frame will
freeze the UI wherever it runs, so push it to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads. OpenCV itself imposes no thread rules on you: arrays and
results move between threads freely, and there is no handle to serialise. Two threads
writing into the same `numpy` array is your problem, not something OpenCV will detect.

## Android notes

The Android build carries two image formats the iOS one does not: **TIFF** (libtiff 4.7.1)
and **JPEG 2000** (OpenJPEG 2.5.3). Both platforms have JPEG (libjpeg-turbo), PNG, WebP,
GIF, HDR, PXM, PFM and Sun raster; neither has AVIF or OpenEXR. So a `.tiff` or `.jp2`
round-trip that passes on an emulator will fail on an iPhone — see
[iOS notes](#ios-notes).

`dnn` has kernels here that iOS does not. OpenCV 5's vendored MLAS (NEON SGEMM and SGEMV on
arm64) is compiled into the Android wheel and disabled in the iOS one, and Android
additionally gets the Carotene HAL for a set of `imgproc` operations. Both are transparent:
the same call returns the same answer on either platform, and only the time it takes moves.

The **NDK Camera and MediaNDK video backends are compiled in** — `ANDROID_NATIVE` is a
registered `videoio` backend and the extension links `libcamera2ndk.so` and
`libmediandk.so`. That is a statement about the binary, not a working camera: nothing in
this recipe opens one, the app would additionally need the `CAMERA`
[permission](https://flet.dev/docs/publish/android/#permissions), and
[`VideoCapture`](https://docs.opencv.org/5.x/main_modules/videoio.html) inside a Flet app is
untested here. Treat it as worth trying, not as supported — the route that is known to work
is [`flet-camera`](https://pypi.org/project/flet-camera/) to acquire frames and cv2 to
process them.

## iOS notes

**No TIFF, no JPEG 2000.** Writing one raises —
`cv2.error: (-2:Unspecified error) could not find a writer for the specified extension`
from `imwrite`, and `could not find encoder for the specified extension` from `imencode` —
while *reading* one fails silently: `cv2.imdecode` returns `None` for a format it has no
decoder for, exactly as it does for a corrupt buffer, so check the return value rather than
relying on an exception. JPEG, PNG and WebP cover everything else. The build also has no
OpenEXR and no AVIF, which matches Android.

The vendored MLAS kernels are **off** on iOS: their object files do not survive into the
iOS framework binary, and `import cv2` failed at `dlopen` with an undefined `MlasGemmBatch`
until they were disabled. `dnn` falls back to OpenCV's built-in SGEMM, which gives the same
answer on the same model; how much throughput that costs has not been measured here.
Apple's Accelerate framework is linked in, as are UIKit, CoreGraphics and QuartzCore.

`videoio` registers the AVFoundation backend and the build reports `iOS capture: YES`; as
on Android, that is what the binary contains and not a tested path.

## Things to know

- **There is no GUI, so `cv2.imshow` raises.** Both builds report `GUI: NONE`, and every
  [highgui](https://docs.opencv.org/5.x/main_modules/highgui.html) entry point —
  [`imshow`](https://docs.opencv.org/5.x/main_modules/highgui.html#imshow), `waitKey`,
  `namedWindow`, the trackbars — fails with
  `cv2.error: (-213:The function/feature is not implemented) The function is not
  implemented. Rebuild the library with Windows, GTK+ 2.x or Cocoa support`. The
  replacement is one line, because
  [`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src) accepts `bytes` as
  well as a path:

  ```python
  view.src = cv2.imencode(".jpg", frame)[1].tobytes()
  ```

  Set [`gapless_playback=True`](https://flet.dev/docs/controls/image/#flet.Image.gapless_playback)
  so the control does not blank between frames. For a continuous stream, encoding every
  frame is the wrong shape —
  [`ft.RawImage`](https://flet.dev/docs/controls/rawimage/#rawimage-vs-image) takes raw RGBA
  over a dedicated channel and paces itself.
- **On device, `cv2` is the extension module, not the package.** OpenCV's compiled bindings
  insist on being loaded under the exact top-level name `cv2`, and the loader in these
  wheels does that by loading the relocated native extension as `cv2` — which, because
  OpenCV uses single-phase module init, replaces the `cv2` package in `sys.modules` with
  the extension itself. Everything the C++ side defines is present and normal:
  `cv2.__version__`, every function and constant, and the native submodules `cv2.dnn`,
  `cv2.aruco`, `cv2.utils`, `cv2.videoio_registry`. What is gone is the handful of
  pure-Python submodules the desktop wheel merges in afterwards — **`cv2.Mat`,
  `cv2.typing`, `cv2.data`, `cv2.mat_wrapper` and `cv2.misc` do not exist**, and
  `import cv2.typing` fails with
  `ModuleNotFoundError: No module named 'cv2.typing'; 'cv2' is not a package`. That matters
  if one of your dependencies does `from cv2.typing import MatLike` outside a
  `TYPE_CHECKING` block; annotate with `numpy.ndarray` in your own code and the question
  does not arise. No `extract_packages` setting changes this.
- **No FFmpeg, so no video files.** The desktop wheel bundles 99 shared libraries —
  the whole of FFmpeg, OpenEXR, Tesseract, SDL2 — and the mobile wheels bundle none of
  them; that is the entire difference in the file list between the two, everything else is
  statically linked in. `cv2.VideoCapture("clip.mp4")` therefore has no FFmpeg to fall back
  on. Android's MediaNDK backend can in principle decode what the OS decodes, iOS has
  AVFoundation, and neither has been exercised by this recipe. Still images are the
  supported path.
- **Haar cascades are gone, and not because of this build.** OpenCV 5 removed
  `cv2.CascadeClassifier` upstream; the symbol is absent from the desktop wheel of the same
  version too, and no cascade XML ships in `cv2/data/` on any platform, so
  `cv2.data.haarcascades` (where the module exists at all) points at an empty directory. Use
  [`cv2.FaceDetectorYN`](https://docs.opencv.org/5.x/main_modules/objdetect.html) with a
  YuNet ONNX model bundled in `src/assets/` — smaller and considerably more accurate — or
  `cv2.QRCodeDetector` and `cv2.barcode` for codes. ArUco did *not* move to contrib: it is
  in `objdetect` now, so `cv2.aruco` is in this wheel.
- **Size.** The wheels are 12–17 MB and unpack to 24–43 MB depending on architecture
  (Android arm64-v8a: 13.8 MB and 33.9 MB; armeabi-v7a: 12.2 MB and 23.9 MB; x86_64:
  16.7 MB and 42.9 MB; iOS arm64: 13.3 MB and 38.8 MB). Essentially all of that is the
  single `cv2` extension — 33.0 MB of the Android arm64 total, 37.8 MB of the iOS one — so
  there is nothing to trim with `[tool.flet.cleanup]`: no test suite, no data files, and
  the 451 KB of `.pyi` type stubs are stripped during packaging anyway. Building only the
  ABIs you ship is the lever that exists; see
  [target architectures](https://flet.dev/docs/publish/android/#supported-target-architectures).

## Build notes (maintainers)

Each patch carries its rationale at the top of the file and each build flag is justified in
`meta.yaml` next to the flag, so this section is what neither of those records.

The recipe builds OpenCV's *own* CMake tree with the python bindings forced back on
(upstream disables them for `ANDROID` and `APPLE_FRAMEWORK`, which is what most of the
patch undoes), rather than going the PEP 517 shim route used for packages with no usable
sdist. `opencv-python`'s sdist drives scikit-build with a `CMAKE_ARGS` handoff, and that
handoff is the whole integration — which is why the same recipe shape is copy-pasted across
all three distributions, with the flavour selected only by the package name and, on iOS
contrib, one extra `BUILD_opencv_rgbd=OFF`. **Keep the three `meta.yaml` files in step**: a
fix applied to one and not the others produces three wheels claiming the same OpenCV
version with different contents, and nothing in CI compares them.

`extract_packages: [cv2]` is retained deliberately even though it is, for this version, a
no-op: the loader's extra-submodule pass it was added for cannot succeed regardless (the
package module is no longer in `sys.modules` by the time it runs). It costs nothing, it is
what the on-device tests exercise, and if upstream ever moves to multi-phase module init
the pass starts working again and the entry becomes load-bearing without anyone touching it.

What to re-verify on a bump, in rough order of how quietly it can go wrong:

- **That `cv2` is still the extension module rather than the package**, since a good deal of
  [Things to know](#things-to-know) hangs off it. It follows from `PyModule_Create2` in the
  binary — single-phase init, so `module_from_spec` registers the extension in `sys.modules`
  under `cv2` and the package module is dropped. The current tests do not pin it; the
  quickest check is `cv2.__spec__.loader` on device, or `hasattr(cv2, "typing")` being
  `False`. If a release switches to multi-phase init the behaviour flips silently and the
  bullet needs rewriting, not updating.
- **The two platforms' codec lists.** No TIFF and no JPEG 2000 on iOS is read out of
  `getBuildInformation()` in the shipped binary, and it is a consequence of which 3rdparty
  libraries the iOS configure step found, not of anything the recipe sets — so it can move
  either way on a bump without a build failure. Re-extract the build information from both
  `.so` files and diff the `Media I/O` blocks before repeating the claim, and do the same
  for `Video I/O` (`MEDIANDK`/`NDK Camera` on Android, `AVFoundation` on iOS) and for the
  `GUI: NONE` line the `imshow` bullet rests on.
- **The module list, and with it the contrib boundary.** `cv2.ml` living in contrib and
  ArUco living in `objdetect` are OpenCV 5 facts, not permanent ones. The
  `OpenCV modules: To be built` line of each build differs between the three flavours and
  is the cheapest way to regenerate the Install section's comparison.
- **Headless being identical to the main build on mobile.** It holds only while there is no
  GUI backend to disable in the first place. If a future toolchain gives the Android or iOS
  build a working `highgui`, headless stops being a synonym and both the Install section
  and the `imshow` bullet change together.
- **The desktop-wheel comparison.** That the mobile wheels differ from the PyPI wheel of the
  same version in exactly the 99 bundled `.dylibs` and nothing else is what backs the
  "no FFmpeg" bullet. Re-run that diff; a new pure-Python file upstream would also change
  it.
- **The sizes** are measured per architecture from the built wheels. Re-measure, do not
  scale.
