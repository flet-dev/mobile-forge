"""Polygon boolean ops and offsetting on a canvas, with every area checked against arithmetic.

Three panels: the four boolean operations over a pair of rectangles, the integer-coordinate
trap shown side by side, and a mitre offset driven by a slider. Each one prints the area
pyclipper produced next to one derived from the rectangle corners on paper, and the residual
between them, so the screen says whether the two agree instead of asking you to trust a picture.
"""

import time

import flet as ft
import pyclipper as pc

# `canvas` is a submodule, so `import flet` alone does not bind it.
from flet import canvas

HI_RANGE = 2**62 - 1
# Wider than 32 bits, far below HI_RANGE: a width probe that cannot reach the abort.
PROBE = 2**40

# Integer coordinates on purpose: AddPath truncates a float toward zero without a word.
A = [(0, 0), (400, 0), (400, 300), (0, 300)]
B = [(150, 100), (600, 100), (600, 400), (150, 400)]
AREA_A, AREA_B = 400 * 300, 450 * 300
OVERLAP = 250 * 200  # the (150..400) x (100..300) rectangle the two share

OPS = {
    "AND": ("intersection", pc.CT_INTERSECTION, OVERLAP),
    "OR": ("union", pc.CT_UNION, AREA_A + AREA_B - OVERLAP),
    "SUB": ("difference, A minus B", pc.CT_DIFFERENCE, AREA_A - OVERLAP),
    "XOR": ("symmetric difference", pc.CT_XOR, AREA_A + AREA_B - 2 * OVERLAP),
}

# Fractional corners chosen so truncation moves the answer: the true overlap is
# 2.5 x 2.5, while truncating FB's corner to (1, 0) turns it into 3 x 3.
FA = [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)]
FB = [(1.5, 0.5), (6.0, 0.5), (6.0, 4.0), (1.5, 4.0)]
FLOAT_TRUTH = 2.5 * 2.5

DELTA_MIN, DELTA_MAX = -160, 100
# A fixed drawing frame, so the offset outline grows inside a still picture.
FRAME = [(DELTA_MIN, DELTA_MIN), (400 - DELTA_MIN, 300 - DELTA_MIN)]

CANVAS_W = 280


def stroke(color, width=2.5):
    """A stroke paint in one colour."""
    return ft.Paint(color=color, style=ft.PaintingStyle.STROKE, stroke_width=width)


def fill(color, opacity):
    """A translucent fill paint in one colour."""
    return ft.Paint(
        color=ft.Colors.with_opacity(opacity, color), style=ft.PaintingStyle.FILL
    )


def shoelace(paths):
    """Total signed area of a list of rings, computed here in pure Python as the check.

    Signed rather than absolute: `Execute` returns a flat list in which a hole is just a
    ring wound the other way, so only the signed total is the real area of the result.
    """
    total = 0.0
    for path in paths:
        for i, (x, y) in enumerate(path):
            next_x, next_y = path[(i + 1) % len(path)]
            total += x * next_y - next_x * y
    return total / 2.0


def clip(subject, clipper, clip_type):
    """Run one boolean operation and return the flat list of result rings.

    A fresh `Pyclipper` every call: one object cannot serve two calls at once, and building
    it costs nothing next to the clip itself.
    """
    engine = pc.Pyclipper()
    engine.AddPath(subject, pc.PT_SUBJECT, True)
    engine.AddPath(clipper, pc.PT_CLIP, True)
    return engine.Execute(clip_type)


def offset(path, delta):
    """Mitre-offset one closed ring by delta; a negative delta erodes it, maybe to nothing."""
    engine = pc.PyclipperOffset()
    engine.AddPath(path, pc.JT_MITER, pc.ET_CLOSEDPOLYGON)
    return engine.Execute(delta)


def echo_probe():
    """Push a coordinate wider than 32 bits through the engine and read it back.

    armeabi-v7a is a 32-bit ELF, so "are coordinates really 64-bit on this slice"
    is a question only the device can answer — printing Clipper's limit as a literal
    would answer it from the wrong place. `GetBounds` is the cheapest read-back, and
    no `Execute` is needed.
    """
    engine = pc.Pyclipper()
    engine.AddPath(
        [(-PROBE, -PROBE), (PROBE, -PROBE), (PROBE, PROBE), (-PROBE, PROBE)],
        pc.PT_SUBJECT,
        True,
    )
    return engine.GetBounds().right


