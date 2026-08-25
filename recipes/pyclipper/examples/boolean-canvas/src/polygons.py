"""Polygon algebra with pyclipper, and the arithmetic that says whether it is right.

Each panel function returns `(layers, lines)`: layers are `(style, rings)` pairs already
projected into canvas pixels, and lines are the text printed underneath. Styles are plain
strings, so nothing here imports flet — the app owns the paints and the controls.
"""

import time

import pyclipper as pc

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

SUBJECT = "subject"
CLIPPER = "clipper"
RESULT = "result"
GUIDE = "guide"
GROWN = "grown"


def version_line(platform_name):
    """Version, platform, a coordinate width read back off the engine, and `__file__`.

    The width is measured rather than asserted: 2**40 goes in through `AddPath` and comes
    back out of `GetBounds`, which is how a 32-bit Android ABI would betray itself if
    Clipper were built with `use_int32`. It stays far below the +/-(2**62 - 1) limit the
    same line quotes, because crossing that aborts the process.

    `__file__` is read through `getattr` and never dereferenced: Flet relocates the
    extension out of site-packages, so a relocated module may report a bare jniLibs
    filename, a `.fwork` path, or have no `__file__` at all.
    """
    engine = pc.Pyclipper()
    engine.AddPath(
        [(-PROBE, -PROBE), (PROBE, -PROBE), (PROBE, PROBE), (-PROBE, PROBE)],
        pc.PT_SUBJECT,
        True,
    )
    echoed = engine.GetBounds().right
    origin = getattr(getattr(pc, "_pyclipper", None), "__file__", None)
    return (
        f"pyclipper {getattr(pc, '__version__', '?')} · {platform_name} · "
        f"int64 coordinates, |x| <= {HI_RANGE:,} — {PROBE:,} echoed back "
        f"{'exactly' if echoed == PROBE else f'as {echoed:,}'}\n"
        f"_pyclipper: {origin or 'no __file__'}"
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


def layer(style, project, paths):
    """Project every ring of one group and tag it with the style the app paints it in."""
    return style, [[project(x, y) for x, y in path] for path in paths]


def boolean_panel(op_key, width, height):
    """Clip A against B with the selected operation, and check the area against the corners.

    The check is exact rather than tolerant: both rectangles are axis-aligned integers, so
    the area their corners give by hand is the area pyclipper owes, and the residual the
    caller prints reads +0.0 when they agree.
    """
    name, clip_type, expected = OPS[op_key]
    started = time.perf_counter()
    solution = clip(A, B, clip_type)
    elapsed = (time.perf_counter() - started) * 1000
    area = shoelace(solution)
    project = projector([A, B], width, height)
    layers = [
        layer(SUBJECT, project, [A]),
        layer(CLIPPER, project, [B]),
        layer(RESULT, project, solution),
    ]
    lines = [
        f"{name}: {len(solution)} path(s), "
        f"{sum(len(path) for path in solution)} vertices, {elapsed:.3f} ms",
        f"area {area:,.1f}   expected {expected:,}   residual {area - expected:+.1f}",
    ]
    return layers, lines


def float_panel(width, height):
    """Run one float clip twice — straight into AddPath, and through the scaling helpers.

    Neither call raises, which is the lesson: the left-hand result is simply wrong, and only
    the printed residual says so. Both halves use the same projection, the right one shifted
    across, so the two outlines are drawn to one scale and the size difference is real.
    """
    raw = clip(FA, FB, pc.CT_INTERSECTION)
    scaled = pc.scale_from_clipper(
        clip(pc.scale_to_clipper(FA), pc.scale_to_clipper(FB), pc.CT_INTERSECTION)
    )
    half = width / 2
    project = projector([FA, FB], half, height)

    def on_right(x, y):
        """The same projection, moved into the right-hand half of the canvas."""
        px, py = project(x, y)
        return px + half, py

    layers = [
        layer(SUBJECT, project, [FA, FB]),
        layer(RESULT, project, raw),
        layer(SUBJECT, on_right, [FA, FB]),
        layer(RESULT, on_right, scaled),
    ]
    raw_area, scaled_area = shoelace(raw), shoelace(scaled)
    lines = [
        f"straight in: area {raw_area:.2f}   true {FLOAT_TRUTH}   "
        f"residual {raw_area - FLOAT_TRUTH:+.2f} "
        f"({(raw_area / FLOAT_TRUTH - 1) * 100:+.0f}%), no exception",
        f"scaled: area {scaled_area:.2f}   true {FLOAT_TRUTH}   "
        f"residual {scaled_area - FLOAT_TRUTH:+.2f}",
    ]
    return layers, lines


def offset_panel(delta, width, height):
    """Offset A by delta and check the area against (400 + 2d)(300 + 2d).

    An inward offset that erodes the rectangle out of existence returns an empty list rather
    than raising, so that is a state to report, not an error path.
    """
    started = time.perf_counter()
    solution = offset(A, delta)
    elapsed = (time.perf_counter() - started) * 1000
    project = projector([FRAME], width, height)
    layers = [layer(GUIDE, project, [A]), layer(GROWN, project, solution)]
    if not solution:
        message = (
            f"delta {delta:+d}: eroded away — 0 paths, no exception, {elapsed:.3f} ms"
        )
        return layers, [message]
    area = shoelace(solution)
    grown_w, grown_h = 400 + 2 * delta, 300 + 2 * delta
    lines = [
        f"delta {delta:+d}: {len(solution)} path(s), {elapsed:.3f} ms",
        f"area {area:,.1f}   expected {grown_w} x {grown_h} = {grown_w * grown_h:,}   "
        f"residual {area - grown_w * grown_h:+.1f}",
    ]
    return layers, lines
