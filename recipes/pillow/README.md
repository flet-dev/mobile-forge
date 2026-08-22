# pillow

[`pillow`](https://python-pillow.github.io/) is the Python imaging library: open a file,
transform the pixels, draw on them, encode them again. On mobile it covers the work the UI
toolkit will not do for you — shrink a camera photo before uploading it, cut a thumbnail,
stamp a caption onto a picture, turn computed pixels into something
[`ft.Image`](https://flet.dev/docs/controls/image/) can display — on the device, offline.

These wheels are a **JPEG and PNG** build. WebP, AVIF, JPEG 2000, compressed TIFF and colour
management are not compiled in, so code that opens those files on your laptop raises on the
phone. The complete list is in [Things to know](#things-to-know).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pillow",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`image-filters`](examples/image-filters) — draws a picture with Pillow and filters it on device.

## Usage in a Flet app

Open, transform, encode into memory, hand the bytes to a control. There is no temporary file
and no base64 anywhere in that path:

```python
import io

import flet as ft
from PIL import Image

img = Image.open(path)
img.thumbnail((1024, 1024))          # resamples in place, keeps the aspect ratio
buffer = io.BytesIO()
img.save(buffer, "JPEG", quality=85)
view = ft.Image(src=buffer.getvalue(), gapless_playback=True)
```

[`Image.save`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.save)
writes to any binary file object and
[`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src) accepts `bytes` as
well as a path, so an `io.BytesIO` is the whole bridge between the two. Set
[`gapless_playback=True`](https://flet.dev/docs/controls/image/#flet.Image.gapless_playback)
whenever you replace those bytes repeatedly, or the control blanks between renders — every
new encode is a different byte string, so Flet has nothing to hold on to otherwise.

### Storage

The bundle Pillow is imported from is read-only, so anything you write goes to one of Flet's
storage directories. Output the user expects to keep — an edited photo, an export — belongs
in [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
img.save(os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "edited.jpg"))
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for thumbnails and other derivatives you can regenerate, and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for files that only have to survive the current operation.

A font or a seed image shipped with the app is an asset, not storage: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and build the path from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir),
which is where `flet build` actually puts `src/assets/`:

```python
font_path = os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "Inter.ttf")
```

Often you need no storage at all: encoding into an `io.BytesIO` and handing the bytes to
`ft.Image.src`, as at the top of this section, never touches the filesystem.

### Threading

Decoding, filtering and encoding are compiled loops, and at photo sizes they are long enough
to drop frames if you run them in an event handler. Push them to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch
exceptions inside the worker so a failure is visible rather than swallowed, and end with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) —
auto-update does not reach background threads.

Pillow releases the GIL around most of the expensive native work — resampling, the
convolution filters, the geometry transforms, JPEG decode — so a background resize really
does run alongside the UI rather than queueing behind the interpreter lock. Not every call
does it, so treat the overlap as an optimisation you get rather than a guarantee you can
schedule around.

What it does not buy you is a shared
[`Image`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image)
object. Nothing in Pillow serialises access to one, so give each worker its own or
[`copy()`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.copy)
before handing one over. Two threads filtering the same instance corrupt each other's pixels
without raising anything.

### Fonts and text

There is no system font directory on a phone to fall back on, so
[`ImageFont.truetype("arial.ttf", 20)`](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html#PIL.ImageFont.truetype)
raises `OSError: cannot open resource`. You have two options.

[`ImageFont.load_default(size=...)`](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html#PIL.ImageFont.load_default)
returns a scalable TrueType font built from a face embedded in `ImageFont.py`, so there is no
file to find and nothing to bundle. Its coverage is printable ASCII (U+0021–U+007E) plus
`© « » ° ± ´ · ‘ ’ “ ”` and nothing else: accented Latin, Cyrillic, Greek, CJK, Arabic,
Hebrew and Devanagari all come out as one identical `.notdef` box. Nothing raises, and
`getbbox()` reports a width for that box, so the only way to notice is to look at the pixels.
Treat it as an ASCII-only font.

For anything else, bundle a face. `truetype` takes a filesystem path or an open binary file
object, so a `.ttf`/`.otf` in your app's `src/assets/` works once you resolve it through
`FLET_ASSETS_DIR` as shown under [Storage](#storage):

```python
font = ImageFont.truetype(
    os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "Inter.ttf"), size=32
)
```

A font downloaded into `FLET_APP_STORAGE_DATA` or embedded in your own source works the same
way, with no path involved.

What you will not get either way is complex-script shaping. Raqm is not compiled in, so
[`ImageDraw.text(...)`](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html#PIL.ImageDraw.ImageDraw.text)
with `direction=`, `language=` or `features=` raises `KeyError: setting text direction,
language or font features is not supported without libraqm`, and what you are left with is
Pillow's basic layout — glyphs placed in logical order, with no bidi reordering and no
joining. Asking for `layout_engine=ImageFont.Layout.RAQM` does not raise; it warns and
quietly falls back to that same basic layout. Arabic and Hebrew therefore render in the wrong
order even when you bundle a font that has the glyphs.

### Decode memory

[`Image.open`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.open)
is lazy: it reads the header and defers the pixels until `load()`, or until the first
operation that needs them. The cost arrives then, and it is set by the pixel count rather
than the file size — a decoded image is about width × height × bands bytes, so a
12-megapixel phone photo is roughly 36 MB of RGB whatever the 3 MB JPEG on disk suggests.
Hold two of those plus an output buffer and you are in the range where Android and iOS kill
the app instead of raising `MemoryError`.

For JPEG, ask the decoder for less before it starts:

```python
img = Image.open(path)
img.draft("RGB", (1024, 1024))   # JPEG only: decode at 1/2, 1/4 or 1/8 scale
img.thumbnail((1024, 1024))      # exact size, and closes the gap draft left
```

[`draft()`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.draft)
picks the largest DCT scale factor that is still at least the size you asked for, so the
full-resolution buffer is never allocated at all; it is a no-op for PNG, which has no such
mode. `thumbnail()` then resamples in place to the exact box. Close images you opened from a
path when you are done — `Image.open` supports the context-manager protocol — and let large
intermediates go out of scope, because the pixel buffer is freed with the last reference and
nothing else triggers it.

### App size

Roughly 0.5–0.6 MB compressed per Android ABI, unpacking to about 1.5–1.8 MB; the iOS device
wheel is about 1.2 MB and unpacks to about 3.4 MB. Android's figure is not the whole cost:
`libjpeg.so` (0.6 MB) and `libfreetype.so` (0.8 MB) ship beside it once per ABI, so budget
around 3 MB per Android ABI rather than 1.8 — which is what makes narrowing `target_arch` worth
more here than the wheel size alone suggests. iOS links those statically, and the figure above
already includes them. Those are decimal MB, so re-measure
with a byte count rather than `du -h`, which reports binary units and shows a smaller number
for the same file. Almost all of it is the `_imaging` family of extensions, so there is no
data directory worth removing with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup).

This is a small payload by mobile standards, but the usual levers still apply if you are
counting: on Android use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI. Wheel size is not the amount added to the final APK or IPA;
packaging and compression decide that.

### Other considerations

**A desktop `flet run` has more codecs than the device does.** That run uses PyPI's own
Pillow wheel, which opens WebP, AVIF, JPEG 2000 and compressed TIFF — none of which open on
the phone. Every one of those is a working desktop run and a crash on device, and the format
comes from whatever the user picked in their gallery, so a desktop pass proves nothing about
image input. Validate on a device or emulator/simulator, and if you want to see what you
actually have, print
[`features.get_supported_codecs()`](https://pillow.readthedocs.io/en/stable/reference/features.html#PIL.features.get_supported_codecs)
from inside the app rather than trusting the interpreter on your laptop.

**Every path Pillow needs comes from your own code.** No module in `PIL` opens a data file
next to itself, which is why the wheel works unchanged from Android's zipped site-packages
and under Flet's default
[package compilation](https://flet.dev/docs/publish/#compilation-and-cleanup). Keep it that
way in your own code: derive font and image paths from `FLET_ASSETS_DIR`, not from
`__file__`. With compilation on, your modules are `.pyc` files on both platforms and
`__file__` no longer points where the source did.

## Things to know

- **Two codecs, and that is the whole list.**
  [`PIL.features.get_supported_codecs()`](https://pillow.readthedocs.io/en/stable/reference/features.html#PIL.features.get_supported_codecs)
  returns `['jpg', 'zlib']` on device, where the desktop PyPI wheel of the same version
  returns `['jpg', 'jpg_2000', 'zlib', 'libtiff']`. What that costs you:

  | | these wheels | desktop PyPI wheel |
  | --- | --- | --- |
  | JPEG | yes | yes |
  | PNG | yes | yes |
  | FreeType text — `ImageFont`, `ImageDraw.text` | yes | yes |
  | WebP | no | yes |
  | AVIF | no | yes |
  | JPEG 2000 | no | yes |
  | TIFF, compressed | no | yes |
  | Colour management — [`ImageCms`](https://pillow.readthedocs.io/en/stable/reference/ImageCms.html) | no | yes |
  | Complex-script text — Raqm | no | yes |

  Everything else matches. Both wheels ship the same set of `PIL/*.py` modules, including the
  plugins for the formats that cannot be decoded — which is why the failure arrives at
  `open()` or `load()` rather than at `import`.

- **What failure looks like.** It differs by format, which matters when you are catching it.
  A WebP or AVIF file warns `image file could not be identified because WEBP support not
  installed` and then raises
  [`UnidentifiedImageError`](https://pillow.readthedocs.io/en/stable/PIL.html#PIL.UnidentifiedImageError)
  — the plugin declines the file, so it looks like a corrupt image rather than a missing
  codec, and a `try`/`except` written for bad user input will swallow it. A JPEG 2000 file
  opens successfully and fails later, in `load()`, with `OSError: decoder jpeg2k not
  available`; a compressed TIFF fails the same way with `decoder libtiff not available`.
  Uncompressed TIFF is the exception that works, because Pillow decodes that one itself.

- **What `Image.save` can produce** is the desktop wheel's list minus exactly WebP, AVIF and
  JPEG 2000, so JPEG, PNG, GIF, BMP, TIFF and PDF are all there. Two edges are worth knowing:
  TIFF writes only uncompressed, so `compression="tiff_lzw"` (or `packbits`,
  `tiff_adobe_deflate`, `jpeg`) raises `OSError: encoder libtiff not available`; and asking
  for a format that is absent entirely is a plain `KeyError: 'WEBP'`, thrown by the format
  lookup before any encoding starts.

- **`ft.Image` decodes more formats than Pillow does.** Flutter, not Pillow, draws what you
  put on screen, so `ft.Image(src=blob)` displays a WebP fine in an app where
  `Image.open(io.BytesIO(blob))` raises on the same bytes. The asymmetry bites when you
  accept a file from the user,
  show it successfully, and only fail once you try to resize it. Encode as PNG or JPEG in the
  other direction and both sides agree.

- **The desktop-integration modules are inert here.**
  [`ImageGrab.grab()`](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html)
  raises `OSError: Pillow was built without XCB support` (there is no screen for a Python
  process to grab anyway);
  [`Image.show()`](https://pillow.readthedocs.io/en/stable/reference/ImageShow.html) finds no
  viewer and returns `False` without doing anything, which is the quiet one — it is the line
  people leave in from a desktop script. `ImageTk` needs tkinter, `ImageQt` needs Qt and
  `ImageWin` is Windows-only. `EpsImagePlugin` can *write* EPS, but rendering one back needs
  a Ghostscript binary that is not on the device.

## Build notes (maintainers)

### Recipe shape

Platform guessing is switched off in the patched `setup.py`, so the wheel's feature set is
exactly the host-dep list in `meta.yaml` and nothing the build runner happens to have
installed. That is the fact to carry around: **adding a codec means a new `flet-lib*` recipe,
not a build flag**, which is why WebP, AVIF, JPEG 2000, TIFF and LittleCMS are absent
together rather than individually, and why the consumer table above can be trusted to match
`requirements.host`. PNG is the exception that needs no host dep: Pillow implements it in
Python over its zlib `zip` codec, so the platform's own zlib — the NDK sysroot's on Android,
`/usr/lib/libz.1.dylib` on iOS — carries it and no `libpng` ends up in any shipped `.so`.
That is why `LDFLAGS: -lz` is in the recipe and why the codec table has one entry with no
matching host dep.

The two platforms differ in where the native code ends up, which is what the size figures
above reflect: on Android `flet-libjpeg` and `flet-libfreetype` stay separate shared
libraries contributed to the APK per ABI, while on iOS they are linked statically into the
extension modules. Nothing in the consumer API changes; only the payload shape does.

### Upgrade hazards

- **`flet-libfreetype` rebuilt with brotli or libpng breaks the iOS link.** The patch's iOS
  hunk trims `_imagingft`'s transitive-link list on the assumption that FreeType pulls in
  nothing beyond libz and libbz2. Bumping that recipe with extra features enabled surfaces
  here, in a different recipe, as a link failure.
- **Adding or removing a host dep silently rewrites the consumer codec table.** It is the
  same switch, so the table above and the `Image.save` inventory both have to be re-read from
  the built wheel afterwards, not reasoned about.
- **A patch that lands with offsets or fuzz does not fail the build.** Pillow moves the
  context these hunks match between releases. The host-leak filter is the dangerous one: when
  it misses, it fails *open* — a feature detects itself on the runner and switches itself on,
  and the result is a green build whose wheel no longer matches anything documented here.
  Check what `patch` reported, and read Pillow's own `PIL SETUP SUMMARY` at the end of the
  build, which is the quickest statement of what actually got compiled in.

### Re-verification checklist

The consumer sections make claims about the built wheel that a bump can silently invalidate.

- The second column of the codec table, and the claim that the two wheels otherwise ship the
  same `PIL/*.py` modules. Both are comparisons against the desktop PyPI wheel *of the same
  version*, so they have to be re-run against the new one rather than inferred from the
  device.
- The list of formats `Image.save` accepts and which of them honour `save_all=True`. Those
  are plugin inventories, and Pillow adds and retires plugins between releases.
- What failure looks like per format — `UnidentifiedImageError` on WebP and AVIF versus the
  deferred `OSError: decoder ... not available` on JPEG 2000 and compressed TIFF. It depends
  on whether a plugin declines the file up front or only at `load()`.
- The glyph coverage attributed to `ImageFont.load_default()`. It comes from a face embedded
  in `ImageFont.py`, so it changes if upstream swaps that face.
- That `draft()` still reaches the JPEG decoder's scaled-decode path, which is the whole
  basis of the memory advice.
- The size figures, compressed and unpacked, on both platforms. Re-measure from the wheels in
  decimal MB rather than scaling the old numbers.
- That nothing in `PIL` has started opening a data file next to itself, which is what keeps
  Android's zipped site-packages working without an
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry.

### Coverage gaps

`tests/` has four tests: a JPEG open plus PNG round-trip, a bundled-TTF render, the codec
set, and `load_default()`. The consumer sections above make roughly twenty behavioural
claims, so a green run is much weaker evidence than it looks. Specifically:

- `test_only_jpeg_and_zlib_codecs_are_built` asserts `{"jpg", "zlib"} <= codecs` and the
  absence of `webp`, `jpg_2000` and `libtiff`. It does not assert the set is exactly those
  two, so "that is the whole list" remains an inspection claim about the wheel.
- `test_default_font_needs_no_file` asserts `image.getbbox() is not None` on a white RGB
  canvas. `getbbox()` trims zero-valued pixels and white is non-zero, so that assertion holds
  whether or not a single glyph drew. Nothing currently tests that `load_default()` renders,
  and the ASCII-only coverage claim is untested outright.
- Untested entirely: every `Image.save` format except PNG, `save_all`, the per-format failure
  modes, `ImageCms`, the Raqm fallback warning, `draft()`, `ImageGrab`/`show()`/`ImageTk`,
  and resolving a font through `FLET_ASSETS_DIR` — the example is the only thing that
  exercises the bytes-to-`ft.Image` path, and it does so with `load_default()`.
