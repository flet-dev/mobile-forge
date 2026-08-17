"""Answer two spatial questions with an STRtree, then answer them again without one."""

import os
import platform
import time

import flet as ft
import numpy as np
import shapely

# `ft.canvas` is a submodule: importing flet does not bind it, so ask for it by name.
from flet import canvas

EXTENT = 100.0
COVERAGE = 0.4
SEED = 20260817
LEVELS = [(30, 500), (60, 1000), (120, 2000), (240, 4000)]
DRAW_TOLERANCE = 0.5
DRAW_POINTS = 1200

# Two lobes that cross at (5, 5): valid enough to construct, invalid to GEOS.
BOWTIE = shapely.Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])


def build_world(n_zones, n_points):
    """Circular zones and sample points, from a fixed seed so every device sees one map.

    The radius shrinks as the count grows, keeping the zones' combined area at
    COVERAGE of the world — otherwise the densest level would bury the map under
    one solid blob and every point would land inside something.
    """
    rng = np.random.default_rng(SEED)
    radius = float(np.sqrt(COVERAGE * EXTENT * EXTENT / (np.pi * n_zones)))
    centres = shapely.points(
        rng.uniform(0, EXTENT, n_zones), rng.uniform(0, EXTENT, n_zones)
    )
    zones = shapely.buffer(centres, radius, quad_segs=8)
    points = shapely.points(
        rng.uniform(0, EXTENT, n_points), rng.uniform(0, EXTENT, n_points)
    )
    return zones, points


def measure(n_zones, n_points):
    """Run every question twice — once through the index, once without it — and time both.

    The second answer is the point of the exercise. `tree.query` applies its
    predicate as `predicate(query_geometry, tree_geometry)`, so "which zone is
    this point inside" is spelled `within`, and the plausible-looking `contains`
    returns an empty result with no error at all. The all-pairs boolean matrix
    from `shapely.within(points[:, None], zones[None, :])` uses no index, so a
    reversed predicate shows up as a mismatch instead of as "nothing hit
    anything".

    Returns the numbers, the merged footprint and the inside/outside mask; the
    caller turns the last two into a picture.
    """
    zones, points = build_world(n_zones, n_points)
    tree = shapely.STRtree(zones)

    start = time.perf_counter()
    point_idx, _ = tree.query(points, predicate="within")
    t_tree = time.perf_counter() - start

    start = time.perf_counter()
    matrix = shapely.within(points[:, None], zones[None, :])
    t_matrix = time.perf_counter() - start

    tree_tally = np.bincount(point_idx, minlength=n_points)
    matrix_tally = matrix.sum(axis=1)

    # query_nearest hands back a (2, n) pair array even for one match per input,
    # so the distances have to be read off the second return value, not indexed
    # out of the first.
    start = time.perf_counter()
    _, tree_distance = tree.query_nearest(
        points, all_matches=False, return_distance=True
    )
    t_nearest = time.perf_counter() - start

    start = time.perf_counter()
    brute_distance = shapely.distance(points[:, None], zones[None, :]).min(axis=1)
    t_brute = time.perf_counter() - start

    start = time.perf_counter()
    blob = shapely.to_wkb(zones)
    restored = shapely.from_wkb(blob)
    t_wkb = time.perf_counter() - start

    union = shapely.union_all(zones)
    cold = shapely.from_wkb(shapely.to_wkb(union))
    start = time.perf_counter()
    cold_hits = shapely.contains(cold, points)
    t_cold = time.perf_counter() - start
    warm = shapely.from_wkb(shapely.to_wkb(union))
    shapely.prepare(warm)
    start = time.perf_counter()
    warm_hits = shapely.contains(warm, points)
    t_warm = time.perf_counter() - start

    naive_area = float(shapely.area(zones).sum())
    joined_area = float(shapely.area(union))
    repaired = shapely.make_valid(BOWTIE)

    return {
        "zones": n_zones,
        "points": n_points,
        "tree_pairs": int(point_idx.size),
        "tree_inside": int((tree_tally > 0).sum()),
        "matrix_pairs": int(matrix_tally.sum()),
        "matrix_inside": int((matrix_tally > 0).sum()),
        "tallies_equal": bool(np.array_equal(tree_tally, matrix_tally)),
        "t_tree": t_tree,
        "t_matrix": t_matrix,
        "distances_agree": int(
            np.isclose(tree_distance, brute_distance, atol=1e-9).sum()
        ),
        "t_nearest": t_nearest,
        "t_brute": t_brute,
        "wkb_bytes": int(sum(len(b) for b in blob)),
        "wkb_equal": int(shapely.equals_exact(restored, zones).sum()),
        "t_wkb": t_wkb,
        "naive_area": naive_area,
        "joined_area": joined_area,
        "parts": int(shapely.get_num_geometries(union)),
        "t_cold": t_cold,
        "t_warm": t_warm,
        "prepared_same": bool(np.array_equal(cold_hits, warm_hits)),
        "bad_area": float(shapely.area(BOWTIE)),
        "bad_reason": shapely.is_valid_reason(BOWTIE),
        "good_area": float(shapely.area(repaired)),
        "good_parts": int(shapely.get_num_geometries(repaired)),
        "outline": shapely.simplify(union, DRAW_TOLERANCE),
        "coords": shapely.get_coordinates(points),
        "inside": tree_tally > 0,
    }


