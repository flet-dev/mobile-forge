"""A GeoTIFF written and read back with osgeo.gdal, checked against the values it came from."""

import math
import os
import sys
import time
import warnings
from array import array

import flet as ft
import numpy as np

try:
    from osgeo import gdal, ogr, osr

    GDAL_ERROR = None
except Exception as err:  # pragma: no cover - only off-device
    gdal = ogr = osr = None
    GDAL_ERROR = f"{type(err).__name__}: {err}"

SIZE = 512
BLOCK = 256
ORIGIN = (10.0, 60.0)
PIXEL = 0.001
PROBE = (10.250, 59.800)
# A proj-string, not "EPSG:4326": an authority code needs proj.db and nothing in this
# chain ships one. The EPSG row is run anyway, so the difference shows on screen.
CRS_TEXT = "+proj=longlat +datum=WGS84 +no_defs"
POINTS = [
    ("north", 10.100, 59.900),
    ("middle", 10.250, 59.800),
    ("south", 10.400, 59.700),
]
EXTENSIONS = ("_gdal", "_gdalconst", "_ogr", "_osr", "_gnm", "_gdal_array")
DATA = os.getenv("FLET_APP_STORAGE_DATA", ".")
RASTER = os.path.join(DATA, "surface.tif")
VECTOR = os.path.join(DATA, "points.geojson")
# Deliberately absent, and named without a directory so the error row stays readable.
MISSING = "not-here.tif"


def surface(n):
    """An n x n float32 field built without numpy, so the raster panel owes numpy nothing."""
    out = array("f")
    for row in range(n):
        damping = math.cos(row / 47.0)
        for col in range(n):
            out.append(math.sin(col / 61.0) * damping * 300.0 + col * 0.25 + row * 0.1)
    return out


def unpack(raw):
    """ReadRaster hands back raw bytes in native order; this band is float32."""
    out = array("f")
    out.frombytes(raw)
    return out


def residual(got, want):
    """Count of differing elements and the worst absolute difference between two sequences.

    A length mismatch counts as everything differing: zip() would otherwise truncate a
    short read to the length GDAL did return and report it as a clean zero.
    """
    if len(got) != len(want):
        return max(len(got), len(want)), float("inf")
    bad = sum(1 for a, b in zip(got, want) if a != b)
    return bad, max((abs(a - b) for a, b in zip(got, want)), default=0.0)


def footprint():
    """How many of the six osgeo extensions are mapped, and how many bytes they occupy.

    Read off sys.modules and the files behind it rather than assumed. This is the number
    that separates the two platforms: the same import maps the same four modules on both,
    and they weigh about 2.9 MB on Android against about 77 MB on iOS.
    """
    total = 0
    loaded = 0
    for name in EXTENSIONS:
        module = sys.modules.get(f"osgeo.{name}")
        if module is None:
            continue
        loaded += 1
        path = getattr(module, "__file__", None)
        if path and os.path.exists(path):
            total += os.path.getsize(path)
    return loaded, total


def line(text):
    """One monospaced result row; much past ~55 characters wraps on a phone."""
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def listed(names, limit=14):
    """Driver names, truncated: a phone registers eleven, a desktop over two hundred."""
    extra = f" (+{len(names) - limit} more)" if len(names) > limit else ""
    return ", ".join(names[:limit]) + extra


REFERENCE = surface(SIZE)


