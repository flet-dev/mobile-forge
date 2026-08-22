"""A contour map drawn from a 2-D grid, every algorithm timed and the geometry checked.

The canvas is the point: filled bands and isolines traced by contourpy's C++ core in
`field.py` and drawn straight onto an `ft.canvas.Canvas`. Underneath, two numbers that
say whether the picture is right.
"""

import math

import flet as ft
from field import (
    ALGORITHMS,
    BAND_COUNT,
    IMPORT_ERROR,
    LEVELS,
    algorithm_report,
    circle_check,
    counts,
    describe,
    trace_all,
)
from flet import canvas

BAND_COLORS = (
    ft.Colors.INDIGO_700,
    ft.Colors.BLUE_500,
    ft.Colors.LIGHT_BLUE_200,
    ft.Colors.BLUE_GREY_50,
    ft.Colors.AMBER_200,
    ft.Colors.ORANGE_400,
    ft.Colors.DEEP_ORANGE_700,
)
GRID_MIN, GRID_MAX, GRID_STEP = 33, 129, 16
CANVAS_W = 300


def project(x, y):
    """Field coordinates to canvas pixels, y flipped so the map reads upright."""
    return x * CANVAS_W, (1.0 - y) * CANVAS_W


def path_of(rings, paint, close):
    """One canvas `Path` spanning several rings, each ring becoming its own subpath.

    `ring.tolist()` rather than iterating the array: it converts to Python floats in one
    call, and Flet's msgpack layer refuses a numpy scalar narrower than `float`.
    """
    elements = []
    for ring in rings:
        points = ring.tolist()
        elements.append(canvas.Path.MoveTo(*project(*points[0])))
        elements.extend(canvas.Path.LineTo(*project(x, y)) for x, y in points[1:])
        if close:
            elements.append(canvas.Path.Close())
    return canvas.Path(elements, paint)


def shapes_for(bands, lines):
    """Shapes for one traced map: filled bands from the bottom up, isolines on top."""
    shapes = []
    for color, band in zip(BAND_COLORS, bands):
        rings = [ring for area in band for ring in area]
        if rings:
            fill = ft.Paint(color=color, style=ft.PaintingStyle.FILL)
            shapes.append(path_of(rings, fill, True))
    open_rings = [ring for level in lines for ring in level]
    if open_rings:
        stroke = ft.Paint(
            color=ft.Colors.ON_SURFACE,
            style=ft.PaintingStyle.STROKE,
            stroke_width=1.0,
        )
        shapes.append(path_of(open_rings, stroke, False))
    return shapes


def main(page: ft.Page):
    """Build the page, then compute the first map on a worker thread."""

    def worker():
        """Trace all four algorithms, draw the selected one, run the circle check.

        The whole body is guarded: `page.run_thread` never retrieves the worker's
        future, so an escaping exception would leave the screen exactly as it was with
        nothing logged anywhere. It ends with an explicit `page.update()`, because
        auto-update does not reach a background thread.
        """
        try:
            # round, not int: the client sends a float, and truncating one tick's worth
            # of float error would trace a grid the slider's own label contradicts.
            grid = int(round(grid_slider.value))
            chosen = algorithms.selected[0]
            traced = trace_all(grid)

            bands, lines = traced[chosen][:2]
            plot.shapes = shapes_for(bands, lines)
            rings, band_points, line_points = counts(bands, lines)
            map_stats.value = (
                f"{grid} x {grid} grid, {len(LEVELS)} levels · {BAND_COUNT} bands, "
                f"{rings} rings, {band_points} vertices filled · "
                f"{line_points} vertices of isoline"
            )

            table.value = "\n".join(
                f"{name:9s} {ms:7.2f} ms  {line_type:13s} {fill_type:12s} "
                + (
                    "ring counts differ"
                    if gap is None
                    else f"same rings, Δlength {gap:.1e}"
                )
                for name, ms, line_type, fill_type, gap in algorithm_report(traced)
            )

            vertices, area, perimeter = circle_check(chosen, grid)
            check.value = (
                f"{vertices} vertices · area {area:.8f} vs pi {math.pi:.8f} "
                f"({(area / math.pi - 1) * 100:+.5f}%)\n"
                f"perimeter {perimeter:.8f} vs 2pi {2 * math.pi:.8f} "
                f"({(perimeter / (2 * math.pi) - 1) * 100:+.5f}%)"
            )
        except Exception as error:
            plot.shapes = []
            map_stats.value = f"{type(error).__name__}: {error}"
            table.value = ""
            check.value = ""
        page.update()  # auto-update does not reach background threads

    def start():
        """Hand the recompute to a worker thread and say so while it runs.

        Every generator is built inside the worker, so two overlapping taps share no
        state — `page.run_thread` submits to a pool and does let them overlap.
        """
        map_stats.value = "tracing…"
        page.update()
        page.run_thread(worker)

    page.appbar = ft.AppBar(title=ft.Text("contourpy contour map"), center_title=True)

    if IMPORT_ERROR is not None:
        page.add(
            ft.SafeArea(
                content=ft.Column(
                    controls=[
                        ft.Text("contourpy did not import", weight=ft.FontWeight.BOLD),
                        ft.Text(IMPORT_ERROR, size=12),
                    ]
                )
            )
        )
        return

    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(describe(page.platform.value), size=11),
                    ft.Divider(),
                    ft.Text(
                        "Four Gaussian bumps, banded and outlined",
                        weight=ft.FontWeight.BOLD,
                    ),
                    grid_slider := ft.Slider(
                        min=GRID_MIN,
                        max=GRID_MAX,
                        divisions=(GRID_MAX - GRID_MIN) // GRID_STEP,
                        value=65,
                        label="{value}",
                        on_change_end=start,
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                content=(
                                    plot := canvas.Canvas(
                                        width=CANVAS_W, height=CANVAS_W
                                    )
                                ),
                                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                                border_radius=6,
                            )
                        ],
                    ),
                    map_stats := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text(
                        "The four algorithms, same grid", weight=ft.FontWeight.BOLD
                    ),
                    algorithms := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name, size=11))
                            for name in ALGORITHMS
                        ],
                        selected=["serial"],
                        show_selected_icon=False,
                        on_change=start,
                    ),
                    table := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text(
                        "Check: z = x² + y², contour at z = 1 is the unit circle",
                        weight=ft.FontWeight.BOLD,
                    ),
                    check := ft.Text(size=11),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
