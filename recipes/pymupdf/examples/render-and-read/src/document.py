import threading
import time

import pymupdf

PAGE_W, PAGE_H = 400.0, 520.0
# Real pixels asked of MuPDF per point of page. Phones draw at 2-3x and Flet
# reports no device ratio, so this is a fixed compromise: crisp on a phone at
# 800x1040 px, and only ~2.4 MB of samples per render.
RENDER_SCALE = 2.0
INK = (0.11, 0.12, 0.16)
MUTED = (0.42, 0.45, 0.52)
ACCENT = (0.15, 0.39, 0.92)
RULE = (0.88, 0.89, 0.92)

# The base-14 PDF fonts are Latin-1, so the document text stays ASCII: an em dash
# passed to insert_text comes out of the rasteriser as a "?" glyph.
FACES = (
    ("helv", "Helvetica"),
    ("tiro", "Times Roman"),
    ("cour", "Courier"),
    ("hebo", "Helvetica Bold"),
)
SAMPLE = "Sphinx of black quartz, judge my vow 0123456789"
BARS = ((34, "Jan"), (58, "Feb"), (47, "Mar"), (72, "Apr"), (65, "May"), (88, "Jun"))
TITLES = ("Typography", "Vector graphics", "Text")


VERSIONS = f"pymupdf {pymupdf.__version__} · MuPDF {pymupdf.mupdf_version}"

# PyMuPDF does not support multithreaded use, and calls reinit_singlethreaded() at
# import. page.run_thread hands work to a thread *pool*, so two renders started
# close together would otherwise overlap inside MuPDF. Serialise them here: the
# renders are milliseconds, so queueing behind the lock costs nothing.
_LOCK = threading.Lock()


def banner(page, number, title):
    """Draw the coloured title bar shared by every page."""
    page.draw_rect(pymupdf.Rect(0, 0, PAGE_W, 48), color=None, fill=ACCENT)
    page.insert_text((26, 31), title, fontname="hebo", fontsize=15, color=(1, 1, 1))
    page.insert_text(
        (PAGE_W - 48, 31), f"{number} / 3", fontname="helv", fontsize=9, color=(1, 1, 1)
    )


def typography_page(doc):
    """A page per base-14 face, which is what proves the fonts are in the wheel.

    Nothing here loads a font file. MuPDF compiles the standard faces into the
    library at build time, so every sample below is drawn from glyphs that
    ship inside `libmupdf` rather than from anything on the device.
    """
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    banner(page, 1, TITLES[0])
    y = 96
    for fontname, label in FACES:
        page.insert_text((26, y), label, fontname=fontname, fontsize=14, color=INK)
        page.insert_text(
            (26, y + 18), SAMPLE, fontname=fontname, fontsize=8.5, color=MUTED
        )
        page.draw_line(
            pymupdf.Point(26, y + 32),
            pymupdf.Point(PAGE_W - 26, y + 32),
            color=RULE,
            width=0.6,
        )
        y += 58
    page.insert_textbox(
        pymupdf.Rect(26, y + 10, PAGE_W - 26, PAGE_H - 20),
        "These are four of the base-14 PDF faces. A phone carries no PostScript "
        "fonts and no fontconfig, so every glyph above came out of the library "
        "itself. The page stores outlines rather than pixels, so the rasteriser "
        "fills them at whatever size it is asked for.",
        fontname="helv",
        fontsize=8.5,
        color=MUTED,
        lineheight=1.45,
    )


def vector_page(doc):
    """A bar chart and some primitives, drawn with page operators rather than pixels.

    Everything here is stored as coordinates rather than pixels, so it is the
    rasteriser that decides how many of them each shape becomes.
    """
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    banner(page, 2, TITLES[1])
    page.insert_text(
        (26, 76),
        "Bars, curves and strokes are page operators.",
        fontname="helv",
        fontsize=8.5,
        color=MUTED,
    )
    base = 330.0
    for index, (value, label) in enumerate(BARS):
        x = 34 + index * 56
        page.draw_rect(
            pymupdf.Rect(x, base - value * 2.1, x + 36, base), color=None, fill=ACCENT
        )
        page.insert_text(
            (x + 8, base - value * 2.1 - 6),
            str(value),
            fontname="helv",
            fontsize=7.5,
            color=MUTED,
        )
        page.insert_text(
            (x + 8, base + 15), label, fontname="helv", fontsize=7.5, color=MUTED
        )
    page.draw_line(
        pymupdf.Point(26, base), pymupdf.Point(PAGE_W - 26, base), color=INK, width=0.9
    )

    # A Shape batches drawing commands into a single page operator run.
    shape = page.new_shape()
    shape.draw_bezier(
        pymupdf.Point(34, 400),
        pymupdf.Point(140, 372),
        pymupdf.Point(250, 428),
        pymupdf.Point(PAGE_W - 34, 390),
    )
    shape.finish(color=ACCENT, width=1.6, closePath=False)
    shape.commit()
    page.draw_circle(pymupdf.Point(62, 470), 16, color=INK, width=1)
    page.draw_rect(pymupdf.Rect(108, 454, 140, 486), color=INK, width=1)
    page.draw_line(pymupdf.Point(168, 486), pymupdf.Point(200, 454), color=INK, width=1)


def text_page(doc):
    """A prose page, so that search and extraction have something to find."""
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    banner(page, 3, TITLES[2])
    page.insert_textbox(
        pymupdf.Rect(26, 76, PAGE_W - 26, PAGE_H - 20),
        "The words on this page are text objects, not pixels. The same page that "
        "rasterises into the image above can be read back with get_text, and "
        "search_for returns a rectangle for every hit, which is how the yellow "
        "highlight gets placed.\n\n"
        "Type a word into the search field to see it marked on the page. Try "
        "quartz, or rectangle, or MuPDF.\n\n"
        "Because glyphs carry their own coordinates, a hit is measured in points "
        "on the page, and stays put however many pixels the renderer decides a "
        "point should become.",
        fontname="helv",
        fontsize=10,
        color=INK,
        lineheight=1.5,
    )


def build_document():
    """Assemble the three-page document the app renders.

    The example generates its own PDF rather than shipping one so that it stays
    a single directory with no bundled asset, and so that composing a document
    is itself part of what gets demonstrated.
    """
    doc = pymupdf.open()
    typography_page(doc)
    vector_page(doc)
    text_page(doc)
    return doc


DOC = build_document()


def render(index, term):
    """Rasterise one page, highlighting `term`, and return PNG bytes.

    Hits are marked with real highlight annotations and deleted again once the
    pixmap exists, which keeps the document itself unchanged between renders --
    the alternative, drawing rectangles onto the page, would accumulate. Pixmaps
    render with annotations included by default, so no extra flag is needed.
    """
    with _LOCK:
        page = DOC[index]
        hits = page.search_for(term) if term else []
        annotations = [page.add_highlight_annot(rect) for rect in hits]

        started = time.perf_counter()
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE))
        png = pixmap.tobytes("png")
        elapsed = time.perf_counter() - started

        # Read the dimensions and drop the pixmap before releasing the lock: every
        # attribute on it is a call back into MuPDF, and the samples are megabytes
        # that nothing needs once the PNG exists.
        size = (pixmap.width, pixmap.height)
        del pixmap

        for annotation in annotations:
            page.delete_annot(annotation)

    return png, len(hits), size, elapsed
