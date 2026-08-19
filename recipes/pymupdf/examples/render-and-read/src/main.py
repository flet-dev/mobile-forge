"""Build a PDF in memory, rasterise it with MuPDF, and read its text back."""

import threading
import time

import flet as ft
import pymupdf

# PyMuPDF does not support multithreaded use, and calls reinit_singlethreaded() at
# import. page.run_thread hands work to a thread *pool*, so two renders started
# close together would otherwise overlap inside MuPDF. Serialise them here: the
# renders are milliseconds, so queueing behind the lock costs nothing.
MUPDF = threading.Lock()

PAGE_W, PAGE_H = 400.0, 520.0
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
        "itself. Zoom in: they stay sharp, because the page stores outlines and "
        "the rasteriser fills them at whatever scale you ask for.",
        fontname="helv",
        fontsize=8.5,
        color=MUTED,
        lineheight=1.45,
    )


def vector_page(doc):
    """A bar chart and some primitives, drawn with page operators rather than pixels.

    The point of the page is what the zoom slider does to it: these shapes are
    stored as coordinates, so raising the scale produces genuinely more detail
    instead of a larger blur.
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

    # A Shape batches drawing commands into one page operator run; the curve and
    # the three primitives below it exist to give the zoom something to sharpen.
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
        "Because glyphs carry their own coordinates, extraction is unaffected by "
        "the zoom. The rectangle of a hit is measured in points on the page; only "
        "the renderer decides how many pixels a point becomes.",
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


def render(index, zoom, term):
    """Rasterise one page at `zoom`, highlighting `term`, and return PNG bytes.

    Hits are marked with real highlight annotations and deleted again once the
    pixmap exists, which keeps the document itself unchanged between renders --
    the alternative, drawing rectangles onto the page, would accumulate. Pixmaps
    render with annotations included by default, so no extra flag is needed.
    """
    with MUPDF:
        page = DOC[index]
        hits = page.search_for(term) if term else []
        annotations = [page.add_highlight_annot(rect) for rect in hits]

        started = time.perf_counter()
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        png = pixmap.tobytes("png")
        elapsed = time.perf_counter() - started

        # Read the dimensions and drop the pixmap before releasing the lock: every
        # attribute on it is a call back into MuPDF, and a full page at 4x is tens
        # of megabytes of samples that nothing needs once the PNG exists.
        size = (pixmap.width, pixmap.height)
        del pixmap

        for annotation in annotations:
            page.delete_annot(annotation)

    return png, len(hits), size, elapsed


def main(page: ft.Page):
    """Show one rendered page at a time, with page navigation, zoom and search.

    Rendering is pushed to a background thread: at the top of the zoom range a
    page is several megapixels, and doing that on the UI thread would stall the
    slider mid-drag.
    """
    state = {"index": 0, "zoom": 2.0, "term": ""}

    def redraw():
        """Kick off a render for the current state, with the spinner up."""
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Render on a background thread, then refill the image and the caption."""
        png, hits, (width, height), elapsed = render(
            state["index"], state["zoom"], state["term"]
        )
        sheet.src = png
        position.value = (
            f"{state['index'] + 1} / {DOC.page_count}  ·  {TITLES[state['index']]}"
        )
        found.value = (
            "" if not state["term"] else f"{hits} hit{'' if hits == 1 else 's'}"
        )
        stats.value = (
            f"{width}x{height} px at {state['zoom']:.1f}x in {elapsed * 1e3:.0f} ms"
        )
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def step(delta):
        """Return a handler that moves `delta` pages, clamped to the document."""

        def handler(e):
            state["index"] = max(0, min(DOC.page_count - 1, state["index"] + delta))
            redraw()

        return handler

    def on_zoom(e):
        """Re-render at the slider's scale once the finger lifts.

        on_change_end rather than on_change: a drag emits a value per pixel, and
        each one would queue a full-page rasterisation.
        """
        state["zoom"] = e.control.value
        redraw()

    def on_search(e):
        """Re-render with the new search term highlighted."""
        state["term"] = e.control.value.strip()
        redraw()

    page.appbar = ft.AppBar(title=ft.Text("Render and read"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"pymupdf {pymupdf.__version__} · MuPDF {pymupdf.mupdf_version}",
                        size=11,
                    ),
                    ft.TextField(
                        label="Search this page",
                        dense=True,
                        on_submit=on_search,
                        on_blur=on_search,
                    ),
                    ft.Container(
                        expand=True,
                        alignment=ft.Alignment.CENTER,
                        content=(
                            # src is required, and the first render fills it in;
                            # gapless_playback stops the control blanking between
                            # renders, since each one is a different byte string.
                            sheet := ft.Image(
                                src=b"", fit=ft.BoxFit.CONTAIN, gapless_playback=True
                            )
                        ),
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=step(-1)),
                            ft.Column(
                                spacing=0,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    position := ft.Text(size=12),
                                    found := ft.Text(size=11, color=ft.Colors.PRIMARY),
                                ],
                            ),
                            ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=step(1)),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            ft.Text("zoom", size=11),
                            ft.Slider(
                                min=1.0,
                                max=4.0,
                                value=2.0,
                                divisions=6,
                                label="{value}x",
                                expand=True,
                                on_change_end=on_zoom,
                            ),
                            spinner := ft.ProgressRing(
                                width=14, height=14, visible=False
                            ),
                        ]
                    ),
                    stats := ft.Text(size=11),
                ]
            ),
        )
    )

    redraw()


if __name__ == "__main__":
    ft.run(main)
