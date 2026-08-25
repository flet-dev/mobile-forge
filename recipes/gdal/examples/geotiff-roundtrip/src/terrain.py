"""Every osgeo call in this example.

No Flet import anywhere in here: each panel returns already-formatted strings, so the
package work and the UI stay separable. The osgeo import is guarded because the gdal wheel
exists only for Android and iOS — off-device, IMPORT_ERROR is set and every function below
would raise on the None modules, so main.py checks it before calling any of them.
"""

import math
import os
import sys
import time
import warnings
from array import array

import numpy as np

try:
    from osgeo import gdal, ogr, osr

    IMPORT_ERROR = None
except Exception as err:  # pragma: no cover - only off-device
    gdal = ogr = osr = None
    IMPORT_ERROR = f"{type(err).__name__}: {err}"

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


def listed(names, limit=14):
    """Driver names, truncated: a phone registers eleven, a desktop over two hundred."""
    extra = f" (+{len(names) - limit} more)" if len(names) > limit else ""
    return ", ".join(names[:limit]) + extra


REFERENCE = surface(SIZE)


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


def versions():
    """The GDAL and PROJ version strings.

    On iOS these are the first calls into a PROJ that was absorbed into _osr at link time,
    so this is where a broken static link shows up first.
    """
    return (
        f"GDAL {gdal.VersionInfo('RELEASE_NAME')} - PROJ "
        f"{osr.GetPROJVersionMajor()}.{osr.GetPROJVersionMinor()}."
        f"{osr.GetPROJVersionMicro()}"
    )


def exception_modes():
    """gdal.Open on a missing file, before and after gdal.UseExceptions().

    Exceptions are off by default in 3.13, so the first call returns None and warns that
    GDAL 4.0 will flip it. The warning is captured rather than described, because on device
    it would otherwise go to stderr and be lost. Run this panel first: it owns the only
    gdal.Open made before UseExceptions(), and the FutureWarning fires once per process.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        opened = gdal.Open(MISSING)
    rows = [
        f"{'default':<8}gdal.Open(missing) -> {opened!r}",
        f"{'':<8}{gdal.GetLastErrorMsg().strip()[:88]}",
    ]
    rows += [f"{'':<8}{w.category.__name__}: {w.message}" for w in caught]
    gdal.UseExceptions()
    try:
        gdal.Open(MISSING)
        rows.append(f"{'after':<8}returned without raising")
    except Exception as err:
        rows.append(f"{'after':<8}{type(err).__name__}: {err}"[:180])
    return rows


def registry():
    """The live driver tables of _gdal and _ogr, which on iOS are separate images.

    Asked rather than assumed: a phone registers a small fraction of what a desktop does,
    and the two counts differ because ogr sees only the vector-capable drivers.
    """
    raster = sorted(gdal.GetDriver(i).ShortName for i in range(gdal.GetDriverCount()))
    vector = sorted(ogr.GetDriver(i).GetName() for i in range(ogr.GetDriverCount()))
    return [
        f"gdal {len(raster)}: {listed(raster)}",
        f"ogr  {len(vector)}: {listed(vector)}",
    ]


def roundtrip():
    """Write the surface as a tiled GeoTIFF, read it all back, and difference it.

    Every call here resolves to _gdal — driver lookup, create, band, both raster transfers,
    the re-open and the geotransform maths — so this is the panel with no cross-extension
    handoff in it at all. No CRS is attached on purpose; that story belongs to the _osr
    panel, and georeferencing is the affine transform regardless.
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
    # Read back rather than assumed: a missing codec fails the Create outright, but an
    # unrecognised COMPRESS value is only a warning and writes an uncompressed file.
    structure = ds.GetMetadata("IMAGE_STRUCTURE")
    want = REFERENCE[int(row) * SIZE + int(col)]
    rows = [
        (
            f"{'driver':<7}{ds.GetDriver().ShortName}, "
            f"{structure.get('COMPRESSION', 'none')}/"
            f"{structure.get('PREDICTOR', '-')}, {band.GetBlockSize()}"
        ),
        (
            f"{'size':<7}{os.path.getsize(RASTER):,} B on disk, "
            f"{len(REFERENCE) * 4:,} B as float32"
        ),
        f"{'write':<7}{write_ms:.0f} ms",
        f"{'read':<7}{read_ms:.0f} ms - {bad:,} of {len(REFERENCE):,} differ",
        f"{'':<7}worst {worst:.3e}",
        f"{'pixel':<7}{PROBE[0]}E {PROBE[1]}N -> col {int(col)}, row {int(row)}",
        f"{'':<7}{here:.4f}, delta {abs(here - want):.3e}",
    ]
    ds = band = None
    return rows


def numpy_rows():
    """band.ReadAsArray() — _gdal_array code running on an object minted by _gdal.

    numpy is an optional extra of the gdal wheel, so a plain "gdal" dependency leaves this
    raising ModuleNotFoundError at the point of use; the app pins numpy for it.
    """
    ds = gdal.Open(RASTER)
    started = time.perf_counter()
    arr = ds.GetRasterBand(1).ReadAsArray()
    elapsed = (time.perf_counter() - started) * 1000
    ds = None
    diff = np.abs(arr - np.frombuffer(REFERENCE, dtype="float32").reshape(SIZE, SIZE))
    return [
        f"numpy {np.__version__} - {arr.dtype} {arr.shape} in {elapsed:.0f} ms",
        f"{int(np.count_nonzero(diff))} differ, worst {float(diff.max()):.3e}",
    ]


def spatial_rows():
    """A CRS built in _osr and attached to _gdal datasets as a string and as an object.

    The two routes are the interesting pair: ExportToWkt() sends text across the module
    boundary, SetSpatialRef() sends the object itself. On Android both reach one shared
    libgdal; on iOS they cross between two separately linked copies of it.
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
        f"proj4 {srs.ExportToProj4()}",
        f"SetProjection {len(wkt_text)} B / SetSpatialRef {len(wkt_object)} B",
        f"identical: {wkt_text == wkt_object}, IsSame: {same}",
    ]
    epsg = osr.SpatialReference()
    try:
        epsg.ImportFromEPSG(4326)
        rows.append(f"EPSG:4326 -> {epsg.GetName()}")
    except Exception as err:
        rows.append(f"EPSG:4326 -> {type(err).__name__}: {err}"[:180])
    return rows


def vector_rows():
    """A GeoJSON written and re-read, passing Layer and Feature objects between _gdal and _ogr.

    GetDriverByName, Create, OpenEx and GetLayer are _gdal calls; the Layer, Feature and
    Geometry objects they hand back belong to _ogr, so every coordinate below has crossed
    the boundary twice.
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
        f"{os.path.getsize(VECTOR):,} B, {count} features re-read",
        f"names match: {names == [name for name, _, _ in POINTS]}",
        f"worst coord delta {worst:.3e}",
    ]


def window_read(side):
    """Read one centred side x side window with a fresh handle, differenced against REFERENCE.

    The gdal.Open is inside this call deliberately: a dataset handle is not safe to share
    between threads, and the caller runs this on a pool thread.
    """
    offset = (SIZE - side) // 2
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
    return (
        f"{side}x{side} in {elapsed:.2f} ms, {len(raw):,} B - "
        f"{bad} differ, worst {worst:.3e}"
    )
