"""Vector layers written to app storage, read back, and differenced against source."""

import importlib
import os
import shutil
import time

# fiona ships here only for Android and iOS, so a desktop run has to explain itself.
try:
    import fiona
    import fiona.crs

    IMPORT_ERROR = None
except Exception as err:
    fiona = None
    IMPORT_ERROR = f"{type(err).__name__}: {err}"

ROOT = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "roundtrip")
LAYERS = (
    ("GeoJSON", ".geojson", "Point"),
    ("GeoJSON", ".geojson", "Polygon"),
    ("ESRI Shapefile", ".shp", "Point"),
    ("ESRI Shapefile", ".shp", "Polygon"),
)
# Field names stay within the DBF 10-character limit a Shapefile enforces.
PROPERTIES = {"name": "str", "n": "int", "v": "float"}
PROJ_STRING = "+proj=longlat +datum=WGS84 +no_defs"
MERCATOR = (
    "+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 "
    "+x_0=0 +y_0=0 +units=m +no_defs"
)
START_COUNT = 200


def _failed(err):
    """Turn an exception into a result line instead of letting it end the session.

    The class matters as much as the message: the write path raises
    `fiona._err.FionaNullPointerError`, which is not a `fiona.errors.FionaError` and so
    survives any narrower `except`.
    """
    return f"  FAILED  {type(err).__name__}: {err}"


def records(count, geometry):
    """`count` features of one geometry type, deterministic so a read-back differences.

    Polygon rings are wound clockwise on purpose: an ESRI Shapefile rewrites a
    counter-clockwise outer ring into clockwise order, which would show up here as a
    coordinate mismatch that is really a format convention.
    """
    out = []
    for i in range(count):
        x = (i % 360) - 180 + 0.123456789
        y = (i % 170) - 85 + 0.987654321
        if geometry == "Point":
            shape = {"type": "Point", "coordinates": (x, y)}
        else:
            ring = [(x, y), (x, y + 0.01), (x + 0.01, y + 0.01), (x + 0.01, y), (x, y)]
            shape = {"type": "Polygon", "coordinates": [ring]}
        out.append(
            {"geometry": shape, "properties": {"name": f"p{i}", "n": i, "v": i / 3.0}}
        )
    return out


def _vertices(shape):
    """Every coordinate pair of a geometry, flattened for element-wise comparison.

    Nesting depth is discovered rather than assumed. A driver is free to hand back a
    `MultiPolygon` where a `Polygon` was written, and that has to arrive below as a
    differing vertex count — not as a `TypeError` from unpacking one level too few,
    which would replace the mismatch report with a message about the comparison.
    """
    found = []

    def descend(node):
        """Recurse until the two numbers at the bottom of the nesting."""
        if node and isinstance(node[0], (int, float)):
            found.append((node[0], node[1]))
            return
        for child in node:
            descend(child)

    descend(shape["coordinates"])
    return found


def _differences(want, got):
    """How far the features read back drift from the records they were written from.

    The reference is `want`, the in-memory records — nothing fiona derived — so the
    numbers are residuals rather than fiona agreeing with itself.
    """
    result = {
        "count": len(got),
        "geometry": 0,
        "coord": 0.0,
        "float": 0.0,
        "int": 0,
        "str": 0,
    }
    for a, b in zip(want, got):
        if a["geometry"]["type"] != b["geometry"]["type"]:
            result["geometry"] += 1
        va, vb = _vertices(a["geometry"]), _vertices(b["geometry"])
        if len(va) != len(vb):
            result["coord"] = float("inf")
        else:
            for pa, pb in zip(va, vb):
                result["coord"] = max(
                    result["coord"], abs(pa[0] - pb[0]), abs(pa[1] - pb[1])
                )
        pa, pb = a["properties"], b["properties"]
        result["float"] = max(result["float"], abs(pa["v"] - pb["v"]))
        result["int"] += pa["n"] != pb["n"]
        result["str"] += pa["name"] != pb["name"]
    return result


