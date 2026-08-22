"""Zones and points, and the two ways of asking a spatial question about them."""

import os
import platform
import time

import numpy as np
import shapely

EXTENT = 100.0
COVERAGE = 0.4
SEED = 20260817
LEVELS = [(30, 500), (60, 1000), (120, 2000), (240, 4000)]
DRAW_TOLERANCE = 0.5
DRAW_POINTS = 1200

# Two lobes that cross at (5, 5): valid enough to construct, invalid to GEOS.
BOWTIE = shapely.Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])


def version_line(platform_name):
    """Report what the device is really running, read off it rather than assumed.

    The last field is `shapely.lib.__file__`, which is where you see that Flet has
    relocated the extension — into `jniLibs` on Android, into a `.fwork` inside the
    bundle on iOS — and which on Android is also the file that resolves GEOS out of
    a separate `libgeos_c.so` instead of carrying it inside.
    """
    lib = os.path.basename(getattr(shapely.lib, "__file__", "") or "none")
    return (
        f"shapely {shapely.__version__} · GEOS {shapely.geos_capi_version_string} · "
        f"numpy {np.__version__} · Python {platform.python_version()} · "
        f"{platform_name} · lib.__file__ {lib}"
    )


def workload_label(n_zones, n_points):
    """Name a workload size, for the caption above the rows."""
    return f"{n_zones} zones × {n_points} points"


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


def report(result):
    """Turn one measurement into the six lines the app prints, in screen order.

    Each line sets an indexed answer against the same answer computed without an
    index, which is what makes a wrong predicate or a lossy round-trip read as a
    disagreement rather than as a plausible number standing on its own.
    """
    verdict = (
        "AGREE"
        if result["tree_pairs"] == result["matrix_pairs"] and result["tallies_equal"]
        else "DISAGREE"
    )
    # Subtract the rounded figures, not the raw ones, so the three numbers on the
    # area line agree with each other as printed.
    separate = round(result["naive_area"], 1)
    merged = round(result["joined_area"], 1)
    return [
        f"index: {result['tree_pairs']} point-in-zone pairs, "
        f"{result['tree_inside']} points inside at least one zone, "
        f"{result['t_tree'] * 1e3:.1f} ms\n"
        f"all pairs: {result['matrix_pairs']} / {result['matrix_inside']}, "
        f"{result['t_matrix'] * 1e3:.1f} ms  →  {verdict}",
        f"{result['distances_agree']}/{result['points']} nearest-zone distances match "
        f"the full {result['points']}×{result['zones']} distance matrix — "
        f"{result['t_nearest'] * 1e3:.1f} ms vs {result['t_brute'] * 1e3:.1f} ms",
        f"{result['zones']} zones cover {separate} separately but {merged} "
        f"merged into {result['parts']} parts — "
        f"{separate - merged:.1f} of it counted twice",
        f"{result['wkb_bytes']} bytes of WKB, {result['wkb_equal']}/{result['zones']} "
        f"exactly equal after from_wkb, {result['t_wkb'] * 1e3:.1f} ms",
        f"contains(footprint, points): {result['t_cold'] * 1e3:.1f} ms plain, "
        f"{result['t_warm'] * 1e3:.1f} ms after prepare() — "
        f"same answers: {result['prepared_same']}",
        f"a self-intersecting zone reports area {result['bad_area']:.1f} and "
        f"{result['bad_reason']!r}; make_valid gives {result['good_parts']} parts "
        f"totalling {result['good_area']:.1f}",
    ]


def projected(result, width, height):
    """Fit the footprint and a thinned point sample into a width × height canvas box.

    Screen y grows downwards while world y grows up, so every y is flipped here.
    The points are strided and the outline arrives already thinned by
    `shapely.simplify`, because a phone-sized canvas cannot usefully show thousands
    of vertices or dots; the numbers on screen come from the full geometry.

    Returns the outline as one list of rings per part, and the sample split into
    the points inside a zone and the points outside every zone.
    """
    scale = min(width, height) / EXTENT
    offset = (width - EXTENT * scale) / 2

    def to_screen(coords):
        """Scale world coordinates into the box and flip y, as (x, y) tuples."""
        xy = np.asarray(coords, dtype=float)
        return [(float(x * scale + offset), float(height - y * scale)) for x, y in xy]

    parts = [
        [to_screen(ring.coords) for ring in (part.exterior, *part.interiors)]
        for part in shapely.get_parts(result["outline"])
    ]
    stride = max(1, -(-result["points"] // DRAW_POINTS))
    screen = to_screen(result["coords"][::stride])
    inside = result["inside"][::stride]
    return (
        parts,
        [point for point, hit in zip(screen, inside) if hit],
        [point for point, hit in zip(screen, inside) if not hit],
    )
