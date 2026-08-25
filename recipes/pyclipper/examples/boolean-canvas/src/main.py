import flet as ft

# `canvas` is a submodule, so `import flet` alone does not bind it.
from flet import canvas
from polygons import (
    CLIPPER,
    DELTA_MAX,
    DELTA_MIN,
    GROWN,
    GUIDE,
    OPS,
    RESULT,
    SUBJECT,
    boolean_panel,
    float_panel,
    offset_panel,
    version_line,
)

CANVAS_W = 280
OP_H, FLOAT_H, OFF_H = 180, 120, 180

FILLS = {SUBJECT: ft.Colors.BLUE, CLIPPER: ft.Colors.GREEN}
STROKES = {
    RESULT: (ft.Colors.RED, 2.5),
    GROWN: (ft.Colors.ORANGE, 2.5),
    GUIDE: (ft.Colors.OUTLINE, 1.0),
}


def paint(style):
    """A fresh paint for one layer style: the inputs filled, the answers outlined.

    Fresh rather than shared: a Flet value object carries its own change tracking, so one
    Paint handed to every ring would be a single object sitting in many places at once.
    """
    if style in FILLS:
        colour = ft.Colors.with_opacity(0.18, FILLS[style])
        return ft.Paint(color=colour, style=ft.PaintingStyle.FILL)
    colour, width = STROKES[style]
    return ft.Paint(color=colour, style=ft.PaintingStyle.STROKE, stroke_width=width)


def draw(target, stats, panel, extras=()):
    """Paint one panel's layers onto its canvas and print its check underneath."""
    layers, lines = panel
    shapes = []
    for style, paths in layers:
        for path in paths:
            elements = [canvas.Path.MoveTo(*path[0])]
            elements += [canvas.Path.LineTo(x, y) for x, y in path[1:]]
            elements.append(canvas.Path.Close())
            shapes.append(canvas.Path(elements, paint(style)))
    target.shapes = shapes + list(extras)
    stats.value = "\n".join(lines)


def report(target, stats, error):
    """Clear a panel and put the exception where its picture was.

    An exception escaping a Flet handler is a crash screen, which says nothing about which
    of the three panels failed.
    """
    target.shapes = []
    stats.value = f"{type(error).__name__}: {error}"


def framed(panel):
    """Put a border around one canvas and centre it in the column."""
    border = ft.Border.all(1, ft.Colors.OUTLINE_VARIANT)
    box = ft.Container(content=panel, border=border, border_radius=6)
    return ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[box])


def caption(x, text):
    """A small label drawn on the canvas itself, over the half it describes."""
    return canvas.Text(x, 2, text, ft.TextStyle(size=10, color=ft.Colors.ON_SURFACE))


def main(page: ft.Page):
    """Build the three panels and compute each of them once the page exists.

    This file is the app only: `polygons` owns the geometry and hands back projected rings
    and lines of text. Nothing runs in `page.run_thread` on purpose — every clip here is
    four vertices against four, so a background thread would be pure overhead.
    """

    def header():
        """The version line, guarded: inside `page.add` a raise is a crash screen."""
        try:
            return version_line(page.platform.value)
        except Exception as error:
            return f"{type(error).__name__}: {error}"

    def render_boolean():
        """Redraw the boolean panel for the operation the segmented button selects."""
        try:
            draw(op_canvas, op_stats, boolean_panel(ops.selected[0], CANVAS_W, OP_H))
        except Exception as error:
            report(op_canvas, op_stats, error)
        page.update()

    def render_floats():
        """Redraw the float panel: the same clip straight in, and through the helpers."""
        labels = [
            caption(6, "straight into AddPath"),
            caption(CANVAS_W / 2 + 6, "scale_to_clipper"),
        ]
        try:
            draw(float_canvas, float_stats, float_panel(CANVAS_W, FLOAT_H), labels)
        except Exception as error:
            report(float_canvas, float_stats, error)
        page.update()

    def render_offset():
        """Redraw the offset panel at the delta the slider was released on."""
        try:
            # round, not int: the client sends a float, and truncating one tick's worth
            # of float error would print a delta the slider's own label contradicts.
            delta = round(delta_slider.value)
            draw(off_canvas, off_stats, offset_panel(delta, CANVAS_W, OFF_H))
        except Exception as error:
            report(off_canvas, off_stats, error)
        page.update()

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
                    framed(op_canvas := canvas.Canvas(width=CANVAS_W, height=OP_H)),
                    op_stats := ft.Text(size=12),
                    ft.Divider(),
                    ft.Text(
                        "The same clip in floats, twice", weight=ft.FontWeight.BOLD
                    ),
                    framed(
                        float_canvas := canvas.Canvas(width=CANVAS_W, height=FLOAT_H)
                    ),
                    float_stats := ft.Text(size=12),
                    ft.Divider(),
                    ft.Text("Mitre offset of rectangle A", weight=ft.FontWeight.BOLD),
                    delta_slider := ft.Slider(
                        min=DELTA_MIN,
                        max=DELTA_MAX,
                        divisions=(DELTA_MAX - DELTA_MIN) // 10,
                        value=40,
                        label="{value}",
                        # on_change_end, not on_change: one recompute per gesture is the
                        # habit you want by the time the geometry is big enough to matter.
                        on_change_end=render_offset,
                    ),
                    framed(off_canvas := canvas.Canvas(width=CANVAS_W, height=OFF_H)),
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
