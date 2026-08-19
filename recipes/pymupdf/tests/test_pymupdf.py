"""On-device tests for PyMuPDF.

The wheel ships four interdependent native libraries — libmupdf, libmupdfcpp,
_mupdf (the SWIG wrapper over MuPDF's C++ API) and _extra — so the first thing
these tests prove is that all four resolve and load. Everything after that
exercises a layer that a cross-compiled MuPDF can plausibly get wrong: the
rasteriser, the base-14 fonts compiled into the library, the image codecs, and
the PDF writer.
"""

import pymupdf


def render(page, dpi=72):
    """Rasterise a page and return (pixmap, count of non-white pixels).

    The count is what separates "MuPDF rendered something" from "MuPDF returned
    a correctly-sized blank" — a missing font or a broken rasteriser produces
    the latter, and only the pixel data tells them apart.
    """
    pix = page.get_pixmap(dpi=dpi)
    samples = pix.samples
    ink = sum(1 for i in range(0, len(samples), pix.n) if samples[i] != 0xFF)
    return pix, ink


def test_import_names():
    """Both `pymupdf` and the legacy `fitz` alias import and are the same build.

    Most code in the wild still says `import fitz`, so the alias package has to
    survive packaging; it is a separate top-level module, not a re-export.
    """
    import fitz

    assert fitz.__name__ == "fitz"
    assert fitz.Document is pymupdf.Document
    # pymupdf.mupdf is the SWIG wrapper over MuPDF's C++ API; reaching it means
    # _mupdf and libmupdfcpp loaded, not just _extra.
    from pymupdf import mupdf

    assert mupdf.FZ_VERSION


def test_open_and_read():
    """Create a one-page PDF in memory, re-open it and read the text back."""
    src = pymupdf.open()
    page = src.new_page()
    page.insert_text((72, 72), "Hello mobile-forge")
    pdf_bytes = src.tobytes()
    src.close()

    dst = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    assert dst.page_count == 1
    text = dst[0].get_text()
    dst.close()

    assert "Hello mobile-forge" in text


def test_metadata():
    """Document metadata survives a write/re-read round trip."""
    doc = pymupdf.open()
    doc.new_page()
    doc.set_metadata({"title": "test", "author": "ci"})
    blob = doc.tobytes()
    doc.close()

    rt = pymupdf.open(stream=blob, filetype="pdf")
    md = rt.metadata
    rt.close()

    assert md["title"] == "test"
    assert md["author"] == "ci"


def test_render_page_to_pixels():
    """Rendering produces real pixels, at the size and depth asked for.

    This is the test that proves the MuPDF rasteriser was cross-compiled into
    something that runs: `get_pixmap` walks the display list and writes RGB
    samples. A page with a filled rectangle on it must come back with ink.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=100)
    page.draw_rect(pymupdf.Rect(20, 20, 180, 80), color=(0, 0, 0), fill=(0, 0, 0))

    pix, ink = render(page)
    doc.close()

    assert (pix.width, pix.height) == (200, 100)
    assert pix.n == 3  # RGB, no alpha
    assert len(pix.samples) == 200 * 100 * 3
    # The rectangle covers 160x60 = 9600 px; allow for antialiasing at the edges.
    assert ink > 9000


def test_base14_fonts_are_built_in():
    """Text renders with no font files on disk — the base-14 set is compiled in.

    MuPDF turns its bundled fonts into C arrays at build time, so a phone with
    no fontconfig and no /usr/share/fonts still draws glyphs. If that codegen
    were skipped, this page would rasterise blank while `get_text` still
    reported the string, so the assertion has to be about pixels.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=60)
    page.insert_text((10, 40), "Hamburgefonstiv", fontname="helv", fontsize=18)

    _, ink = render(page)
    doc.close()

    assert ink > 200


def test_font_variants_differ():
    """The base-14 faces are distinct fonts, not one face under many names.

    Same string, same size, three of the standard PDF faces: serif, sans and a
    fixed-pitch face. Their glyph coverage differs, so the rendered ink differs
    — which is only true if each name resolved to its own compiled-in font.
    """
    inks = {}
    for fontname in ("helv", "tiro", "cour"):
        doc = pymupdf.open()
        page = doc.new_page(width=240, height=60)
        page.insert_text((10, 40), "Hamburgefonstiv", fontname=fontname, fontsize=18)
        _, inks[fontname] = render(page)
        doc.close()

    assert all(v > 200 for v in inks.values())
    assert len(set(inks.values())) == 3


