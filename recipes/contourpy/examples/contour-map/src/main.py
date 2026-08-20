"""A contour map drawn from a 2-D grid, with every algorithm timed and the geometry checked.

The canvas is the point: filled bands from `filled()` and isolines from `lines()`, both traced
by contourpy's C++ core and drawn straight onto an `ft.canvas.Canvas`. Underneath, two numbers
that say whether the picture is right — the four algorithms' largest disagreement with each
other, and the area contourpy measures for a contour that is exactly a unit circle, against pi.
"""

import math
import time

import flet as ft
from flet import canvas

# Guarded so a desktop run without the package says why rather than dying at import.
try:
    import contourpy
    import numpy as np
    from contourpy import FillType, LineType

    IMPORT_ERROR = None
except Exception as error:
    contourpy = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

# Four fixed Gaussian bumps (x, y, sigma, amplitude) over the unit square: a peak, a pit,
# a ridge and a notch, so the map has closed rings, open ends and a hole in it.
BUMPS = (
    (0.30, 0.32, 0.17, 1.00),
    (0.72, 0.26, 0.13, -0.85),
    (0.62, 0.74, 0.20, 0.70),
    (0.18, 0.80, 0.10, -0.55),
)
# Fixed rather than derived from the data, so the picture is comparable across grid sizes.
LEVELS = (-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8)
BAND_COLORS = (
    ft.Colors.INDIGO_700,
    ft.Colors.BLUE_500,
    ft.Colors.LIGHT_BLUE_200,
    ft.Colors.BLUE_GREY_50,
    ft.Colors.AMBER_200,
    ft.Colors.ORANGE_400,
    ft.Colors.DEEP_ORANGE_700,
)

ALGORITHMS = ("serial", "threaded", "mpl2014", "mpl2005")
GRID_MIN, GRID_MAX, GRID_STEP = 33, 129, 16
CANVAS_W = 300

# The ruler: z = x**2 + y**2 over [-1.5, 1.5]**2. Its contour at z = 1 is the unit circle,
# enclosing exactly pi and measuring exactly 2*pi around.
CHECK_HALF_WIDTH = 1.5
CHECK_LEVEL = 1.0


def bump_field(grid):
    """The map's scalar field on a `grid` x `grid` mesh of the unit square."""
    axis = np.linspace(0.0, 1.0, grid)
    x, y = np.meshgrid(axis, axis)
    z = np.zeros_like(x)
    for cx, cy, sigma, amplitude in BUMPS:
        z = z + amplitude * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma**2))
    return x, y, z


def paraboloid(grid):
    """The check field, whose one contour at `CHECK_LEVEL` has a known area and perimeter."""
    axis = np.linspace(-CHECK_HALF_WIDTH, CHECK_HALF_WIDTH, grid)
    x, y = np.meshgrid(axis, axis)
    return x, y, x**2 + y**2


def rings_at(gen, level):
    """Contour lines at one level as a list of (N, 2) arrays, whatever format the algorithm uses.

    The result is converted rather than requested: `mpl2005` and `mpl2014` support only
    `LineType.SeparateCode`, so asking either of them for `LineType.Separate` up front raises
    `ValueError` instead of returning anything.
    """
    return list(
        contourpy.convert_lines(gen.lines(level), gen.line_type, LineType.Separate)
    )


def bands_at(gen, lower, upper):
    """The filled region between two levels, as a list of rings per enclosed area.

    Converted to `FillType.OuterOffset` for the same reason as above. Each outer boundary
    arrives with its holes wound the opposite way, which is exactly what lets one canvas
    `Path` carrying several subpaths cut the holes out under the non-zero fill rule.
    """
    points, offsets = contourpy.convert_filled(
        gen.filled(lower, upper), gen.fill_type, FillType.OuterOffset
    )
    return [
        [array[offs[i] : offs[i + 1]] for i in range(len(offs) - 1)]
        for array, offs in zip(points, offsets)
    ]


def trace(name, field):
    """Every band and isoline of one field for one algorithm, plus what it cost.

    The clock covers the tracing and the format conversion together, because that pair is what
    an app actually pays for; building the generator sits outside it. Each algorithm keeps its
    own default output types, which the returned names report.
    """
    x, y, z = field
    gen = contourpy.contour_generator(x=x, y=y, z=z, name=name)
    started = time.perf_counter()
    bands = [bands_at(gen, lo, hi) for lo, hi in zip(LEVELS[:-1], LEVELS[1:])]
    lines = [rings_at(gen, level) for level in LEVELS[1:-1]]
    elapsed = (time.perf_counter() - started) * 1000
    return bands, lines, elapsed, gen.line_type.name, gen.fill_type.name


def contour_length(rings):
    """Total polyline length of one level's rings."""
    return sum(
        float(np.sum(np.hypot(np.diff(ring[:, 0]), np.diff(ring[:, 1]))))
        for ring in rings
    )


def deviation(one, other):
    """Largest per-level length difference between two algorithms, or None if the shapes differ.

    Compared by length rather than vertex against vertex, because the algorithms are free to
    begin a closed ring at a different vertex and they do — an element-wise difference reports
    a disagreement of a tenth of the field where the curves are in fact the same. A None here
    means the two disagreed about how many rings a level has or how many vertices one holds,
    which is a real difference and not a rounding one.
    """
    if [len(level) for level in one] != [len(level) for level in other]:
        return None
    for level, mirror in zip(one, other):
        if [len(r) for r in level] != [len(r) for r in mirror]:
            return None
    return max(
        abs(contour_length(level) - contour_length(mirror))
        for level, mirror in zip(one, other)
    )


