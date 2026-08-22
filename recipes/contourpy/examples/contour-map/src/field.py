"""The contourpy half of the example: trace a field, compare the algorithms, check it.

Everything here returns plain numbers and numpy arrays; nothing in this module knows
about Flet.
"""

import time

# Guarded so a desktop run without the packages says which one is missing rather than
# dying while this module is imported.
try:
    import contourpy
    import numpy as np
    from contourpy import FillType, LineType

    IMPORT_ERROR = None
except Exception as error:
    contourpy = None
    np = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

# Four fixed Gaussian bumps (x, y, sigma, amplitude) over the unit square: a peak, a
# pit, a ridge and a notch, so the map has closed rings, open ends and a hole in it.
BUMPS = (
    (0.30, 0.32, 0.17, 1.00),
    (0.72, 0.26, 0.13, -0.85),
    (0.62, 0.74, 0.20, 0.70),
    (0.18, 0.80, 0.10, -0.55),
)
# Fixed rather than derived from the data, so the picture stays comparable across grids.
LEVELS = (-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8)
BAND_COUNT = len(LEVELS) - 1
ALGORITHMS = ("serial", "threaded", "mpl2014", "mpl2005")

# The ruler: z = x**2 + y**2 over [-1.5, 1.5]**2. Its contour at z = 1 is the unit
# circle, enclosing exactly pi and measuring exactly 2*pi around.
CHECK_HALF_WIDTH = 1.5
CHECK_LEVEL = 1.0


def describe(platform):
    """Header provenance: versions, platform, thread count and the extension's path.

    `max_threads()` is `std::thread::hardware_concurrency()` as *this* device answers
    it, so it is read rather than assumed. The extension's `__file__` goes through
    `getattr` because Flet relocates ABI-tagged extensions out of site-packages: a
    relocated module may report a `.fwork` path, or nothing at all on Android, and an
    `AttributeError` raised while the page is being built is a crash screen rather than
    a line of text. The whole body is guarded for the same reason.
    """
    try:
        origin = getattr(getattr(contourpy, "_contourpy", None), "__file__", None)
        return (
            f"contourpy {contourpy.__version__} · numpy {np.__version__} · "
            f"{platform} · max_threads() = {contourpy.max_threads()}\n"
            f"_contourpy: {origin or 'no __file__'}"
        )
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def bump_field(grid):
    """The map's scalar field on a `grid` x `grid` mesh of the unit square."""
    axis = np.linspace(0.0, 1.0, grid)
    x, y = np.meshgrid(axis, axis)
    z = np.zeros_like(x)
    for cx, cy, sigma, amplitude in BUMPS:
        z = z + amplitude * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma**2))
    return x, y, z


def paraboloid(grid):
    """The check field, whose contour at `CHECK_LEVEL` has a known area."""
    axis = np.linspace(-CHECK_HALF_WIDTH, CHECK_HALF_WIDTH, grid)
    x, y = np.meshgrid(axis, axis)
    return x, y, x**2 + y**2


def rings_at(gen, level):
    """Contour lines at one level as (N, 2) arrays, whatever format the algorithm uses.

    The result is converted rather than requested: `mpl2005` and `mpl2014` support only
    `LineType.SeparateCode`, so asking either of them for `LineType.Separate` up front
    raises `ValueError` instead of returning anything.
    """
    return list(
        contourpy.convert_lines(gen.lines(level), gen.line_type, LineType.Separate)
    )


def bands_at(gen, lower, upper):
    """The filled region between two levels, as a list of rings per enclosed area.

    Converted to `FillType.OuterOffset` for the same reason as above. Each outer
    boundary arrives with its holes wound the opposite way, which is exactly what lets
    one canvas `Path` carrying several subpaths cut the holes out under the non-zero
    fill rule.
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

    The clock covers the tracing and the format conversion together, because that pair
    is what an app actually pays for; building the generator sits outside it. Each
    algorithm keeps its own default output types, which the returned names report.
    """
    x, y, z = field
    gen = contourpy.contour_generator(x=x, y=y, z=z, name=name)
    started = time.perf_counter()
    bands = [bands_at(gen, lo, hi) for lo, hi in zip(LEVELS[:-1], LEVELS[1:])]
    lines = [rings_at(gen, level) for level in LEVELS[1:-1]]
    elapsed = (time.perf_counter() - started) * 1000
    return bands, lines, elapsed, gen.line_type.name, gen.fill_type.name


def trace_all(grid):
    """Trace the bump field at `grid` x `grid` with every algorithm, keyed by name.

    One generator per algorithm, built inside whatever thread called this: contourpy
    generators are not documented as thread-safe, and a `threaded` one shared across
    threads aborts the process rather than raising.
    """
    field = bump_field(grid)
    return {name: trace(name, field) for name in ALGORITHMS}


def counts(bands, lines):
    """Rings, filled vertices and isoline vertices in one traced map.

    The vertex counts are what the canvas costs: every one becomes a `Path` element.
    """
    rings = sum(len(area) for band in bands for area in band)
    band_points = sum(len(ring) for band in bands for area in band for ring in area)
    line_points = sum(len(ring) for level in lines for ring in level)
    return rings, band_points, line_points


def contour_length(rings):
    """Total polyline length of one level's rings."""
    return sum(
        float(np.sum(np.hypot(np.diff(ring[:, 0]), np.diff(ring[:, 1]))))
        for ring in rings
    )


def deviation(one, other):
    """Largest per-level length gap between two algorithms, or None if shapes differ.

    Compared by length rather than vertex against vertex, because the algorithms are
    free to begin a closed ring at a different vertex and they do — an element-wise
    difference reports a disagreement of a tenth of the field where the curves are in
    fact the same. A None here means the two disagreed about how many rings a level has
    or how many vertices one holds, which is a real difference and not a rounding one.
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


def algorithm_report(traced):
    """One tuple per algorithm: name, ms, output type names, and the gap from serial."""
    reference = traced["serial"][1]
    rows = []
    for name in ALGORITHMS:
        _, lines, elapsed, line_type, fill_type = traced[name]
        rows.append((name, elapsed, line_type, fill_type, deviation(reference, lines)))
    return rows


def circle_check(name, grid):
    """Trace the paraboloid at z = 1 and measure the ring against the circle it must be.

    Returns the vertex count, the shoelace area and the summed edge length. The polygon
    is inscribed in the true circle, so both come out slightly small — by an amount that
    falls with the grid spacing, which is the thing the slider is really showing.
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