def test_pixmap_to_png():
    """A rendered page encodes to PNG, which is how it reaches a Flet control.

    Exercises MuPDF's bundled zlib and PNG writer. The magic number is checked
    rather than the length, because a truncated or headerless blob would still
    have a plausible size.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=120, height=60)
    page.draw_circle(pymupdf.Point(60, 30), 25, color=(1, 0, 0), fill=(1, 0, 0))
    png = page.get_pixmap(dpi=72).tobytes("png")
    doc.close()

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # IHDR carries the dimensions as big-endian uint32s at a fixed offset.
    assert int.from_bytes(png[16:20], "big") == 120
    assert int.from_bytes(png[20:24], "big") == 60


def test_search_returns_geometry():
    """`search_for` locates a string and returns its rectangle on the page.

    Text search runs over the same structured-text extraction the renderer
    builds, so a hit with sane coordinates shows the text pipeline agrees with
    the layout the page was written with.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((50, 100), "findable", fontsize=14)
    blob = doc.tobytes()
    doc.close()

    rt = pymupdf.open(stream=blob, filetype="pdf")
    hits = rt[0].search_for("findable")
    misses = rt[0].search_for("absent")
    rt.close()

    assert len(hits) == 1
    rect = hits[0]
    assert 40 < rect.x0 < 60
    assert 80 < rect.y0 < 105
    assert rect.width > 10 and rect.height > 5
    assert misses == []


def test_structured_text_dict():
    """`get_text("dict")` returns the block/line/span tree with font details.

    The dict form is what apps use to lay text out themselves, and it reaches
    further into MuPDF's stext machinery than the plain-string form.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "structured", fontname="helv", fontsize=11)
    blob = doc.tobytes()
    doc.close()

    rt = pymupdf.open(stream=blob, filetype="pdf")
    span = rt[0].get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
    rt.close()

    assert span["text"] == "structured"
    assert span["size"] == 11
    assert "Helvetica" in span["font"]


def test_image_roundtrip():
    """A PNG image embeds into a page and comes back out through the extractor.

    Covers the image codecs MuPDF was built with: the pixmap is encoded to PNG,
    inserted, then recovered via `extract_image` after the PDF writer has
    stored it.
    """
    src = pymupdf.open()
    src_page = src.new_page(width=40, height=40)
    src_page.draw_rect(pymupdf.Rect(0, 0, 40, 40), color=(0, 0, 1), fill=(0, 0, 1))
    png = src_page.get_pixmap(dpi=72).tobytes("png")
    src.close()

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=png)
    blob = doc.tobytes()
    doc.close()

    rt = pymupdf.open(stream=blob, filetype="pdf")
    xref = rt[0].get_images()[0][0]
    image = rt.extract_image(xref)
    rt.close()

    assert image["width"] == 40 and image["height"] == 40
    assert image["image"][:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0")


def test_page_manipulation():
    """Pages can be added, copied between documents, deleted and reordered.

    Document surgery goes through the PDF object graph rather than the
    renderer, so it is a separate code path from everything above.
    """
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"page {i}")

    other = pymupdf.open()
    other.insert_pdf(doc)
    assert other.page_count == 3

    other.delete_page(1)
    assert other.page_count == 2
    assert "page 2" in other[1].get_text()

    other.move_page(1, 0)
    assert "page 2" in other[0].get_text()

    doc.close()
    other.close()


def test_non_pdf_formats():
    """Images and comic archives open as documents, not just PDFs.

    MuPDF treats every input format as a document, and the handlers for them are
    compile-time options — so this is the check that the build kept more than the
    PDF one. A CBZ is a zip of images, which makes it constructible here without
    committing a fixture.
    """
    import io
    import zipfile

    doc = pymupdf.open()
    page = doc.new_page(width=60, height=40)
    page.draw_rect(pymupdf.Rect(0, 0, 60, 40), color=None, fill=(0, 0.4, 1))
    png = page.get_pixmap(dpi=72).tobytes("png")
    doc.close()

    image = pymupdf.open(stream=png, filetype="png")
    assert image.page_count == 1
    assert image[0].rect.width == 60
    assert image[0].get_pixmap(dpi=72).width == 60
    image.close()

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("001.png", png)
        zf.writestr("002.png", png)
    comic = pymupdf.open(stream=archive.getvalue(), filetype="cbz")
    assert comic.page_count == 2
    comic.close()

    # The remaining handlers are reported rather than exercised: epub and xps need
    # a fixture big enough to be worth committing, and this is what the build says.
    config = pymupdf.TOOLS.fitz_config
    assert all(config[name] for name in ("pdf", "img", "cbz", "epub", "xps", "svg"))


def test_encryption_roundtrip():
    """A password-protected PDF can be written and opened again.

    The standard security handler is MuPDF's own code rather than libcrypto, which
    this build leaves out — so encryption survives while signing does not, and that
    distinction is worth pinning down.
    """
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "classified")
    blob = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    doc.close()

    locked = pymupdf.open(stream=blob, filetype="pdf")
    assert locked.needs_pass
    assert locked.authenticate("user")
    assert "classified" in locked[0].get_text()
    locked.close()


def test_write_and_reopen_from_disk(tmp_path):
    """A document saves to a real file and reopens from that path.

    Apps write PDFs into Flet's app-storage directories, so the path-based
    save/open pair matters as much as the in-memory one — and it is the only
    test here that touches the filesystem.
    """
    target = tmp_path / "written.pdf"

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "from disk")
    doc.save(str(target))
    doc.close()

    assert target.stat().st_size > 0

    rt = pymupdf.open(str(target))
    assert rt.page_count == 1
    assert "from disk" in rt[0].get_text()
    rt.close()