def _roundtrip(driver, extension, geometry, count):
    """Write one layer, reopen it, and difference it against the records it came from.

    Each layer gets its own directory because a Shapefile is four or five files that
    belong together, and the directory is cleared first so the file list reported back
    is this run's and not a leftover.
    """
    folder = os.path.join(ROOT, f"{driver.replace(' ', '')}-{geometry}")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    path = os.path.join(folder, "layer" + extension)
    want = records(count, geometry)
    schema = {"geometry": geometry, "properties": dict(PROPERTIES)}

    started = time.monotonic()
    # driver= is always explicit: guessing it from the extension asks every driver in
    # fiona.supported_drivers for its metadata, which fails on its own if the lookup
    # table this write uses is empty.
    with fiona.open(path, "w", driver=driver, schema=schema) as dst:
        dst.writerecords(want)
    with fiona.open(path) as src:
        got = list(src)
        read_schema = dict(src.schema)
    elapsed = (time.monotonic() - started) * 1000

    files = sorted(os.listdir(folder))
    return {
        "wanted": len(want),
        "schema": read_schema,
        "files": files,
        "bytes": sum(os.path.getsize(os.path.join(folder, f)) for f in files),
        "ms": elapsed,
        "diff": _differences(want, got),
    }


def build_lines(platform):
    """Which GDAL this is, and how large it claims its registry to be."""
    try:
        return [
            f"fiona {fiona.__version__} - GDAL {fiona.__gdal_version__}",
            f"platform {platform} - driver_count {fiona.driver_count()}",
        ]
    except Exception as err:
        return [_failed(err)]


def registry_lines():
    """The driver table `fiona.Env()` registers into, not the one `fiona.open` reads.

    On Android both live in one shared libgdal.so. On iOS they are separate copies in
    separate extensions, so this list can name drivers the round trip cannot use — which
    is why the caller prints it directly above that one.
    """
    try:
        with fiona.Env() as env:
            registered = sorted(env.drivers())
        supported = sorted(fiona.supported_drivers.items())
        return [
            f"Env().drivers() [{len(registered)}]: {', '.join(registered)}",
            *[f"  {name}  mode {modes}" for name, modes in supported],
        ]
    except Exception as err:
        return [_failed(err)]


def roundtrip_lines(count):
    """Write and read every driver/geometry pair, and report the residuals per layer."""
    lines = []
    for driver, extension, geometry in LAYERS:
        lines.append(f"{driver} / {geometry}")
        try:
            r = _roundtrip(driver, extension, geometry, count)
            d = r["diff"]
            ok = (
                d["count"] == r["wanted"]
                and d["geometry"] == 0
                and d["coord"] < 1e-9
                and d["float"] < 1e-9
                and d["int"] == 0
                and d["str"] == 0
            )
            lines += [
                f"  read back {d['count']} of {r['wanted']} in {r['ms']:.0f} ms",
                f"  schema    {r['schema']['properties']}",
                f"  files     {', '.join(r['files'])} - {r['bytes']} bytes",
                f"  worst dx {d['coord']:.3g}  dv {d['float']:.3g}  "
                f"type {d['geometry']}  int {d['int']}  str {d['str']}",
                "  ROUND TRIP OK" if ok else "  MISMATCH",
            ]
        except Exception as err:
            lines.append(_failed(err))
    return lines


def crs_lines():
    """What the absent proj.db costs, run rather than described.

    A proj-string is parsed by PROJ itself and works; an EPSG code has to be looked up
    in a database these wheels do not ship.
    """
    lines = []
    for label, call in (
        (
            f"CRS.from_string({PROJ_STRING!r})",
            lambda: fiona.crs.CRS.from_string(PROJ_STRING),
        ),
        ("CRS.from_epsg(4326)", lambda: fiona.crs.CRS.from_epsg(4326)),
    ):
        lines.append(label)
        try:
            lines.append(f"  OK  {call().to_string()[:60]}")
        except Exception as err:
            lines.append(_failed(err))
    return lines


def transform_lines():
    """Import the one module `import fiona` leaves out, and reproject a point with it.

    Reaching for `fiona.transform` is a decision rather than a side effect: it is the
    only extension a plain `import fiona` never loads, and on iOS it maps another
    statically linked copy of GDAL — tens of megabytes for this line alone. Both CRSs
    are proj-strings, which keeps the missing proj.db out of the answer.
    """
    try:
        transform = importlib.import_module("fiona.transform").transform
        lon, lat = 4.3517, 50.8503
        x, y = transform(PROJ_STRING, MERCATOR, [lon], [lat])
        return [f"  OK  {lon}, {lat} -> {x[0]:.0f}, {y[0]:.0f} m"]
    except Exception as err:
        return [_failed(err)]
