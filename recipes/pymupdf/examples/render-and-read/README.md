# pymupdf render and read

A three-page PDF, built in memory when the app starts, then shown one page at a time as a
rendered image. Page through it, drag the zoom from 1× to 4× and watch the caption report
the pixel count and the milliseconds it took, and type a word into the search field to see
every occurrence highlighted in yellow on the page.

What it demonstrates:

- **Rasterising a page**, which is the thing you ship PyMuPDF to a phone for.
  [`page.get_pixmap(matrix=...)`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_pixmap)
  renders through MuPDF and
  [`pixmap.tobytes("png")`](https://pymupdf.readthedocs.io/en/latest/pixmap.html#Pixmap.tobytes)
  encodes the result, which
  [`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src) accepts as bytes —
  no temp file, no base64.
- **That the fonts are inside the wheel.** Page 1 sets the same sentence in four of the
  base-14 faces. Nothing loads a font file; a phone has no PostScript fonts and no
  fontconfig, and the glyphs still draw because MuPDF compiles them into the library.
- **Vector, not pixels.** Page 2 is a bar chart, a Bézier and three primitives written with
  page operators, so raising the zoom produces real detail rather than a bigger blur. The
  same slider on a page of scanned images would only enlarge them.
- **Text that survives the render.**
  [`page.search_for`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.search_for)
  returns a rectangle per hit, in page points; the app turns each into a
  [highlight annotation](https://pymupdf.readthedocs.io/en/latest/page.html#Page.add_highlight_annot),
  renders, then deletes the annotations again so the document is unchanged between renders.
  Hit coordinates do not move when you zoom — only the renderer's scale does.
- **Compute off the UI thread** — every render runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, driven from the slider's `on_change_end` so one gesture means one
  rasterisation, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a background
  thread needs.

The document is generated rather than bundled, so the example ships no asset — and
composing a PDF is itself half of what PyMuPDF does.

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