def workload_label(n_zones, n_points):
    """Name a workload size, for the caption above the rows."""
    return f"{n_zones} zones × {n_points} points"


def ring_elements(ring, scale, offset, height):
    """Turn one linear ring into canvas path elements, flipping y for screen axes."""
    xs, ys = np.asarray(ring.coords).T
    xs = xs * scale + offset
    ys = height - ys * scale
    elements = [canvas.Path.MoveTo(float(xs[0]), float(ys[0]))]
    elements += [canvas.Path.LineTo(float(x), float(y)) for x, y in zip(xs[1:], ys[1:])]
    elements.append(canvas.Path.Close())
    return elements


def main(page: ft.Page):
    """One slider picks the workload; every figure it produces is checked a second way.

    The header line is read off the device rather than assumed: the last field is
    `shapely.lib.__file__`, which is where you see that Flet has relocated the
    extension — into `jniLibs` on Android, into a `.fwork` inside the bundle on
    iOS — and which on Android is also the file that resolves GEOS out of a
    separate `libgeos_c.so` instead of carrying it inside.
    """
    result = None
    size = (0.0, 0.0)

    def redraw():
        """Rebuild the canvas from the last result, at the canvas's current size.

        Both the footprint and the point cloud are thinned for drawing — the
        merged outline through `shapely.simplify`, the points by striding — because
        a phone-sized canvas cannot usefully show 5,000 vertices or 4,000 dots.
        The numbers above it come from the full, unsimplified geometry.
        """
        # One read of `result`, because the worker rebinds it while this may be
        # running: reading it per field could pair one level's points with
        # another's mask, and the mismatched lengths would raise here.
        latest, (width, height) = result, size
        if latest is None or width <= 0 or height <= 0:
            return
        scale = min(width, height) / EXTENT
        offset = (width - EXTENT * scale) / 2

        shapes = []
        for part in shapely.get_parts(latest["outline"]):
            elements = ring_elements(part.exterior, scale, offset, height)
            for hole in part.interiors:
                elements += ring_elements(hole, scale, offset, height)
            shapes.append(
                canvas.Path(
                    elements=elements,
                    paint=ft.Paint(
                        style=ft.PaintingStyle.STROKE,
                        stroke_width=1.2,
                        color=ft.Colors.TEAL_400,
                    ),
                )
            )

        stride = max(1, -(-latest["points"] // DRAW_POINTS))
        coords = latest["coords"][::stride]
        inside = latest["inside"][::stride]
        screen = np.column_stack(
            [coords[:, 0] * scale + offset, height - coords[:, 1] * scale]
        )
        for mask, colour in (
            (inside, ft.Colors.AMBER_600),
            (~inside, ft.Colors.BLUE_GREY_400),
        ):
            shapes.append(
                canvas.Points(
                    points=[(float(x), float(y)) for x, y in screen[mask]],
                    paint=ft.Paint(stroke_width=2.0, color=colour),
                )
            )
        plot.shapes = shapes

    def on_resize(e):
        """Remember the canvas's pixel size and redraw at it."""
        nonlocal size
        size = (e.width, e.height)
        redraw()

    def run(n_zones, n_points):
        """Compute, fill the rows, redraw, and re-enable the slider. Runs off the UI thread.

        `page.run_thread` never retrieves the worker's future, so anything raised
        here would vanish without a trace — hence the blanket `except`, which puts
        the failure in the caption instead. The explicit `page.update()` is needed
        for the same reason: auto-update only fires at handler boundaries, and this
        is not one.
        """
        nonlocal result
        try:
            result = measure(n_zones, n_points)
            # Re-state the level from the result, not from the thumb: a release
            # dropped by the guard leaves the two disagreeing, and the numbers are
            # the half that is true.
            caption.value = workload_label(result["zones"], result["points"])
            verdict = (
                "AGREE"
                if result["tree_pairs"] == result["matrix_pairs"]
                and result["tallies_equal"]
                else "DISAGREE"
            )
            containment.value = (
                f"index: {result['tree_pairs']} point-in-zone pairs, "
                f"{result['tree_inside']} points inside at least one zone, "
                f"{result['t_tree'] * 1e3:.1f} ms\n"
                f"all pairs: {result['matrix_pairs']} / {result['matrix_inside']}, "
                f"{result['t_matrix'] * 1e3:.1f} ms  →  {verdict}"
            )
            nearest.value = (
                f"{result['distances_agree']}/{result['points']} nearest-zone distances match "
                f"the full {result['points']}×{result['zones']} distance matrix — "
                f"{result['t_nearest'] * 1e3:.1f} ms vs {result['t_brute'] * 1e3:.1f} ms"
            )
            # Subtract the rounded figures, not the raw ones, so the three numbers
            # on the line agree with each other as printed.
            separate = round(result["naive_area"], 1)
            merged = round(result["joined_area"], 1)
            overlap.value = (
                f"{result['zones']} zones cover {separate} separately but {merged} "
                f"merged into {result['parts']} parts — "
                f"{separate - merged:.1f} of it counted twice"
            )
            io_row.value = (
                f"{result['wkb_bytes']} bytes of WKB, {result['wkb_equal']}/{result['zones']} "
                f"exactly equal after from_wkb, {result['t_wkb'] * 1e3:.1f} ms"
            )
            prepared.value = (
                f"contains(footprint, points): {result['t_cold'] * 1e3:.1f} ms plain, "
                f"{result['t_warm'] * 1e3:.1f} ms after prepare() — "
                f"same answers: {result['prepared_same']}"
            )
            repair.value = (
                f"a self-intersecting zone reports area {result['bad_area']:.1f} and "
                f"{result['bad_reason']!r}; make_valid gives {result['good_parts']} parts "
                f"totalling {result['good_area']:.1f}"
            )
            redraw()
        except Exception as error:
            # Six rows and a map from the previous level, left under a fresh
            # error message, read as that error's own output.
            result = None
            for row in (containment, nearest, overlap, io_row, prepared, repair):
                row.value = ""
            plot.shapes = []
            caption.value = f"{type(error).__name__}: {error}"
        finally:
            workload.disabled = False
            page.update()

    def start():
        """Dispatch the run for the level the slider was released on.

        Bound to `on_change_end`, which fires once per gesture: `on_change` fires
        continuously while dragging, and the all-pairs half of this workload is
        far too expensive to run per pixel.

        The guard reads `disabled` back rather than trusting it to have taken
        effect. Disabling the slider only queues the new state for the client, and
        `page.run_thread` submits to a shared pool, so a release arriving in that
        window would put a second worker on the same six rows — and the two then
        leave the slider, the caption and the numbers each describing a different
        level, with nothing on screen admitting it.
        """
        if workload.disabled:
            return
        workload.disabled = True
        n_zones, n_points = LEVELS[int(workload.value)]
        page.update()
        page.run_thread(run, n_zones, n_points)

    def preview():
        """Caption the level under the thumb while it is still moving — no computing.

        A preview only: the caption is rewritten from the result once the run lands.
        """
        caption.value = workload_label(*LEVELS[int(workload.value)])

    page.appbar = ft.AppBar(title=ft.Text("shapely zone index"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"shapely {shapely.__version__} · GEOS "
                        f"{shapely.geos_capi_version_string} · numpy {np.__version__} · "
                        f"Python {platform.python_version()} · {page.platform.value} · "
                        f"lib.__file__ "
                        f"{os.path.basename(getattr(shapely.lib, '__file__', '') or 'none')}",
                        size=11,
                        selectable=True,
                    ),
                    caption := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    workload := ft.Slider(
                        value=len(LEVELS) - 1,
                        min=0,
                        max=len(LEVELS) - 1,
                        divisions=len(LEVELS) - 1,
                        on_change=preview,
                        on_change_end=start,
                    ),
                    containment := ft.Text(size=12),
                    nearest := ft.Text(size=12),
                    overlap := ft.Text(size=12),
                    io_row := ft.Text(size=12),
                    prepared := ft.Text(size=12),
                    repair := ft.Text(size=12),
                    ft.Container(
                        height=300,
                        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                        border_radius=8,
                        content=(
                            plot := canvas.Canvas(expand=True, on_resize=on_resize)
                        ),
                    ),
                ],
            ),
        )
    )

    preview()
    start()


if __name__ == "__main__":
    ft.run(main)
