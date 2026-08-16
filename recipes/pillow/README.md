# pillow

[`pillow`](https://python-pillow.github.io/) is the Python imaging library: open a file,
transform the pixels, draw on them, encode them again. On mobile it covers the work the UI
toolkit will not do for you — shrink a camera photo before uploading it, cut a thumbnail,
stamp a caption onto a picture, turn computed pixels into something
[`ft.Image`](https://flet.dev/docs/controls/image/) can display — on the device, offline.

These wheels are a **JPEG and PNG** build. WebP, AVIF, JPEG 2000, compressed TIFF and colour
management are not compiled in, so code that opens those files on your laptop raises on the
phone. The complete list is in [Things to know](#things-to-know), and the example app prints
the codecs it actually has on screen.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pillow",
]
```

Two more wheels come along and need no configuring: `flet-libjpeg` (libjpeg-turbo) and
`flet-libfreetype`, the JPEG codec and the font rasteriser Pillow is compiled against. No
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed either — nothing in `PIL` opens a data file next to itself at runtime, so
Android's zipped site-packages is fine.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS,
on Python 3.12, 3.13 and 3.14.

## Storage

The bundle Pillow is imported from is read-only, so anything you save goes to one of Flet's
storage directories. Output you intend to keep — an edited photo, a thumbnail cache —
belongs in [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
img.save(os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "thumb.jpg"))
```

Files that only have to survive the current operation go in
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp).

Often you need no file at all:
[`Image.save`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.save)
writes to any binary file object, so an `io.BytesIO` gives you encoded bytes that
[`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src) accepts directly —
see [Things to know](#things-to-know).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`image-filters`](examples/image-filters) — draws a picture with Pillow and filters it on device.

## Threading

Decoding, filtering and encoding are compiled loops, and at photo sizes they are long enough
to drop frames if you run them in an event handler. Push them to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads.

Those loops release the GIL, so a background resize really does run alongside the UI instead
of queueing behind the interpreter lock. What that does not buy you is a shared
[`Image`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image)
object: nothing in Pillow serialises access to one, so give each worker its own or `copy()`
before handing one over.

## Things to know

- **Two codecs, and that is the whole list.**
  [`PIL.features.get_supported_codecs()`](https://pillow.readthedocs.io/en/stable/reference/features.html#PIL.features.get_supported_codecs)
  returns `['jpg', 'zlib']` on device where the desktop PyPI wheel of the same version
  returns `['jpg', 'jpg_2000', 'zlib', 'libtiff']`. The full comparison:

  | | these wheels | desktop PyPI wheel |
  | --- | --- | --- |
  | JPEG (libjpeg-turbo) | yes | yes |
  | PNG / zlib | yes | yes (zlib-ng) |
  | FreeType — `ImageFont`, `ImageDraw.text` | yes | yes |
  | JPEG 2000 (OpenJPEG) | no | yes |
  | TIFF (libtiff) | no | yes |
  | WebP | no | yes |
  | AVIF | no | yes |
  | LittleCMS — [`ImageCms`](https://pillow.readthedocs.io/en/stable/reference/ImageCms.html) | no | yes |
  | Raqm — bidirectional and complex-script text | no | yes |
  | XCB — X11 screen grab | no | yes |
  | libimagequant | no | no |

  Three extension modules are simply absent from the wheel — `_webp`, `_avif` and
  `_imagingcms` — and the rest are compile-time switches inside `_imaging`. Everything else
  matches: both wheels ship the same set of `PIL/*.py` modules, including the plugins for
  formats that cannot be decoded. `libimagequant` is missing from the desktop wheel too, so
  `quantize(method=Image.Quantize.LIBIMAGEQUANT)` raises `ValueError: dependency required by
  this method was not enabled at compile time` in both places; plain `quantize()` works.

- **What failure looks like.** It differs by format, which matters when you are catching it.
  A WebP or AVIF file warns `image file could not be identified because WEBP support not
  installed` and then raises
  [`UnidentifiedImageError`](https://pillow.readthedocs.io/en/stable/PIL.html#PIL.UnidentifiedImageError)
  — the plugin declines the file, so it looks like a corrupt image rather than a missing
  codec. A JPEG 2000 file opens successfully and fails later, in `load()`, with `OSError:
  decoder jpeg2k not available`; a compressed TIFF fails the same way with `decoder libtiff
  not available`. Uncompressed TIFF is the exception that works, because Pillow decodes that
  one itself.

- **What `Image.save` can produce.** BLP, BMP, DDS, DIB, EPS, GIF, ICNS, ICO, IM, JPEG, MPO,
  MSP, PALM, PCX, PDF, PNG, PPM, QOI, SGI, SPIDER, TGA, TIFF and XBM — the desktop wheel's
  list minus exactly WebP, AVIF and JPEG 2000. Multi-frame saving (`save_all=True`) works for
  GIF, PNG (APNG), TIFF, PDF and MPO. TIFF writes only uncompressed: passing
  `compression="tiff_lzw"` (or `packbits`, `tiff_adobe_deflate`, `jpeg`) raises `OSError:
  encoder libtiff not available`. Asking for a format that is not there at all is a plain
  `KeyError: 'WEBP'`.

- **Text renders without shipping a font, in ASCII.**
  [`ImageFont.load_default(size=...)`](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html#PIL.ImageFont.load_default)
  returns a scalable TrueType font built from a face embedded in `ImageFont.py`, so there is
  no file to find. Its coverage is printable ASCII (U+0021–U+007E) plus
  `© « » ° ± ´ · ‘ ’ “ ”` and nothing else: accented Latin, Cyrillic, Greek, CJK, Arabic,
  Hebrew and Devanagari all come out as one identical `.notdef` box. `getbbox()` reports a
  width for that box, so nothing in the API tells you the text did not render.

- **Bundling a font.**
  [`ImageFont.truetype`](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html#PIL.ImageFont.truetype)
  wants a filesystem path or an open binary file object, and there is no system font
  directory on a phone to fall back on — `ImageFont.truetype("arial.ttf", 20)` raises
  `OSError: cannot open resource`. Put the `.ttf`/`.otf` in your app's `src/assets/` and open
  it relative to the module:

  ```python
  font = ImageFont.truetype(Path(__file__).parent / "assets" / "Inter.ttf", size=32)
  ```

  Because `truetype` also takes a file object, a font you downloaded into
  `FLET_APP_STORAGE_DATA` or embedded in your own source works the same way, with no path
  involved. What you will not get either way is complex-script shaping: Raqm is not compiled
  in, so `ImageDraw.text(...)` with `direction=`, `language=` or `features=` raises
  `KeyError: setting text direction, language or font features is not supported without
  libraqm`, and what you are left with is Pillow's basic layout — glyphs placed in logical
  order, with no bidi reordering and no joining. Asking for
  `layout_engine=ImageFont.Layout.RAQM` does not raise; it warns and quietly falls back to
  that same basic layout.

- **A PIL image reaches the screen without a temp file.**
  [`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src) accepts raw bytes, so
  encoding into an `io.BytesIO` and passing `buffer.getvalue()` is the whole trick — no file,
  no base64, no assets entry. Encode as PNG or JPEG. Note the asymmetry in the other
  direction: `ft.Image` can *display* a WebP because Flutter decodes it, while Pillow in the
  same app cannot open or write one.

- **The desktop-integration modules are inert here.**
  [`ImageGrab.grab()`](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html)
  raises `OSError: Pillow was built without XCB support` (there is no screen to grab from a
  Python process anyway);
  [`Image.show()`](https://pillow.readthedocs.io/en/stable/reference/ImageShow.html) finds no
  viewer and returns `False` without doing anything; `ImageTk` needs tkinter, `ImageQt` needs
  Qt and `ImageWin` is Windows-only. `EpsImagePlugin` can *write* EPS but rendering one back
  needs a Ghostscript binary, which is not on the device.

- **Size.** The Android wheels are 0.52–0.61 MB and unpack to 1.7–1.9 MB; the iOS device
  wheel is 1.19 MB and unpacks to 3.4 MB. iOS is bigger because libjpeg-turbo and FreeType
  are linked statically into the extensions there, while on Android they stay separate
  shared libraries that `flet-libjpeg` and `flet-libfreetype` contribute to the APK
  (`libjpeg.so` 0.6 MB, `libfreetype.so` 0.8 MB per ABI, plus a `libturbojpeg.so` that
  Pillow does not link). For scale: the desktop PyPI wheel is 4.5 MB and unpacks to 13 MB,
  nearly all of it the eighteen bundled native libraries these wheels do without.

## Build notes (maintainers)

Pillow builds with plain setuptools, but its `setup.py` hand-probes directories for the
libraries it wants instead of trusting the compiler's own search paths, so the recipe is a
patched `setup.py` plus a couple of environment variables rather than a configure step.
`meta.yaml` selects one of two patches by version, and each explains itself in a preamble
above its diff.

What follows from that shape, and is worth carrying around: auto-detection is switched off
entirely, so the feature set of these wheels is exactly the list of host deps. Adding a
codec means a new `flet-lib*` recipe, not a build flag, which is why WebP, AVIF, JPEG
2000, TIFF and LittleCMS are absent together rather than individually. PNG is the one
feature that needs no host dep: Pillow implements it in Python over its zlib `zip` codec,
so the platform's own zlib — the NDK sysroot's on Android, `/usr/lib/libz.1.dylib` on
iOS — carries it, and no `libpng` ends up in any shipped `.so`.

### Re-verify on a version bump

The sections above make claims about the built wheel that a bump can silently invalidate.
`tests/` already pins the codec set, the presence of `freetype2`, the absence of LittleCMS
and that `load_default()` renders; these are the claims no test covers.

- The second column of the codec table, and the claim that the two wheels otherwise ship
  the same `PIL/*.py` modules. Both are comparisons against the desktop PyPI wheel *of the
  same version*, so they have to be re-run against the new one rather than inferred from
  the device. Pillow's own `PIL SETUP SUMMARY`, printed at the end of the build, is the
  quickest read of what actually got compiled in.
- The list of formats `Image.save` accepts and which of them honour `save_all=True`. Those
  are plugin inventories, and Pillow adds and retires plugins between releases.
- What failure looks like per format — `UnidentifiedImageError` on WebP and AVIF versus
  the deferred `OSError: decoder ... not available` on JPEG 2000 and compressed TIFF. It
  depends on whether a plugin declines the file up front or only at `load()`.
- The glyph coverage attributed to `ImageFont.load_default()`. It comes from a face
  embedded in `ImageFont.py`, so it changes if upstream swaps that face.
- The claim that `_imagingft` links nothing beyond libz, libbz2, libSystem and Python. The
  iOS hunk that trims the transitive-link list assumes exactly that, and the assumption
  breaks if `flet-libfreetype` is ever rebuilt with brotli or libpng.
- The size figures, wheel and unpacked, on both platforms.
- That no `extract_packages` entry is needed, which holds only while nothing in `PIL`
  opens a data file next to itself at runtime.

Also worth a glance: which patch applied, and whether `patch` reported offsets or fuzz
rather than a clean application. A hunk that lands in the wrong place does not fail the
build; the host-leak filter in particular fails by letting a feature turn itself on, which
surfaces later as a wheel that no longer matches the table above.
