# pymupdf

[`pymupdf`](https://pymupdf.readthedocs.io/) is the Python binding for
[MuPDF](https://mupdf.com/). It opens PDF, XPS, EPUB, CBZ and image files; renders pages to
bitmaps; extracts text with coordinates; and creates or edits documents. In a Flet app, those
operations happen on the device, so a document does not need to leave the app for rendering or
text extraction.

Import the package as `pymupdf`. The historical `fitz` name is still included as a separate
top-level module, so existing code that begins with `import fitz` continues to work.

## Install

Add PyMuPDF to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pymupdf",
]
```

**iOS requires Flet 0.86.0 or newer.** The wheel relies on the native-library relocation and
marker-file support shipped by the corresponding serious-python runtime. With an older Flet
version, the app fails at `import pymupdf` with
`Library not loaded: @rpath/libmupdf.dylib`. A bare `flet` dependency resolves to a current
release; this matters when another dependency or an application pin holds Flet below 0.86.0.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`render-and-read`](examples/render-and-read) — builds a three-page PDF, rasterises it to an
  image, and highlights search hits on the rendered page.

## Usage in a Flet app

### Storage

PyMuPDF can work entirely in memory. Open a document from `bytes`, render a page, and send the
encoded result directly to [`ft.Image`](https://flet.dev/docs/controls/image/):

```python
doc = pymupdf.open(stream=blob, filetype="pdf")
png = doc[0].get_pixmap(dpi=144).tobytes("png")
view = ft.Image(src=png)
```

Put documents the user expects to keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
data_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
doc.save(os.path.join(data_dir, "report.pdf"))
```

From Flet 0.86.0, this durable directory is also the process working directory in production
and under `flet run`, so a relative write lands there. Using the environment variable
explicitly still makes the destination and intent clear.

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for regenerable rendered pages and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for throwaway intermediate files. A PDF shipped with the application is an asset: put it in
the [assets directory](https://flet.dev/docs/cookbook/assets) and use
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
when PyMuPDF needs an absolute path.

[`Document.save(..., incremental=True)`](https://pymupdf.readthedocs.io/en/latest/document.html#Document.save)
requires the document to have been opened from the same path. It is not available for a
document opened with `stream=`.

### Threading

**PyMuPDF does not support concurrent use.** Upstream warns that multithreaded use can produce
incorrect behavior or crash Python, and the package does not reliably turn an overlap into a
catchable exception.

Rendering is slow enough to move off the Flet UI thread, and MuPDF releases the GIL while it
works. Use [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread),
but serialise every PyMuPDF call behind one application-wide lock because `run_thread` uses a
thread pool and two quick events can overlap:

```python
MUPDF_LOCK = threading.Lock()

def render_page():
    try:
        with MUPDF_LOCK:
            png = DOC[index].get_pixmap(dpi=dpi).tobytes("png")
        sheet.src = png
    except Exception as exc:
        status.value = str(exc)
    page.update()
```

Disabling the initiating button is useful UI feedback but is not a concurrency guard: a second
handler may already be queued. Keep the lock around the complete native operation, catch and
display worker exceptions, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

Upstream recommends multiprocessing for parallel PyMuPDF workloads on desktop, with each
process opening its own document. Flet does not support
[`multiprocessing`](https://flet.dev/docs/cookbook/multiprocessing/) on Android or iOS, so a
mobile app cannot use that route. [`subinterpreters`](https://flet.dev/docs/cookbook/subinterpreters/)
are not a fallback here either: importing PyMuPDF inside one raises
`ImportError: module _extra does not support loading in subinterpreters`. On mobile, treat one
locked worker at a time as the supported execution model.

### Rendering and memory

[`Page.get_pixmap`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_pixmap) returns
raw pixel samples, whose memory grows with the square of the rendering DPI. A text-filled A4
page measured approximately 1.4 MB at 72 dpi, 5.7 MB at 144 dpi and 24.9 MB at 300 dpi before
PNG encoding. The encoded PNG from that measurement was much smaller, but the raw pixmap still
has to exist while it is produced.

Render at the scale the UI actually needs, convert the pixmap to PNG bytes, and release it
promptly. Set
[`gapless_playback=True`](https://flet.dev/docs/controls/image/#flet.Image.gapless_playback)
when replacing pages so the image does not blank between renders.

### App size

Expect approximately 40–41 MB of compressed wheel and 69–74 MB unpacked per architecture.
Most of that is `libmupdf` and its compiled-in fonts, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) cannot
meaningfully reduce it.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These figures describe the package payload, not the exact
amount added to the final APK or IPA; packaging and compression determine that result.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel. The Python API is the same, but that wheel can
have a different compiled-in font and optional-feature set. Read
`pymupdf.TOOLS.fitz_config` when the distinction matters, and validate mobile-specific
behavior on a device or emulator/simulator.

## Things to know

- **There is no OCR.** MuPDF is built without Tesseract, so
  [`page.get_textpage_ocr()`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_textpage_ocr)
  raises `OCR Disabled in this build`. A scanned PDF still renders, but it contains no
  extractable text unless the document already has a text layer.

- **There is no signature creation or verification.** MuPDF is built without libcrypto, so
  PKCS#7 signing and verification are unavailable. Password-based PDF encryption is separate
  and remains supported: `doc.authenticate(password)` opens a protected document, and
  `Document.save()` accepts encryption and owner/user password options.

- **The built-in fonts make rendering self-contained but have an insertion trap.** The wheel
  compiles the base-14 faces and a broad Noto/CJK fallback set into MuPDF, so documents render
  without fontconfig or system PostScript fonts. However,
  `page.insert_text(..., fontname="helv")` uses a Latin-1 base-14 face: an em dash, curly quote
  or other unsupported character is silently rendered as `?`. Use
  [`insert_htmlbox`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.insert_htmlbox),
  which selects a font containing the glyph, or embed one explicitly with
  [`insert_font`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.insert_font).
- **Licensing:** [AGPL-3.0](https://spdx.org/licenses/AGPL-3.0.html). That is upstream's deliberate choice, not an accident:
  [Artifex](https://artifex.com/licensing/) sells a commercial PyMuPDF licence precisely so
  closed-source products can use it, and the AGPL is the other half of that business model.
  Shipping it in an app you do not publish the source of is the case the commercial licence exists
  for — take it up with Artifex before release rather than after. For an open-source app under a
  compatible licence, nothing to do. The licence text ships in the wheel under
  `dist-info/licenses/`. Flagging it, not advising you — we are not lawyers.

## Build notes (maintainers)

### Recipe shape

This is one self-contained recipe rather than a `flet-libmupdf` native-library recipe followed
by a PyMuPDF consumer. That split was built and rejected: PyMuPDF downloads its own matching
MuPDF source and generates the C++ wrapper and SWIG layer from those exact headers, so a
separately built MuPDF duplicates work without removing a build step.

The resulting wheel contains four interdependent native binaries: MuPDF (`libmupdf`), its C++
wrapper (`libmupdfcpp`), the SWIG module (`_mupdf`) and PyMuPDF's accelerator (`_extra`). The
patch preambles own the crossenv code-generation and iOS preload explanations; `meta.yaml`
comments own individual build settings. Do not duplicate those mechanisms here.

### Upgrade hazards

The `pipcl` build requirement is deliberately pinned. It is both the build backend and the
linker for `_mupdf` and `_extra`, and the cross-compilation patch depends on its current API.
Raise the pin only with a complete rebuild and device test.

Moving to the 1.28 source series is not a routine version bump. Its `setup.py` uses a rewritten
`pipcl` API, removes `PYMUPDF_SETUP_FLAVOUR`, and introduces another vendored native dependency.
Treat that migration as a recipe redesign with its own validation pass; remove this warning
once that work has landed.

### Re-verification checklist

- **Android sonames and dependencies:** `libmupdf`, `libmupdfcpp` and `_mupdf` must refer to
  unversioned `lib*.so` names that can be packaged as `jniLibs`, and the C++ binaries must still
  receive `libc++_shared.so` through the wheel dependency.
- **Android 16 KB alignment:** Inspect every `PT_LOAD` segment, especially `_extra`, whose
  linker invocation does not inherit all of forge's flags automatically.
- **iOS file types and loading:** All four binaries must be `MH_DYLIB`, and the preload block
  must still execute before `pymupdf.extra` imports the extension modules.
- **Compiled features:** Read them from the built library or `fitz_config`; recipe flags alone
  are not proof that OCR, libcrypto and barcode support stayed disabled.
- **Android package layout:** Test from zipped site-packages. Add `extract_packages` to consumer
  guidance only if a real runtime filesystem read makes it mandatory, and include the failure
  symptom.
- **Fonts:** Recheck the set that underpins the multilingual rendering, insertion guidance and
  size figures. MuPDF's `TOFU` configuration is the build-time size lever, but changing it also
  changes rendering behavior.
- **Size:** Re-measure the compressed and unpacked ranges from the resulting wheels rather than
  scaling old figures.

### Coverage gaps

The device tests cover import through both names, document composition, real-pixel rendering,
base-14 fonts, PNG encoding, search geometry, structured text, image round-trip, page editing,
encryption, PNG and CBZ input, and a save/reopen filesystem round-trip. They do not exercise
`insert_htmlbox`, EPUB or XPS input, or the deliberately compiled-out features. Keep those gaps
in mind when changing any corresponding consumer claim.
