# opencv-contrib-python

[`opencv-contrib-python`](https://github.com/opencv/opencv-python) is the `cv2` bindings for
[OpenCV](https://opencv.org/) built with the
[`opencv_contrib`](https://github.com/opencv/opencv_contrib) tree compiled in: the same main
modules as the base distribution, plus the extra ones OpenCV develops outside its core
release. Reach for it when you need a module by name — local thresholding, white balance,
model-free tracking, perceptual hashing, `ml` — and not otherwise.

## Install

Add it to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "opencv-contrib-python",
]
```

**This replaces [`opencv-python`](../opencv-python); it does not sit beside it.** Both
distributions install a top-level package called `cv2`, and every file in the base wheel has
the same path in this one, the `cv2` extension itself included. Listing both means one
silently overwrites the other, and which set of modules you end up with depends on unpacking
order; from inside the app that looks like `hasattr(cv2, "ximgproc")` answering `False`.
Under `flet run` it does not: `cv2` is a package there, the loser's orphaned `cv2/ximgproc/`
directory still imports as an empty module, and only a function such as `niBlackThreshold`
goes missing. Upstream states the same restriction in its
[installation guidance](https://github.com/opencv/opencv-python#installation-and-usage).

Everything in the base build is here too, so moving across is a change of dependency name and
nothing else. [`cv2.aruco`](https://docs.opencv.org/5.x/main_modules/objdetect.html),
`cv2.QRCodeDetector` and `cv2.barcode` are the three things people most often switch for that
the base wheel already has.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`contrib-modules`](examples/contrib-modules) — thresholds a badly lit page with
  `cv2.ximgproc` and ticks off contrib calls against the loaded binary.

## Usage in a Flet app

A contrib module is reached as an attribute of `cv2`, and its results are ordinary
`numpy` arrays that go to a Flet control the same way any other frame does:

```python
import cv2

scan = cv2.ximgproc.niBlackThreshold(
    gray, 255, cv2.THRESH_BINARY, 31, 0.15,
    binarizationMethod=cv2.ximgproc.BINARIZATION_SAUVOLA,
)
view.src = cv2.imencode(".png", scan)[1].tobytes()
```

### Storage

Several contrib modules are front ends that load weights from disk —
`cv2.dnn_superres.DnnSuperResImpl_create().readModel`, `quality`'s BRISQUE model and range
files, `text`'s classifier files, the cascade XML for `cv2.CascadeClassifier`. Ship those
with the application as
[assets](https://flet.dev/docs/cookbook/assets) and build the absolute path from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir):

```python
model = os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "EDSR_x2.pb")
```

A recogniser you train on device — an `ml.SVM`, an `ml.RTrees`, an `LBPHFaceRecognizer` —
should `save()` into
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which survives restarts, not
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp).

Images read and written through
[`imread`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imread) and
[`imwrite`](https://docs.opencv.org/5.x/main_modules/imgcodecs.html#imwrite) take ordinary
filesystem paths, and the codec set differs by platform: Android builds TIFF and JPEG 2000 on
top of JPEG, PNG, WebP, GIF, HDR, PXM and Sun raster, while iOS builds neither and raises a
`cv2.error` for a `.tif` or `.jp2` write. Neither has AVIF or OpenEXR.

### Threading

Several of the modules people take this wheel for are among the slowest calls in OpenCV:
`xphoto`'s BM3D denoiser, `optflow`'s DeepFlow and SimpleFlow, `dnn_superres` upscaling, and
training an `ml.SVM` or an `LBPHFaceRecognizer`. Each is one blocking native call that cannot
report progress, so run it in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch
exceptions inside the worker, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). OpenCV's own
parallelism — `pthreads` on Android, Grand Central Dispatch on iOS, per the build information
in each binary — happens inside those calls and does not keep the UI thread free. A tracker is
the opposite shape: `update()` runs once per short frame, so keep the whole loop on one worker
instead of dispatching every frame.

### The extra modules

Compared with the base build, this wheel registers 34 further `cv2` submodules on both
platforms, and five more on Android. In rough order of how often they earn their place on a
phone:

| Module | What it gives you |
| --- | --- |
| [`ximgproc`](https://docs.opencv.org/5.x/extra_modules/ximgproc.html) | Per-pixel Niblack/Sauvola/Wolf/NICK thresholding for photographed documents, `thinning`, guided and edge-aware filters, a fast line detector, superpixels |
| [`xphoto`](https://docs.opencv.org/5.x/extra_modules/xphoto.html) | White balance (`createSimpleWB`, `createGrayworldWB`), BM3D denoising, inpainting, `oilPainting` |
| `legacy` | `TrackerMOSSE`, `TrackerMedianFlow`, `TrackerBoosting`, `TrackerTLD`, `MultiTracker` — the older tracking API, kept for the four trackers that live nowhere else |
| [`img_hash`](https://docs.opencv.org/5.x/extra_modules/img_hash.html) | Perceptual hashes (`averageHash`, `pHash`, `blockMeanHash`) for finding near-duplicate photos |
| [`ml`](https://docs.opencv.org/5.x/extra_modules/ml.html) | `SVM`, `RTrees`, `KNearest`, `Boost` — trainable on device. OpenCV 5 moved this out of the base build, so `cv2.ml` raises `AttributeError` there |
| [`bgsegm`](https://docs.opencv.org/5.x/extra_modules/bgsegm.html) | MOG, GMG, CNT and LSBP background subtractors for a camera stream |
| [`quality`](https://docs.opencv.org/5.x/extra_modules/quality.html) | SSIM, PSNR, GMSD and MSE between two images; BRISQUE additionally wants a model file and a range file |
| [`face`](https://docs.opencv.org/5.x/extra_modules/face.html) | `LBPHFaceRecognizer` and friends, trained in-app from your own images |
| [`optflow`](https://docs.opencv.org/5.x/extra_modules/optflow.html) | DeepFlow, PCAFlow, RLOF and SimpleFlow, beyond the base build's Farnebäck, Lucas-Kanade and DIS |
| [`xfeatures2d`](https://docs.opencv.org/5.x/extra_modules/xfeatures2d.html) | BEBLID, TEBLID, FREAK, DAISY, LATCH and BRIEF descriptors |

The rest, which are present and importable but tend to need a model file, a research
pipeline or a desktop: `bioinspired`, `datasets`, `dnn_superres`, `dpm`, `ft`, `gapi`, `hfs`,
`intensity_transform`, `line_descriptor`, `motempl`, `multicalib`, `omnidir`,
`phase_unwrapping`, `plot`, `ppf_match_3d`, `rapid`, `reg`, `saliency`, `signal`, `stereo`,
`structured_light`, `text`, `videostab`, `wechat_qrcode`.

Contrib restores top-level names as well as submodules. Diffed against the base wheel of the
same version, this build adds `cv2.CascadeClassifier`, `cv2.HOGDescriptor`, `cv2.TrackerCSRT`,
`cv2.TrackerKCF` and the shape-matching family. None of them arrive with data — no cascade XML
or model file is in the wheel, and `cv2.data` does not exist on device to point at one — so
`CascadeClassifier` needs an XML you ship as an asset.

Android additionally registers five RGB-D modules that iOS does not build: `kinfu`,
`dynafu`, `colored_kinfu`, `large_kinfu` and `linemod`. Code that touches them raises
`AttributeError` on iOS, so gate it or leave it alone.

### App size

The wheel is approximately 19.6–26 MB compressed and 38–72 MB unpacked, depending on the
architecture. That is roughly 7 MB compressed, and 13–21 MB unpacked, more than the base
`opencv-python` wheel of the same version.

Every extra module is compiled into the one `cv2` extension, so this is all-or-nothing:
nothing on the application side drops the modules you do not call, and there is no test suite
or data directory worth removing with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup). On Android,
use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. Wheel size is not the amount added directly to the
final APK or IPA; packaging and compression determine that.

### Other considerations

The desktop wheel from PyPI is not the same build. Measured on macOS arm64 against the
5.0.0.93 desktop wheel, `cv2.text.OCRTesseract.create().run(...)` returned real text: that
wheel ships Tesseract and Leptonica among 99 bundled shared libraries. The mobile wheel is one
binary carrying the no-Tesseract stub, so code that reads a word under `flet run` cannot read
one on the phone. Validate any contrib module you depend on where it will actually run.

Leave Flet's package compilation enabled on mobile. Advice to set
[`[tool.flet.compile].packages = false`](https://flet.dev/docs/publish/#compilation-and-cleanup)
addresses the stock desktop wheel, whose loader executes a source `config.py`. This mobile
wheel uses a different loader and is tested with package compilation enabled. If a desktop
target in the same project needs that workaround, scope it to that target:

```toml
[tool.flet.macos.compile]
packages = false
```

## Things to know

- **A contrib module is an attribute of `cv2`, never an import path.** On device the recipe's
  loader makes `cv2` the native extension module itself, so `import cv2.ximgproc` — which works
  under `flet run` — raises `ModuleNotFoundError: No module named 'cv2.ximgproc'; 'cv2' is not
  a package`. `import cv2` followed by `cv2.ximgproc.niBlackThreshold(...)`, or
  `from cv2 import ximgproc`, works in both places, and nested names such as
  `cv2.ximgproc.segmentation` are reached the same way.

- **The model-free trackers are top-level, not in `cv2.legacy`.** `cv2.TrackerCSRT` and
  `cv2.TrackerKCF` initialise from one frame and a bounding box, need no weights, and are
  absent from the base wheel — which is one of the better reasons to take this one. The base
  build leaves `TrackerMIL` as its only weightless tracker, and `TrackerVit`, `TrackerNano`
  and `TrackerDaSiamRPN` all raise a `cv2.error` out of the ONNX importer until you hand them
  a model file. Reach into `cv2.legacy` only for `TrackerMOSSE`, `TrackerMedianFlow`,
  `TrackerBoosting` and `TrackerTLD`, which exist nowhere else.

- **The patented algorithms are not compiled in.** Both mobile binaries report `Non-free
  algorithms: NO`, so `cv2.xfeatures2d.SURF.create()` raises `cv2.error: (-213:The
  function/feature is not implemented) This algorithm is patented and is excluded in this
  configuration`. `SIFT` is unaffected — it moved into the main modules and is in the base
  wheel too. Use `BEBLID`, `TEBLID` or `DAISY` where you would have reached for SURF.

- **`cv2.text` is a front end for an OCR engine, not an OCR engine.** The class names are
  there, but the binary carries the no-Tesseract stub, whose message is `Tesseract not
  found.`, and `OCRHMMDecoder` and `OCRBeamSearchDecoder` need classifier files you supply
  yourself. To get text out of an image on a phone, run a recognition model through
  `cv2.dnn` instead.

## Build notes (maintainers)

### Recipe shape

The three OpenCV distributions share one recipe shape: OpenCV's own CMake tree is built with
the Python bindings enabled, and the distribution name selects the base, contrib or headless
flavour. Keep the three `meta.yaml` files in step. A fix applied to only one can produce
wheels claiming the same OpenCV generation but exposing different behavior, and CI does not
compare their contents.

Below its preamble, `patches/mobile.patch` is identical to the base recipe's: the contrib
sdist ships the same `opencv/` tree and only adds `opencv_contrib/` beside it, so all 14 files
and 38 hunks apply unchanged. That preamble owns the binding, loader and iOS `dnn`
explanations, and `meta.yaml` comments own individual build settings. The one contrib-specific
divergence is the iOS `-DBUILD_opencv_rgbd=OFF` gate, which is why the two platforms ship
different module lists.

### Upgrade hazards

The consumer-facing inventory above is a property of the build, not of upstream's
documentation, and OpenCV moves code between the main and contrib trees between releases:
`ml` and `aruco` both moved for the 5.0 series, and CSRT/KCF tracking, `CascadeClassifier` and
`HOGDescriptor` all sit on the contrib side of that line here. A version bump can invalidate
the Install section, the table, the top-level-class paragraph and the `AttributeError` claims
at once without any build failure.

### Re-verification checklist

- **Module inventory:** Re-derive it from the built wheels, not from upstream docs. Two
  independent readings should agree: the `cv2.<name>` strings interned in the extension, and
  the per-module stub directories the build generates. Diff contrib against base for the same
  version and diff Android against iOS, then update the table, the leftover list, the RGB-D
  paragraph and the "already in the base wheel" sentence.
- **Top-level classes:** Diff those too, not just submodules — the tracker, cascade, HOG and
  shape-matching claims rest on names that are attributes of `cv2` itself.
- **Import shape:** Confirm `cv2` still resolves to the extension module, so `import
  cv2.<module>` still fails while attribute access works. If upstream moves to multi-phase
  initialisation, rewrite that note rather than carrying it forward.
- **Non-free and Tesseract:** Confirm from the built binary that neither is linked, and
  recheck the desktop-versus-mobile divergence before repeating it.
- **iOS rgbd:** If the `Ptr` clash is fixed upstream, dropping the gate changes the module
  lists on one platform only.
- **Size:** Re-measure compressed and unpacked from the resulting wheels, and re-measure the
  delta against the base wheel of the same version rather than scaling old figures.

### Coverage gaps

The device tests cover the distribution name resolving to this wheel, an encode/decode/gray/
Canny round-trip, the presence of `dnn`, and one contrib module (`img_hash`) actually running.
They do not exercise `ximgproc` or any other module named in the table, the restored top-level
classes, the trackers, the model-file modules, the non-free exclusion, the missing Tesseract,
or the Android-only RGB-D set — and nothing in CI fails if the contrib module list changes
shape. Treat those as inspection-backed and example-backed claims until device coverage
exists.
