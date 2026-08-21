"""Write a point layer through OGR and read it straight back.

Everything pyogrio touches lives here, and every function returns plain values,
so main.py only ever deals with numbers, strings and lists.
"""

import os
import struct
import time

import numpy as np
import pyogrio
from pyogrio.raw import read as ogr_read
from pyogrio.raw import write as ogr_write

# A PROJ string rather than "EPSG:4326". Naming a CRS by authority code means
# looking the code up in proj.db, and the mobile wheels carry no PROJ database.
CRS = "+proj=longlat +datum=WGS84 +no_defs"

# Two of the three file formats this GDAL can write, and the file name each
# one gets. The Shapefile stem grows four siblings on write.
FORMATS = {"GeoJSON": "stations.geojson", "ESRI Shapefile": "stations.shp"}

# Three of these four names are longer than ten characters, which is deliberate:
# the DBF field names a Shapefile can hold are not.
FIELDS = np.array(["station_name", "reading_count", "elevation_m", "calibrated"])

VERSION = (
    f"pyogrio {pyogrio.__version__} · "
    f"GDAL {'.'.join(str(part) for part in pyogrio.__gdal_version__)}"
)


def dataset_dir(driver):
    """Return a writable directory of its own for one dataset, creating it.

    A Shapefile is five files sharing a stem, so a dataset gets a directory
    rather than a path: copying, replacing or deleting it is then one move
    instead of a glob that can miss a sibling.
    """
    root = os.getenv("FLET_APP_STORAGE_DATA", ".")
    path = os.path.join(root, "vector-io", driver.replace(" ", "-").lower())
    os.makedirs(path, exist_ok=True)
    return path


def point_wkb(x, y):
    """Encode one 2-D point as little-endian WKB, which is what OGR reads."""
    return b"\x01" + struct.pack("<I", 1) + struct.pack("<dd", x, y)


def decode_point(wkb):
    """Decode one WKB point back to (x, y), honouring its byte-order flag."""
    order = "<" if wkb[0] == 1 else ">"
    return struct.unpack(order + "dd", wkb[5:21])


def make_stations(count):
    """Build `count` synthetic stations and keep the truth to compare against.

    The raw API wants geometry as an array of WKB byte strings and one array
    per attribute column, so numpy is the entire interface: no geopandas, no
    shapely, no dataframe. The four columns are a string, a 64-bit integer, a
    float and a boolean, because that is where the two formats disagree.
    """
    rng = np.random.default_rng(count)
    # Full-precision doubles, so the residual reported after the round trip is
    # the format's own: a Shapefile stores the bytes, GeoJSON stores digits.
    xs = rng.uniform(-9.5, 3.2, count)
    ys = rng.uniform(41.3, 51.1, count)
    geometry = np.array([point_wkb(x, y) for x, y in zip(xs, ys)], dtype=object)
    field_data = [
        np.array([f"station-{index:05d}" for index in range(count)], dtype=object),
        np.arange(count, dtype="int64") * 7,
        np.round(rng.uniform(-4.0, 1344.0, count), 3),
        np.arange(count) % 3 == 0,
    ]
    return xs, ys, geometry, field_data


def registered_drivers():
    """Return the driver table as (name, modes) pairs, `r` and `w` per name.

    This reads the registry through pyogrio's `_ogr` extension, while reads and
    writes go through `_io`. On Android both are views of one shared libgdal;
    on iOS they are two statically linked copies, so a full table here is not
    evidence that a round trip will work.
    """
    return sorted(pyogrio.list_drivers().items())


def compare(field_data, returned):
    """Count attribute values that came back different from what went out."""
    wrong = 0
    for original, back in zip(field_data, returned):
        if original.dtype == object:
            wrong += sum(str(a) != str(b) for a, b in zip(original, back))
        else:
            wrong += int(np.count_nonzero(original != back.astype(original.dtype)))
    return wrong


def roundtrip(driver, count):
    """Write the stations with `driver`, read them back, and report the damage.

    Both halves are timed separately, and the comparison is done against the
    arrays that were generated rather than against the file, so the result says
    what survived OGR rather than what OGR is willing to re-read.
    """
    xs, ys, geometry, field_data = make_stations(count)
    directory = dataset_dir(driver)
    path = os.path.join(directory, FORMATS[driver])

    started = time.perf_counter()
    ogr_write(
        path,
        geometry,
        field_data,
        FIELDS,
        driver=driver,
        geometry_type="Point",
        crs=CRS,
    )
    write_ms = (time.perf_counter() - started) * 1e3

    started = time.perf_counter()
    meta, _fids, geometry_back, returned = ogr_read(path)
    read_ms = (time.perf_counter() - started) * 1e3

    coordinates = np.array([decode_point(wkb) for wkb in geometry_back])
    files = sorted(os.listdir(directory))
    return {
        "files": files,
        "bytes": sum(os.path.getsize(os.path.join(directory, f)) for f in files),
        "write_ms": write_ms,
        "read_ms": read_ms,
        "features": len(geometry_back),
        "fields": list(meta["fields"]),
        "dtypes": list(meta["dtypes"]),
        "crs": meta["crs"] or "",
        "worst_coordinate": float(
            np.max(np.abs(coordinates - np.column_stack([xs, ys])))
        ),
        "wrong_values": compare(field_data, returned),
    }