def projector(paths, width, height, pad=10):
    """Return a world-to-pixel mapping that centres every given path inside the canvas.

    One scale for both axes, so a square still looks square.
    """
    xs = [x for path in paths for x, _ in path]
    ys = [y for path in paths for _, y in path]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)

    def project(x, y):
        """One world point to canvas pixels."""
        return (
            (x - x0) * scale + (width - span_x * scale) / 2,
            (y - y0) * scale + (height - span_y * scale) / 2,
        )

    return project


def rings(project, paths, paint):
    """One closed canvas Path per ring, mapped through project."""
    shapes = []
    for path in paths:
        elements = [canvas.Path.MoveTo(*project(*path[0]))]
        elements += [canvas.Path.LineTo(*project(x, y)) for x, y in path[1:]]
        elements.append(canvas.Path.Close())
        shapes.append(canvas.Path(elements, paint))
    return shapes


def main(page: ft.Page):
    """Build the three panels and compute each of them once the page exists.

    Every panel body sits in its own try/except that renders the exception class and message
    into that panel: an unhandled exception in a Flet handler produces a crash screen
    instead, which says nothing about which of the three calls failed.
    """

    def header():
        """Version, platform, measured coordinate width and the extension's `__file__`.

        Guarded like a panel because it runs inside `page.add`, where a raise is a crash
        screen and not a message. Flet relocates ABI-tagged extensions, and a relocated
        module may report a bare `jniLibs` filename, a `.fwork` path, or no `__file__` at
        all — so it is read through `getattr`, never dereferenced.
        """
        try:
            echoed = echo_probe()
            origin = getattr(getattr(pc, "_pyclipper", None), "__file__", None)
            return (
                f"pyclipper {getattr(pc, '__version__', '?')} · {page.platform.value} · "
                f"int64 coordinates, |x| <= {HI_RANGE:,} — {PROBE:,} echoed back "
                f"{'exactly' if echoed == PROBE else f'as {echoed:,}'}\n"
                f"_pyclipper: {origin or 'no __file__'}"
            )
        except Exception as error:
            return f"{type(error).__name__}: {error}"

    def render_boolean():
        """Clip A against B with the selected operation, draw it, and print the check."""
        try:
            name, clip_type, expected = OPS[ops.selected[0]]
            started = time.perf_counter()
            solution = clip(A, B, clip_type)
            elapsed = (time.perf_counter() - started) * 1000
            area = shoelace(solution)
            project = projector([A, B], CANVAS_W, op_canvas.height)
            op_canvas.shapes = (
                rings(project, [A], fill(ft.Colors.BLUE, 0.18))
                + rings(project, [B], fill(ft.Colors.GREEN, 0.18))
                + rings(project, solution, stroke(ft.Colors.RED))
            )
            op_stats.value = (
                f"{name}: {len(solution)} path(s), "
                f"{sum(len(path) for path in solution)} vertices, {elapsed:.3f} ms\n"
                f"area {area:,.1f}   expected {expected:,}   residual {area - expected:+.1f}"
            )
        except Exception as error:
            op_canvas.shapes = []
            op_stats.value = f"{type(error).__name__}: {error}"
        page.update()

    def render_floats():
        """Run one float clip twice — straight into AddPath, and through the scaling helpers.

        Neither call raises, which is the lesson: the left-hand result is simply wrong, and
        only the printed residual says so.
        """
        try:
            raw = clip(FA, FB, pc.CT_INTERSECTION)
            scaled = pc.scale_from_clipper(
                clip(
                    pc.scale_to_clipper(FA), pc.scale_to_clipper(FB), pc.CT_INTERSECTION
                )
            )
            half = CANVAS_W / 2
            project = projector([FA, FB], half, float_canvas.height)

            def on_right(x, y):
                """The same projection, moved into the right-hand half of the canvas."""
                px, py = project(x, y)
                return px + half, py

            label = ft.TextStyle(size=10, color=ft.Colors.ON_SURFACE)
            float_canvas.shapes = (
                rings(project, [FA, FB], fill(ft.Colors.BLUE, 0.12))
                + rings(project, raw, stroke(ft.Colors.RED))
                + rings(on_right, [FA, FB], fill(ft.Colors.BLUE, 0.12))
                + rings(on_right, scaled, stroke(ft.Colors.RED))
                + [
                    canvas.Text(6, 2, "straight into AddPath", label),
                    canvas.Text(half + 6, 2, "scale_to_clipper", label),
                ]
            )
            raw_area, scaled_area = shoelace(raw), shoelace(scaled)
            float_stats.value = (
                f"straight in: area {raw_area:.2f}   true {FLOAT_TRUTH}   "
                f"residual {raw_area - FLOAT_TRUTH:+.2f} "
                f"({(raw_area / FLOAT_TRUTH - 1) * 100:+.0f}%), no exception\n"
                f"scaled: area {scaled_area:.2f}   true {FLOAT_TRUTH}   "
                f"residual {scaled_area - FLOAT_TRUTH:+.2f}"
            )
        except Exception as error:
            float_canvas.shapes = []
            float_stats.value = f"{type(error).__name__}: {error}"
        page.update()

    def render_offset():
        """Offset A by the slider's delta and check the area against (400+2d)(300+2d).

        An inward offset that erodes the rectangle out of existence returns an empty list
        rather than raising, so that is a state this panel reports, not an error path.
        """
        try:
            # round, not int: the client sends a float, and truncating one tick's worth
            # of float error would print a delta the slider's own label contradicts.
            delta = round(delta_slider.value)
            started = time.perf_counter()
            solution = offset(A, delta)
            elapsed = (time.perf_counter() - started) * 1000
            project = projector([FRAME], CANVAS_W, off_canvas.height)
            off_canvas.shapes = rings(
                project, [A], stroke(ft.Colors.OUTLINE, 1.0)
            ) + rings(project, solution, stroke(ft.Colors.ORANGE))
            if solution:
                area = shoelace(solution)
                width, height = 400 + 2 * delta, 300 + 2 * delta
                off_stats.value = (
                    f"delta {delta:+d}: {len(solution)} path(s), {elapsed:.3f} ms\n"
                    f"area {area:,.1f}   expected {width} x {height} = "
                    f"{width * height:,}   residual {area - width * height:+.1f}"
                )
            else:
                off_stats.value = (
                    f"delta {delta:+d}: eroded away — 0 paths, "
                    f"no exception, {elapsed:.3f} ms"
                )
        except Exception as error:
            off_canvas.shapes = []
            off_stats.value = f"{type(error).__name__}: {error}"
        page.update()

    def framed(panel):
        """Put a border around one canvas and centre it in the column."""
        return ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[
                ft.Container(
                    content=panel,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=6,
                )
            ],
        )

    page.appbar = ft.AppBar(
        title=ft.Text("pyclipper boolean canvas"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(header(), size=11),
                    ft.Divider(),
                    ft.Text(
                        "Boolean ops on two integer rectangles",
                        weight=ft.FontWeight.BOLD,
                    ),
                    ops := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=key, label=ft.Text(key)) for key in OPS
                        ],
                        selected=["AND"],
                        on_change=render_boolean,
                    ),
                    framed(op_canvas := canvas.Canvas(width=CANVAS_W, height=180)),
                    op_stats := ft.Text(size=12),
                    ft.Divider(),
                    ft.Text(
                        "The same clip in floats, twice", weight=ft.FontWeight.BOLD
                    ),
                    framed(float_canvas := canvas.Canvas(width=CANVAS_W, height=120)),
                    float_stats := ft.Text(size=12),
                    ft.Divider(),
                    ft.Text("Mitre offset of rectangle A", weight=ft.FontWeight.BOLD),
                    delta_slider := ft.Slider(
                        min=DELTA_MIN,
                        max=DELTA_MAX,
                        divisions=(DELTA_MAX - DELTA_MIN) // 10,
                        value=40,
                        label="{value}",
                        on_change_end=render_offset,
                    ),
                    framed(off_canvas := canvas.Canvas(width=CANVAS_W, height=180)),
                    off_stats := ft.Text(size=12),
                ],
            ),
        )
    )

    render_boolean()
    render_floats()
    render_offset()


if __name__ == "__main__":
    ft.run(main)
