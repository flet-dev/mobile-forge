# pymupdf

[`pymupdf`](https://pymupdf.readthedocs.io/) is the Python binding for
[MuPDF](https://mupdf.com/), and it is the reason a phone can do anything useful with a PDF
without sending it somewhere. It opens PDF, XPS, EPUB, CBZ and image files; renders any page
to a bitmap at any scale; pulls the text back out with coordinates; and writes documents from
scratch. On mobile that matters twice over — the file never leaves the device, and rendering
a page locally is the difference between a viewer and a download button.

**The wheel is self-contained: four native libraries ship inside it.** MuPDF itself
(`libmupdf`), its C++ wrapper (`libmupdfcpp`), the SWIG module over that wrapper (`_mupdf`)
and PyMuPDF's own accelerator (`_extra`). There is no companion `flet-lib*` package to add —
but the four have to find each other at load time, and how that works differs between the
platforms, so it is described under [Android notes](#android-notes) and
[iOS notes](#ios-notes) rather than here.

Import it as `pymupdf`. The historical `fitz` name is still shipped as a separate top-level
module and still works, which matters because most PyMuPDF code you will find in the wild
opens with `import fitz`.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pymupdf",
]
```

Nothing else to configure on Android: one extra wheel comes along and needs no entry of its
own, `flet-libcpp-shared`, the NDK C++ runtime that MuPDF's C++ wrapper links against. On
iOS there is no such dependency — the system `/usr/lib/libc++.1.dylib` covers it.

**iOS needs Flet 0.86 or newer.** The iOS wheel relies on serious-python 4.2.1 (PR #223)
relocating its bundled libraries into framework bundles, and on the marker files that leaves
behind; on an older Flet the libraries land somewhere the loader will not look and the app
dies at `import pymupdf` with `Library not loaded: @rpath/libmupdf.dylib`. Android has no
such floor.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Under Flet 0.86 Android ships site-packages as a compressed archive, which
breaks any package that opens a bundled data file by path — pymupdf has none. The only
non-code file in the wheel is an empty `py.typed`.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS
device and simulator, on Python 3.12, 3.13 and 3.14.

## Storage

Most of the time you want no file at all. A document can be opened from a `bytes` object and
written back to one, and a rendered page goes straight into a Flet control:

```python
doc = pymupdf.open(stream=blob, filetype="pdf")           # no path
png = doc[0].get_pixmap(dpi=144).tobytes("png")
image.src = png                                            # ft.Image.src takes bytes
```

When a document does belong on disk, put it in Flet's app storage — the working directory is
not a durable location on either platform:

```python
import os

data = os.getenv("FLET_APP_STORAGE_DATA", ".")             # survives restarts and updates
doc.save(os.path.join(data, "report.pdf"))
```

[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is for documents the user expects to keep;
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
is for anything you can regenerate, such as a cache of rendered page images, and may be
cleared between launches. A PDF shipped with the app is an asset: put it under `src/assets/`
and read it from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

[`doc.save(path, incremental=True)`](https://pymupdf.readthedocs.io/en/latest/document.html#Document.save)
needs the document to have been opened from that same path, so it is only available for
files you own on disk — not for the `stream=` case.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`render-and-read`](examples/render-and-read) — builds a three-page PDF, rasterises it at a
  zoom you choose, and highlights search hits on the rendered page.

## Threading

**PyMuPDF does not support concurrent use, and it will not tell you when you break the
rule.** Upstream is unambiguous — *"PyMuPDF does not support multithreaded use, even with
Python's newer free-threading mode"* — and the package calls MuPDF's
`reinit_singlethreaded()` at import, which switches off the locking MuPDF would otherwise
use. Two overlapping calls do not raise; they corrupt state, and on a phone that surfaces as
a native crash with no Python traceback.

None of the four libraries starts a thread of its own: no extension in either wheel
references `pthread_create`, or any OpenMP symbol. So all the concurrency is whatever your
app introduces.

Rendering is genuinely slow enough to need a thread — a full page at high zoom is several
megapixels — and MuPDF releases the GIL while it works, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) really
does keep the UI live. But `run_thread` submits to a thread *pool*, so two handlers started
close together will run inside MuPDF at the same time. Serialise them yourself:

```python
MUPDF = threading.Lock()

def work():
    with MUPDF:
        png = DOC[index].get_pixmap(dpi=dpi).tobytes("png")
    sheet.src = png
    page.update()          # auto-update does not reach background threads
```

Disabling the button that starts the work is not a substitute — it cannot catch a tap already
in flight. Note also that exceptions raised inside `run_thread` are swallowed, so wrap the
body if you want to see a `pymupdf.FileDataError` rather than a screen that never updates.
If you need real parallelism, upstream's answer is multiprocessing with one document per
process, which is not available to you here.

## Android notes

The four libraries are installed as `jniLibs` and resolve each other by `DT_NEEDED` name at
`dlopen` time, which is why this recipe builds MuPDF with unversioned sonames: an APK only
accepts bare `lib*.so`, so a stock `libmupdf.so.27.2` soname would leave `_mupdf` asking for
a file that cannot be packaged. What ships is `libmupdf.so`, and the dependency entries
naming it match.

`libmupdfcpp`, `_mupdf` and `libmupdf` all link `libc++_shared.so`, which is the
`flet-libcpp-shared` dependency in [Install](#install); Android does not provide the NDK C++
runtime itself. Every `PT_LOAD` segment is 16 KB-aligned, so the wheels load on Android 15
devices with 16 KB pages.

| | arm64-v8a | armeabi-v7a | x86_64 |
| --- | --- | --- | --- |
| `libmupdf.so` | 55.4 MB | 52.7 MB | 56.0 MB |
| `_mupdf` | 12.3 MB | 11.3 MB | 12.4 MB |
| `libmupdfcpp.so` | 1.9 MB | 1.5 MB | 2.0 MB |
| `_extra` | 0.2 MB | 0.2 MB | 0.2 MB |
| **wheel / unpacked** | **40.8 / 73 MB** | **40.2 / 69 MB** | **41.3 / 74 MB** |

## iOS notes

All four binaries are `MH_DYLIB`, which is what `flet build ipa` requires — a CMake-style
`MH_BUNDLE` fails at link rather than at import.

Their inter-dependencies are the interesting part. serious-python relocates each bundled
binary into its own framework bundle, but rewrites only the extension modules' own
install-ids: a `.dylib`'s id, and every dependency entry in every file, is left as it was.
So this recipe points them at the framework paths at build time, and `pymupdf/__init__.py`
loads `libmupdf` and then `libmupdfcpp` with `RTLD_GLOBAL` before importing `_extra` — which
lets dyld satisfy each `@rpath` reference from an image that is already in memory. That
preload is why the [Flet floor](#install) exists. It is inert on Android and on desktop.

There is no `libc++_shared` equivalent: the extensions link the system `/usr/lib/libc++.1.dylib`.

| | device arm64 | simulator arm64 | simulator x86_64 |
| --- | --- | --- | --- |
| `libmupdf.dylib` | 54.3 MB | 54.9 MB | 55.0 MB |
| `_mupdf.so` | 12.9 MB | 13.0 MB | 12.9 MB |
| `libmupdfcpp.dylib` | 1.8 MB | 1.8 MB | 1.8 MB |
| `_extra.so` | 0.2 MB | 0.2 MB | 0.2 MB |
| **wheel / unpacked** | **40.3 / 73 MB** | **40.9 / 73 MB** | **41.0 / 73 MB** |

## Things to know

- **Fonts are compiled into the library, and that is most of the wheel.** MuPDF turns its
  bundled fonts into C arrays at build time, so text renders on a device that has no
  PostScript fonts and no fontconfig — including scripts a PDF did not embed a font for.
  This build keeps the whole set: the base-14 faces, 159 Noto families, `DroidSansFallback`
  and `SourceHanSerif` for CJK, Arabic, Tibetan and emoji. It is also why `libmupdf` here is
  55 MB against 31 MB in the same-version wheel PyPI ships for macOS, which excludes most of
  the Noto set. If your PDFs embed their own fonts — most produced by real software do — you
  are paying for a fallback you will not use, but the choice is made at build time and
  cannot be changed from an app.
- **The base-14 faces are Latin-1 only.** `page.insert_text(..., fontname="helv")` with an em
  dash, a curly quote or any non-Latin-1 character silently rasterises it as `?`. There is no
  exception; the string you read back with `get_text` is not what you see. Use
  [`insert_htmlbox`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.insert_htmlbox),
  which lays text out through MuPDF's HTML engine and picks a font that has the glyph, or
  embed a font of your own with
  [`insert_font`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.insert_font).
- **There is no OCR.** MuPDF is built without Tesseract, so
  [`page.get_textpage_ocr()`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_textpage_ocr)
  and anything else that builds an OCR device raises `OCR Disabled in this build`. It fails
  loudly rather than returning nothing, which is the good case — but a scanned PDF is a page
  of images to this build: it renders perfectly and extracts no text. Tesseract would bring
  its own language data files as well as the engine, which is not something to add by
  accident.
- **There is no signature support.** MuPDF is built without libcrypto, so PKCS#7 signing and
  signature *verification* are unavailable. Encryption is unaffected — the standard security
  handler is MuPDF's own code, so opening a password-protected PDF with
  `pymupdf.open(path)` then `doc.authenticate(password)` works, as does saving with
  `encryption=` and owner/user passwords.
- **Also absent:** barcode generation and decoding — MuPDF's own entry points answer
  `Barcode functionality not included`, though PyMuPDF exposes no Python API for them at this
  version anyway, which is why the ~2 MB ZXing library is left out. Likewise the `curl`,
  `X11` and `glut` integrations, which are desktop viewer plumbing with no meaning in a Flet
  app.
- **Rendering is the API to reach for, and the pixmap is the memory hazard, not the PNG.**
  `page.get_pixmap(dpi=...)` returns raw RGB samples, and they grow with the square of the
  scale: a text-filled A4 page is 1.4 MB at 72 dpi, 5.7 MB at 144 and **24.9 MB at 300**,
  where the PNG `tobytes("png")` produces is 14 KB, 248 KB and 522 KB. Only the PNG crosses
  into Flet. Render at the scale you will actually display, drop the pixmap as soon as you
  have the bytes, and set
  [`gapless_playback=True`](https://flet.dev/docs/controls/image/) on the `ft.Image` or it
  blanks between frames.
- **Size.** The wheel is about 41 MB and unpacks to 69–74 MB depending on the slice, nearly
  all of it `libmupdf`. There is no test suite or header directory to trim with
  `[tool.flet.cleanup]` — the library *is* the package. What you can do is ship fewer copies:
  on Android, `split_per_abi` or a `target_arch` narrowed to the ABIs you support.
- **The Python API is upstream's, unchanged**, so upstream's documentation and the answers
  you find online apply as written. The wheel ships the same 13 Python files as the
  same-version desktop wheel, nine of them byte-identical; the four that differ are
  `__init__.py` (the iOS preload described above), `_build.py` (build metadata) and the two
  SWIG-generated layers, which are regenerated per target by construction.
- **`flet run` on your desktop uses PyPI's wheel, not this one.** That build has a different
  font set and different compiled-in features, so a desktop run proves your code and not the
  device build. `pymupdf.TOOLS.fitz_config` reports what the wheel actually has, and it
  differs between the two.

## Build notes (maintainers)

Both patches carry their own explanation in a preamble, and every `meta.yaml` setting is
justified in a comment beside it; what follows is what neither file records.

**Shape.** This is a single self-contained recipe, not the `flet-libmupdf` native library
plus consumer that the chain-recipe pattern would suggest — and a working `flet-libmupdf`
was in fact built and then abandoned. PyMuPDF's build does not consume an external MuPDF in
any useful way: it downloads its own copy, and then generates the C++ wrapper *and* the SWIG
layer from those exact headers, so a separately-built MuPDF only duplicates the compile
without removing a step. Everything the recipe does is therefore aimed at the one upstream
build, through `MUPDF_MAKE` and a patch.

**Why the codegen is the hard part.** PyMuPDF parses MuPDF's headers with libclang and
generates a C++ wrapper, on the build host, under crossenv's cross-python. That interpreter
reports the *target* — `platform.system()` is `Android` or `iOS` — which matches no branch
upstream has, and libclang is given no sysroot, so the generator falls back to hardcoded
64-bit type sizes. That is the whole reason the patch exists, and why the recipe cannot be
reduced to environment variables.

**pipcl is pinned in `requirements.build`, and that pin is load-bearing.** PyMuPDF asks for a
bare `pipcl`, which is both the build backend and the linker for `_mupdf`/`_extra`, and the
patch monkeypatches one of its functions. It shipped twelve releases in four months. Raise
the pin deliberately, with a build, rather than letting it float.

**1.28 is a separate project, not a bump.** PyMuPDF 1.28 rewrote `setup.py` around `pipcl`'s
API — five of the eight hunks reject — and removed `PYMUPDF_SETUP_FLAVOUR` entirely, so the
dev headers and static library this recipe drops would ship unconditionally and need a new
hunk to suppress. MuPDF 1.28 also vendors `cmark-gfm`, an unproven C dependency for these
five slices. The MuPDF-script surgery, by contrast, applies unchanged. Do it as its own
change with its own CI run.

What to re-verify on a bump, in rough order of how quietly it can go wrong:

- **That barcode is still off.** `MUPDF_MAKE` says `barcode=no`, and that setting alone does
  nothing: MuPDF's wrapper script appends `barcode=yes` after it and make lets the last
  command-line assignment win, so the patch has to rewrite that token too. If either half is
  lost the build stays green and ZXing quietly returns. Check `strings libmupdf.so | grep
  ZXing` is empty.
- **The sonames, on Android.** They must be unversioned. A change in how `SO_VERSION=` is
  handled upstream produces a wheel that builds, packages and then fails to `dlopen` on
  device — the first symptom is an on-device test failure, not a build error.
- **`_extra` on both platforms.** It is the one library pipcl links from its own flag list,
  ignoring everything forge exports, so it is where dropped link flags show up: 16 KB
  `PT_LOAD` alignment on Android, and `LC_BUILD_VERSION` with a sane `minos` rather than a
  legacy `LC_VERSION_MIN_IPHONEOS` on iOS. Both are re-added by the patch and both are easy
  to lose.
- **Mach-O filetype `MH_DYLIB` on all three iOS slices**, and that the preload block still
  sits above the `from . import extra` line it is meant to precede — an upstream reshuffle of
  `src/__init__.py` moves the import without failing the patch.
- **The compiled-out feature list**, read out of the built library rather than off the
  `MUPDF_MAKE` flags. The barcode case above is precisely why: a flag in the recipe is not
  evidence about the wheel.
- **Whether `extract_packages` is still unnecessary.** It holds only while nothing in the
  package opens a bundled file by path. A new data file upstream flips it, and the symptom is
  an import failure on Android only.
- **The font set**, which is the size story and the [Things to know](#things-to-know) claim
  about non-Latin text. If shrinking the wheel ever becomes the priority, MuPDF's `TOFU`
  family of defines is the lever — `tofu=yes` drops the Noto fonts and keeps CJK, which is
  roughly what upstream's own desktop wheels do — but it changes what renders on a device
  and has not been tested here.
- **All sizes and counts.** Re-measure from the built wheels; do not scale.

The tests cover import through both names, page composition, rendering to real pixels, the
base-14 fonts, PNG encoding, search geometry, structured text, image round-trip, page
surgery, an encrypted round-trip, PNG and CBZ input, and a save/reopen through the
filesystem. What they do not touch: `insert_htmlbox` and the HTML engine behind it, EPUB and
XPS input (both only asserted through `fitz_config`), and any of the compiled-out features —
the absence of OCR and signing is checked by reading the built library, not on device.