def circle_check(name, grid):
    """Trace the paraboloid at z = 1 and measure the ring against the circle it has to be.

    Returns the vertex count, the shoelace area and the summed edge length. The polygon is
    inscribed in the true circle, so both come out slightly small — by an amount that falls
    with the grid spacing, which is the thing the slider is really showing.
    """
    x, y, z = paraboloid(grid)
    gen = contourpy.contour_generator(x=x, y=y, z=z, name=name)
    rings = rings_at(gen, CHECK_LEVEL)
    if len(rings) != 1:
        raise ValueError(f"expected one ring at z={CHECK_LEVEL}, got {len(rings)}")
    ring = rings[0]
    area = 0.5 * abs(
        float(np.sum(ring[:-1, 0] * ring[1:, 1] - ring[1:, 0] * ring[:-1, 1]))
    )
    perimeter = float(np.sum(np.hypot(np.diff(ring[:, 0]), np.diff(ring[:, 1]))))
    return len(ring), area, perimeter


def project(x, y):
    """Unit-square field coordinates to canvas pixels, with y flipped so the map reads upright."""
    return x * CANVAS_W, (1.0 - y) * CANVAS_W


def path_of(rings, paint, close):
    """One canvas `Path` spanning several rings, each ring becoming its own subpath.

    `ring.tolist()` rather than iterating the array: it converts to Python floats in one call,
    and Flet's msgpack layer refuses a numpy scalar of any width narrower than `float`.
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
    """Canvas shapes for one traced map: filled bands from bottom up, then isolines on top."""
    shapes = []
    for color, band in zip(BAND_COLORS, bands):
        rings = [ring for area in band for ring in area]
        if rings:
            fill = ft.Paint(color=color, style=ft.PaintingStyle.FILL)
            shapes.append(path_of(rings, fill, True))
    stroke = ft.Paint(
        color=ft.Colors.ON_SURFACE, style=ft.PaintingStyle.STROKE, stroke_width=1.0
    )
    open_rings = [ring for level in lines for ring in level]
    if open_rings:
        shapes.append(path_of(open_rings, stroke, False))
    return shapes


def main(page: ft.Page):
    """Build the page, then compute the first map on a worker thread."""

    def header():
        """Versions, platform, the thread count the C++ core reports, and the extension's path.

        `max_threads()` is `std::thread::hardware_concurrency()` as this device answers it, so
        it is read rather than assumed. The extension's `__file__` goes through `getattr`
        because Flet relocates ABI-tagged extensions and a relocated module may report a bare
        library name, a `.fwork` path, or nothing at all — and an `AttributeError` raised while
        the page is being built is a crash screen, not a line of text.
        """
        try:
            origin = getattr(getattr(contourpy, "_contourpy", None), "__file__", None)
            return (
                f"contourpy {contourpy.__version__} · numpy {np.__version__} · "
                f"{page.platform.value} · max_threads() = {contourpy.max_threads()}\n"
                f"_contourpy: {origin or 'no __file__'}"
            )
        except Exception as error:
            return f"{type(error).__name__}: {error}"

    def worker():
        """Trace all four algorithms, draw the selected one, and run the circle check.

        The whole body is guarded: `page.run_thread` never retrieves the worker's future, so an
        escaping exception would leave the screen exactly as it was with nothing logged
        anywhere. It ends with an explicit `page.update()`, because auto-update does not reach
        a background thread.
        """
        try:
            # round, not int: the client sends a float, and truncating one tick's worth of
            # float error would trace a grid the slider's own label contradicts.
            grid = int(round(grid_slider.value))
            chosen = algorithms.selected[0]
            field = bump_field(grid)
            traced = {name: trace(name, field) for name in ALGORITHMS}

            bands, lines = traced[chosen][:2]
            plot.shapes = shapes_for(bands, lines)
            band_rings = sum(len(area) for band in bands for area in band)
            band_points = sum(
                len(ring) for band in bands for area in band for ring in area
            )
            line_points = sum(len(ring) for level in lines for ring in level)
            map_stats.value = (
                f"{grid} x {grid} grid, {len(LEVELS)} levels · "
                f"{len(BAND_COLORS)} bands, {band_rings} rings, {band_points} vertices "
                f"filled · {line_points} vertices of isoline"
            )

            reference = traced["serial"][1]
            rows = []
            for name in ALGORITHMS:
                _, other_lines, elapsed, line_type, fill_type = traced[name]
                gap = deviation(reference, other_lines)
                if gap is None:
                    agrees = "ring counts differ"
                else:
                    agrees = f"same rings, Δlength {gap:.1e}"
                rows.append(
                    f"{name:9s} {elapsed:7.2f} ms  {line_type:13s} {fill_type:12s} {agrees}"
                )
            table.value = "\n".join(rows)

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
        page.update()

    def start():
        """Hand the recompute to a worker thread and say so while it runs.

        Every generator is built inside the worker, so two overlapping taps share no state —
        `page.run_thread` submits to a pool and does let them overlap.
        """
        map_stats.value = "tracing…"
        page.update()
        page.run_thread(worker)

    def framed(content):
        """Put a border around the canvas and centre it in the column."""
        return ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[
                ft.Container(
                    content=content,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=6,
                )
            ],
        )

    page.appbar = ft.AppBar(title=ft.Text("contourpy contour map"), center_title=True)

    if IMPORT_ERROR is not None:
        page.add(
            ft.SafeArea(
                content=ft.Column(
                    controls=[
                        ft.Text("contourpy did not import", weight=ft.FontWeight.BOLD),
                        ft.Text(IMPORT_ERROR, size=12),
                        ft.Text(
                            "contourpy and numpy both have to be installed: from "
                            "pypi.flet.dev in a built app, from PyPI on the desktop.",
                            size=12,
                        ),
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
                    ft.Text(header(), size=11),
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
                    framed(plot := canvas.Canvas(width=CANVAS_W, height=CANVAS_W)),
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
