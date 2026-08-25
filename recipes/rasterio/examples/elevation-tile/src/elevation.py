"""The rasterio half of the app: write one GeoTIFF, read it back, measure the disagreement.

Nothing here touches Flet. Every function returns numbers so the caller prints residuals
rather than claims.
"""

import os
import time

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.windows import Window

# A proj-string rather than "EPSG:4326". PROJ parses this itself; an authority code needs
# proj.db, which these wheels do not ship, so the EPSG probe below is left to fail.
CRS_STRING = "+proj=longlat +datum=WGS84 +no_defs"
SIZE = 1024
BLOCK = 256
ORIGIN = (10.0, 60.0)
PIXEL = 0.0005
PROBE = (10.25, 59.75)
PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "elevation.tif")


def surface(n):
    """An n x n float32 elevation field, deterministic so a read-back can be differenced."""
    rows, cols = np.mgrid[0:n, 0:n].astype("float32")
    height = np.sin(cols / 61.0) * np.cos(rows / 47.0) * 300.0
    return (height + cols * 0.25 + rows * 0.1).astype("float32")


ELEVATION = surface(SIZE)


def residual(got, want):
    """Mismatched element count and worst absolute difference between two arrays."""
    diff = np.abs(got - want)
    return int(np.count_nonzero(diff)), float(diff.max())


def versions():
    """Version strings, plus GDAL's driver registry as it exists on this device.

    `rasterio.show_versions()` would be the obvious call and raises in 1.5.0, so the fields
    are read one at a time. `Env.drivers()` is the honest capability list — eleven entries on
    a phone against about 150 on a desktop — and it needs the `Env` entered, since it reads
    the current thread's GDAL environment.
    """
    with rasterio.Env() as env:
        drivers = sorted(env.drivers())
    return {
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
        "proj": rasterio.__proj_version__,
        "drivers": drivers,
    }


def epsg_probe():
    """Run `CRS.from_epsg(4326)` and report what came back, exception included.

    The one call the missing PROJ database costs, run rather than described: a CRS on a
    desktop, where rasterio's own wheel bundles proj.db, and a CRSError on a phone, where
    nothing does. Caught here, because an unhandled exception in a Flet handler ends the
    session with a crash screen.
    """
    try:
        return CRS.from_epsg(4326).to_string()
    except Exception as err:
        return f"{type(err).__name__}: {err}"[:200]


def round_trip():
    """Write the surface as a tiled GeoTIFF, read it back, and measure every disagreement.

    The `rasterio.Env()` is entered here rather than by the caller because GDAL's environment
    is thread-local and this runs in a worker: without one, every driver reads as
    unregistered.
    """
    with rasterio.Env():
        started = time.perf_counter()
        with rasterio.open(
            PATH,
            "w",
            driver="GTiff",
            height=SIZE,
            width=SIZE,
            count=1,
            dtype="float32",
            crs=CRS.from_string(CRS_STRING),
            transform=from_origin(*ORIGIN, PIXEL, PIXEL),
            tiled=True,
            blockxsize=BLOCK,
            blockysize=BLOCK,
            compress="DEFLATE",
            predictor=3,
        ) as dst:
            dst.write(ELEVATION, 1)
        write_ms = (time.perf_counter() - started) * 1000

        with rasterio.open(PATH) as ds:
            started = time.perf_counter()
            full = ds.read(1)
            read_ms = (time.perf_counter() - started) * 1000
            stats = ds.stats(indexes=1, approx=False)[0]
            differ, worst = residual(full, ELEVATION)
            # The affine transform, not the CRS, is what turns a coordinate into a pixel —
            # so this resolves with no PROJ database behind it.
            row, col = ds.index(*PROBE)
            here = float(next(ds.sample([PROBE]))[0])
            # GDAL accumulates in float64; numpy's default for a float32 array is float32,
            # which loses the last six digits and hides the real agreement.
            drift = max(
                abs(stats.min - float(ELEVATION.min())),
                abs(stats.max - float(ELEVATION.max())),
                abs(stats.mean - float(ELEVATION.mean(dtype="float64"))),
                abs(stats.std - float(ELEVATION.std(dtype="float64"))),
            )
            return {
                "driver": ds.driver,
                "compress": ds.profile["compress"],
                "blocks": len(list(ds.block_windows(1))),
                "block_shape": ds.block_shapes[0],
                "on_disk": os.path.getsize(PATH),
                "in_memory": int(ELEVATION.nbytes),
                "crs": ds.crs.to_dict(),
                "epsg": ds.crs.to_epsg(),
                "bounds": ds.bounds,
                "row": row,
                "col": col,
                "sample": here,
                "sample_delta": abs(here - float(ELEVATION[row, col])),
                "write_ms": write_ms,
                "read_ms": read_ms,
                "differ": differ,
                "worst": worst,
                "stats": stats,
                "stats_drift": drift,
            }


def window_read(side):
    """Read one centred `side` x `side` window and difference it against numpy.

    The `rasterio.open` is inside this function deliberately: handing one default dataset
    handle to several threads does not raise, it takes the process down, so every worker
    opens its own. `rasterio.open(..., thread_safe=True)` is the other way out.
    """
    offset = (SIZE - side) // 2
    with rasterio.Env(), rasterio.open(PATH) as ds:
        started = time.perf_counter()
        data = ds.read(1, window=Window(offset, offset, side, side))
        elapsed = (time.perf_counter() - started) * 1000
    differ, worst = residual(
        data, ELEVATION[offset : offset + side, offset : offset + side]
    )
    return {
        "side": side,
        "ms": elapsed,
        "bytes": int(data.nbytes),
        "differ": differ,
        "worst": worst,
    }