def main(page: ft.Page):
    """Write one GeoTIFF, read it back, and print how far each read disagrees with its source.

    Nothing on screen asserts that GDAL is right. Every row is either a difference against
    REFERENCE or the exception the call raised, rendered with its class and message —
    an unhandled exception in a Flet handler ends the session with a crash screen instead.
    """

    if GDAL_ERROR is not None:
        # gdal is declared under [tool.flet.android]/[tool.flet.ios] because it has no
        # desktop wheel, so it is absent anywhere but a device build.
        page.appbar = ft.AppBar(title=ft.Text("GeoTIFF round trip"), center_title=True)
        page.add(
            ft.SafeArea(
                expand=True,
                content=ft.Card(
                    content=ft.Container(
                        padding=16,
                        content=ft.Text(
                            f"osgeo is not importable here — {GDAL_ERROR}.\n\n"
                            "That is expected off-device: the gdal wheel exists only for "
                            "Android and iOS on pypi.flet.dev, and upstream publishes no "
                            "desktop wheel, so this app declares it under "
                            "[tool.flet.android] and [tool.flet.ios] rather than in "
                            "[project] dependencies."
                        ),
                    )
                ),
            )
        )
        return

    def version_row():
        """The GDAL and PROJ version strings, or whichever exception asking for them raised.

        Guarded like every panel below, and for the same reason: on iOS these are the
        first calls into a PROJ that was absorbed into _osr at link time, and this row is
        built while page.add() is still running — an exception here would end the session
        before a single control existed to show it in.
        """
        try:
            text = (
                f"GDAL {gdal.VersionInfo('RELEASE_NAME')} - PROJ "
                f"{osr.GetPROJVersionMajor()}.{osr.GetPROJVersionMinor()}."
                f"{osr.GetPROJVersionMicro()}"
            )
        except Exception as err:
            text = f"{type(err).__name__}: {err}"[:160]
        return line(f"{text} - {page.platform.value}")

    def exception_modes():
        """gdal.Open on a missing file, before and after gdal.UseExceptions().

        Exceptions are off by default in 3.13, so the first call returns None and warns
        that GDAL 4.0 will flip it. The warning is captured rather than described, because
        on device it would otherwise go to stderr and be lost.
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            opened = gdal.Open(MISSING)
        rows = [
            line(f"{'default':<8}gdal.Open(missing) -> {opened!r}"),
            line(f"{'':<8}{gdal.GetLastErrorMsg().strip()[:88]}"),
        ]
        rows += [line(f"{'':<8}{w.category.__name__}: {w.message}") for w in caught]
        gdal.UseExceptions()
        try:
            gdal.Open(MISSING)
            rows.append(line(f"{'after':<8}returned without raising"))
        except Exception as err:
            rows.append(line(f"{'after':<8}{type(err).__name__}: {err}"[:180]))
        return rows

    def registry():
        """The live driver tables of _gdal and _ogr, which on iOS are separate images.

        Asked rather than assumed: a phone registers a small fraction of what a desktop
        does, and the two counts differ because ogr sees only the vector-capable drivers.
        """
        raster = sorted(
            gdal.GetDriver(i).ShortName for i in range(gdal.GetDriverCount())
        )
        vector = sorted(ogr.GetDriver(i).GetName() for i in range(ogr.GetDriverCount()))
        return [
            line(f"gdal {len(raster)}: {listed(raster)}"),
            line(f"ogr  {len(vector)}: {listed(vector)}"),
        ]

    def roundtrip():
        """Write the surface as a tiled GeoTIFF, read it all back, and difference it.

        Every call here resolves to _gdal — driver lookup, create, band, both raster
        transfers, the re-open and the geotransform maths — so this is the panel with no
        cross-extension handoff in it at all. No CRS is attached on purpose; that story
        belongs to the _osr panel, and georeferencing is the affine transform regardless.
        """
        started = time.perf_counter()
        ds = gdal.GetDriverByName("GTiff").Create(
            RASTER,
            SIZE,
            SIZE,
            1,
            gdal.GDT_Float32,
            options=[
                "COMPRESS=DEFLATE",
                "PREDICTOR=3",
                "TILED=YES",
                f"BLOCKXSIZE={BLOCK}",
                f"BLOCKYSIZE={BLOCK}",
            ],
        )
        ds.SetGeoTransform([ORIGIN[0], PIXEL, 0.0, ORIGIN[1], 0.0, -PIXEL])
        ds.GetRasterBand(1).WriteRaster(0, 0, SIZE, SIZE, REFERENCE.tobytes())
        ds = None  # dropping the last reference is what flushes the tiles to disk
        write_ms = (time.perf_counter() - started) * 1000

        ds = gdal.Open(RASTER)
        band = ds.GetRasterBand(1)
        started = time.perf_counter()
        got = unpack(band.ReadRaster(0, 0, SIZE, SIZE))
        read_ms = (time.perf_counter() - started) * 1000
        bad, worst = residual(got, REFERENCE)
        col, row = gdal.ApplyGeoTransform(
            gdal.InvGeoTransform(ds.GetGeoTransform()), *PROBE
        )
        here = unpack(band.ReadRaster(int(col), int(row), 1, 1))[0]
        # Read back rather than repeated: an unsupported codec is a warning, not an error,
        # so a build without DEFLATE writes the file uncompressed and says nothing.
        structure = ds.GetMetadata("IMAGE_STRUCTURE")
        rows = [
            line(
                f"{'driver':<7}{ds.GetDriver().ShortName}, "
                f"{structure.get('COMPRESSION', 'none')}/"
                f"{structure.get('PREDICTOR', '-')}, {band.GetBlockSize()}"
            ),
            line(
                f"{'size':<7}{os.path.getsize(RASTER):,} B on disk, "
                f"{len(REFERENCE) * 4:,} B as float32"
            ),
            line(f"{'write':<7}{write_ms:.0f} ms"),
            line(f"{'read':<7}{read_ms:.0f} ms - {bad:,} of {len(REFERENCE):,} differ"),
            line(f"{'':<7}worst {worst:.3e}"),
            line(
                f"{'pixel':<7}{PROBE[0]}E {PROBE[1]}N -> col {int(col)}, row {int(row)}"
            ),
            line(
                f"{'':<7}{here:.4f}, delta {abs(here - REFERENCE[int(row) * SIZE + int(col)]):.3e}"
            ),
        ]
        ds = band = None
        return rows

    def numpy_rows():
        """band.ReadAsArray() — _gdal_array code running on an object minted by _gdal.

        numpy is an optional extra of the gdal wheel, so a plain "gdal" dependency leaves
        this raising ModuleNotFoundError at the point of use; the app pins numpy for it.
        """
        ds = gdal.Open(RASTER)
        started = time.perf_counter()
        arr = ds.GetRasterBand(1).ReadAsArray()
        elapsed = (time.perf_counter() - started) * 1000
        ds = None
        diff = np.abs(
            arr - np.frombuffer(REFERENCE, dtype="float32").reshape(SIZE, SIZE)
        )
        return [
            line(
                f"numpy {np.__version__} - {arr.dtype} {arr.shape} in {elapsed:.0f} ms"
            ),
            line(
                f"{int(np.count_nonzero(diff))} differ, worst {float(diff.max()):.3e}"
            ),
        ]

    def spatial_rows():
        """A CRS built in _osr and attached to _gdal datasets as a string and as an object.

        The two routes are the interesting pair: ExportToWkt() sends text across the
        module boundary, SetSpatialRef() sends the object itself. On Android both reach
        one shared libgdal; on iOS they cross between two separately linked copies of it.
        """
        srs = osr.SpatialReference()
        srs.SetFromUserInput(CRS_TEXT)
        as_text = gdal.GetDriverByName("MEM").Create("", 2, 2, 1, gdal.GDT_Byte)
        as_text.SetProjection(srs.ExportToWkt())
        as_object = gdal.GetDriverByName("MEM").Create("", 2, 2, 1, gdal.GDT_Byte)
        as_object.SetSpatialRef(srs)
        back = as_text.GetSpatialRef()
        wkt_text = back.ExportToWkt()
        wkt_object = as_object.GetSpatialRef().ExportToWkt()
        same = srs.IsSame(back)
        as_text = as_object = back = None
        rows = [
            line(f"proj4 {srs.ExportToProj4()}"),
            line(
                f"SetProjection {len(wkt_text)} B / SetSpatialRef {len(wkt_object)} B"
            ),
            line(f"identical: {wkt_text == wkt_object}, IsSame: {same}"),
        ]
        epsg = osr.SpatialReference()
        try:
            epsg.ImportFromEPSG(4326)
            rows.append(line(f"EPSG:4326 -> {epsg.GetName()}"))
        except Exception as err:
            rows.append(line(f"EPSG:4326 -> {type(err).__name__}: {err}"[:180]))
        return rows

    def vector_rows():
        """A GeoJSON written and re-read, passing Layer and Feature objects between _gdal and _ogr.

        GetDriverByName, Create, OpenEx and GetLayer are _gdal calls; the Layer, Feature
        and Geometry objects they hand back belong to _ogr, so every coordinate below has
        crossed the boundary twice.
        """
        if os.path.exists(VECTOR):
            os.remove(VECTOR)  # so the byte count below is this run's, not a leftover's
        ds = gdal.GetDriverByName("GeoJSON").Create(VECTOR, 0, 0, 0, gdal.GDT_Unknown)
        layer = ds.CreateLayer("points", geom_type=ogr.wkbPoint)
        layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
        for name, lon, lat in POINTS:
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetField("name", name)
            point = ogr.Geometry(ogr.wkbPoint)
            point.AddPoint_2D(lon, lat)
            feature.SetGeometry(point)
            layer.CreateFeature(feature)
        ds = layer = None

        ds = gdal.OpenEx(VECTOR, gdal.OF_VECTOR)
        layer = ds.GetLayer(0)
        worst = 0.0
        names = []
        for feature, (_, lon, lat) in zip(layer, POINTS):
            geometry = feature.GetGeometryRef()
            worst = max(worst, abs(geometry.GetX() - lon), abs(geometry.GetY() - lat))
            names.append(feature.GetField("name"))
        count = layer.GetFeatureCount()
        ds = layer = None
        return [
            line(f"{os.path.getsize(VECTOR):,} B, {count} features re-read"),
            line(f"names match: {names == [name for name, _, _ in POINTS]}"),
            line(f"worst coord delta {worst:.3e}"),
        ]

    def fill(column, work):
        """Run one panel and put either its rows or its exception into the column."""
        try:
            column.controls = work()
        except Exception as err:
            column.controls = [line(f"{type(err).__name__}: {err}"[:220])]

    def sample():
        """Read one centred window with its own dataset handle, differenced against REFERENCE.

        The gdal.Open is inside the worker deliberately: a dataset handle is not safe to
        share between threads, and page.run_thread hands this body to a pool.
        """
        side = int(window.value)
        offset = (SIZE - side) // 2
        try:
            ds = gdal.Open(RASTER)
            started = time.perf_counter()
            raw = ds.GetRasterBand(1).ReadRaster(offset, offset, side, side)
            elapsed = (time.perf_counter() - started) * 1000
            ds = None
            want = array("f")
            for step in range(side):
                start = (offset + step) * SIZE + offset
                want.extend(REFERENCE[start : start + side])
            bad, worst = residual(unpack(raw), want)
            readout.value = (
                f"{side}x{side} in {elapsed:.2f} ms, {len(raw):,} B - "
                f"{bad} differ, worst {worst:.3e}"
            )
        except Exception as err:
            readout.value = f"{type(err).__name__}: {err}"[:180]
        page.update()

    def resize():
        """Re-read at the slider's new window size, off the UI thread."""
        page.run_thread(sample)

    def build():
        """Fill every panel off the UI thread, in the one order that works.

        exception_modes() has to run first: it owns the only gdal.Open made before
        gdal.UseExceptions(), and the FutureWarning it captures fires once per process.
        Everything after it therefore raises on failure instead of returning None.
        """
        fill(modes, exception_modes)
        fill(drivers, registry)
        fill(raster, roundtrip)
        fill(arrays, numpy_rows)
        fill(spatial, spatial_rows)
        fill(vectors, vector_rows)
        count, total = footprint()
        loaded.value = f"after UseExceptions {count}/6, {total:,} B"
        window.disabled = False
        sample()  # carries the page.update() this worker owes

    imported, bytes_in = footprint()
    page.appbar = ft.AppBar(title=ft.Text("GeoTIFF round trip"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=6,
                controls=[
                    version_row(),
                    line(f"import mapped {imported}/6, {bytes_in:,} B"),
                    loaded := line("after UseExceptions ..."),
                    ft.Divider(),
                    heading(f"{SIZE}x{SIZE} float32 GeoTIFF, all of it inside _gdal"),
                    raster := ft.Column(spacing=6, controls=[line("writing...")]),
                    ft.Divider(),
                    heading("Windowed read"),
                    window := ft.Slider(
                        min=64,
                        max=512,
                        divisions=7,
                        value=256,
                        label="{value} px",
                        disabled=True,
                        on_change_end=resize,
                    ),
                    readout := line("waiting for the file..."),
                    ft.Divider(),
                    heading("Into _gdal_array"),
                    arrays := ft.Column(spacing=6),
                    heading("Into _osr"),
                    spatial := ft.Column(spacing=6),
                    heading("Into _ogr"),
                    vectors := ft.Column(spacing=6),
                    ft.Divider(),
                    heading("Driver registries"),
                    drivers := ft.Column(spacing=6),
                    heading("Exception mode"),
                    modes := ft.Column(spacing=6),
                ],
            ),
        )
    )

    page.run_thread(build)


if __name__ == "__main__":
    ft.run(main)
