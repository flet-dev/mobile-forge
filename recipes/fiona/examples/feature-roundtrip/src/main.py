"""Vector layers written into app storage, read back, and compared to their source records."""

import importlib
import os
import shutil
import time

import flet as ft

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
START_COUNT = 200


def records(count, geometry):
    """`count` features of one geometry type, deterministic so a read-back can be differenced.

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


def vertices(shape):
    """Every coordinate pair of a geometry, flattened for element-wise comparison.

    Nesting depth is discovered rather than assumed. A driver is free to hand back a
    `MultiPolygon` where a `Polygon` was written, and that has to arrive below as a
    differing vertex count — not as a `TypeError` from unpacking one level too few, which
    would replace the mismatch report with a message about the comparison instead.
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


def differences(want, got):
    """How far the features read back drift from the records they were written from.

    The reference is `want`, the in-memory records — nothing fiona derived — so the numbers
    are residuals rather than fiona agreeing with itself.
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
        va, vb = vertices(a["geometry"]), vertices(b["geometry"])
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


def roundtrip(driver, extension, geometry, count):
    """Write one layer, reopen it, and difference it against the records it came from.

    Each layer gets its own directory because a Shapefile is four or five files that
    belong together, and the directory is cleared first so the file list reported back is
    this run's and not a leftover.
    """
    folder = os.path.join(ROOT, f"{driver.replace(' ', '')}-{geometry}")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    path = os.path.join(folder, "layer" + extension)
    want = records(count, geometry)
    schema = {"geometry": geometry, "properties": dict(PROPERTIES)}

    started = time.monotonic()
    # driver= is always explicit: guessing it from the extension asks every driver in
    # fiona.supported_drivers for its metadata, which fails on its own if the lookup table
    # this write uses is empty.
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
        "diff": differences(want, got),
    }


def line(text):
    """One monospaced result line; anything past ~55 characters wraps on a phone."""
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def failure(err):
    """Render an exception instead of letting it end the Flet session.

    The class matters as much as the message: the write path raises
    `fiona._err.FionaNullPointerError`, which is not a `fiona.errors.FionaError` and so
    survives any narrower `except`.
    """
    return line(f"  FAILED  {type(err).__name__}: {err}")


def main(page: ft.Page):
    """Print what this build of fiona can do, then measure a write-read cycle against its input."""

    def build_section():
        """Versions and driver totals — which GDAL this is, and how small its registry is."""
        try:
            return [
                line(f"fiona {fiona.__version__} - GDAL {fiona.__gdal_version__}"),
                line(
                    f"platform {page.platform.value} - driver_count {fiona.driver_count()}"
                ),
            ]
        except Exception as err:
            return [failure(err)]

    def registry_section():
        """The driver table `fiona.Env()` registers into, which is not the one `fiona.open` reads.

        On Android both live in one shared libgdal.so. On iOS they are separate copies
        inside separate extensions, so this list can name drivers the round trip below
        cannot use — which is why it is printed directly above it.
        """
        try:
            with fiona.Env() as env:
                registered = sorted(env.drivers())
            supported = sorted(fiona.supported_drivers.items())
            return [
                line(f"Env().drivers() [{len(registered)}]: {', '.join(registered)}"),
                *[line(f"  {name}  mode {modes}") for name, modes in supported],
            ]
        except Exception as err:
            return [failure(err)]

    def roundtrip_section(count):
        """Write and read each driver/geometry pair, and report the residuals per layer."""
        rows = []
        for driver, extension, geometry in LAYERS:
            rows.append(line(f"{driver} / {geometry}"))
            try:
                r = roundtrip(driver, extension, geometry, count)
                d = r["diff"]
                ok = (
                    d["count"] == r["wanted"]
                    and d["geometry"] == 0
                    and d["coord"] < 1e-9
                    and d["float"] < 1e-9
                    and d["int"] == 0
                    and d["str"] == 0
                )
                rows += [
                    line(
                        f"  read back {d['count']} of {r['wanted']} in {r['ms']:.0f} ms"
                    ),
                    line(f"  schema    {r['schema']['properties']}"),
                    line(f"  files     {', '.join(r['files'])} - {r['bytes']} bytes"),
                    line(
                        f"  worst dx {d['coord']:.3g}  dv {d['float']:.3g}  "
                        f"type {d['geometry']}  int {d['int']}  str {d['str']}"
                    ),
                    line("  ROUND TRIP OK" if ok else "  MISMATCH"),
                ]
            except Exception as err:
                rows.append(failure(err))
        return rows

    def crs_section():
        """What the absent proj.db costs, run rather than described.

        A proj-string is parsed by PROJ itself and works; an EPSG code has to be looked up
        in a database these wheels do not ship.
        """
        rows = []
        for label, call in (
            (
                f"CRS.from_string({PROJ_STRING!r})",
                lambda: fiona.crs.CRS.from_string(PROJ_STRING),
            ),
            ("CRS.from_epsg(4326)", lambda: fiona.crs.CRS.from_epsg(4326)),
        ):
            rows.append(line(label))
            try:
                rows.append(line(f"  OK  {call().to_string()[:60]}"))
            except Exception as err:
                rows.append(failure(err))
        return rows

    def transform_section():
        """Import the one module `import fiona` leaves out.

        Reaching for `fiona.transform` is a decision, not a side effect: it is the only
        extension a plain `import fiona` never loads, and on iOS it maps another
        statically linked copy of GDAL — tens of megabytes for this line alone.
        """
        try:
            module = importlib.import_module("fiona.transform")
            native = getattr(fiona, "_transform", None)
            path = getattr(native, "__file__", None)
            size = os.path.getsize(path) if path and os.path.exists(path) else 0
            return [line(f"  OK  {module.__name__} - _transform {size} bytes")]
        except Exception as err:
            return [failure(err)]

    def render(count):
        """Refill the results column; every section catches its own exceptions."""
        results.controls = [
            heading("Build"),
            *build_section(),
            heading("Registry (fiona.Env)"),
            *registry_section(),
            heading(f"Round trip (fiona.open), {count} features per layer"),
            *roundtrip_section(count),
            heading("CRS"),
            *crs_section(),
            heading("fiona.transform"),
            *transform_section(),
        ]

    def rerun():
        """Run the round trip off the thread pool, since 2000 features is not instant.

        Also the first run, called once below: `import fiona` has already mapped every
        extension by then, and on iOS `transform_section` maps another one, so doing the
        opening pass on the UI thread would hold the first paint behind it.

        The guard reads `disabled` back rather than trusting it to have taken effect.
        Disabling the slider only queues the new state for the client, and
        `page.run_thread` submits to a shared pool, so a release arriving in that window
        would put a second worker on the same four layer directories — which each clear
        themselves before writing. Overlapping runs then report `FileExistsError`,
        `FileNotFoundError` and `DriverError: Failed to create GeoJSON datasource`, putting
        fiona's name on a fault that belongs to this app.
        """
        if features.disabled:
            return
        features.disabled = True

        def worker():
            """Recompute and repaint; run_thread swallows exceptions and does not auto-update."""
            try:
                render(int(features.value))
            except Exception as err:
                results.controls = [failure(err)]
            finally:
                features.disabled = False
                page.update()

        results.controls = [line("working...")]
        page.update()
        page.run_thread(worker)

    if IMPORT_ERROR is not None:
        page.appbar = ft.AppBar(title=ft.Text("fiona round trip"), center_title=True)
        page.add(
            ft.SafeArea(
                expand=True,
                content=ft.Column(
                    [
                        heading("fiona is not installed here"),
                        line(IMPORT_ERROR),
                        line("It is declared under [tool.flet.android] and"),
                        line("[tool.flet.ios], so only an apk/ipa build carries it."),
                    ]
                ),
            )
        )
        return

    os.makedirs(ROOT, exist_ok=True)
    page.appbar = ft.AppBar(title=ft.Text("fiona round trip"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                [
                    features := ft.Slider(
                        min=10,
                        max=2000,
                        divisions=199,
                        value=START_COUNT,
                        label="{value} features",
                        on_change_end=rerun,
                    ),
                    results := ft.Column(
                        spacing=2, expand=True, scroll=ft.ScrollMode.AUTO
                    ),
                ],
                expand=True,
            ),
        )
    )
    rerun()


ft.run(main)
