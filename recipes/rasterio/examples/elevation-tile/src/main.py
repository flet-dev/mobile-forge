"""A GeoTIFF written into app storage, read back, and differenced against its source array."""

import os
import time

import flet as ft
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.windows import Window

# A proj-string rather than "EPSG:4326". PROJ parses this itself; an authority code needs
# proj.db, which these wheels do not ship, so the EPSG panel below is left to fail.
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


def residual(got, want):
    """Mismatched element count and worst absolute difference between two arrays."""
    diff = np.abs(got - want)
    return int(np.count_nonzero(diff)), float(diff.max())


def line(text):
    """One monospaced result line; anything past ~55 characters wraps on a phone."""
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


ELEVATION = surface(SIZE)


def main(page: ft.Page):
    """Write one GeoTIFF, read it back several ways, and print how far each read disagrees.

    Nothing on screen asserts that rasterio is right: every panel differences what came
    off disk against the numpy array that was written, so the numbers are residuals
    rather than claims.
    """

    def header():
        """Versions, and GDAL's driver registry as it exists on this device.

        `rasterio.show_versions()` would be the obvious call and raises in 1.5.0, so the
        fields are read one at a time. `Env.drivers()` is the honest capability list — a
        handful of entries on a phone against about 150 on a desktop — and it needs the
        `Env` entered, since it reads the current thread's GDAL environment.
        """
        with rasterio.Env() as env:
            drivers = sorted(env.drivers())
        extra = f" (+{len(drivers) - 12} more)" if len(drivers) > 12 else ""
        return [
            line(
                f"rasterio {rasterio.__version__} - GDAL {rasterio.__gdal_version__} - "
                f"PROJ {rasterio.__proj_version__}"
            ),
            line(f"{len(drivers)} drivers: {', '.join(drivers[:12])}{extra}"),
        ]

    def epsg_row():
        """The one call the missing PROJ database costs, run rather than described.

        Prints a CRS on a desktop, where rasterio's own wheel bundles proj.db, and a
        CRSError on a phone, where nothing does. Caught, because an unhandled exception
        in a Flet handler ends the session with a crash screen.
        """
        try:
            return line(f"CRS.from_epsg(4326) -> {CRS.from_epsg(4326).to_string()}")
        except Exception as err:
            return line(f"CRS.from_epsg(4326) -> {type(err).__name__}: {err}"[:200])

    def sample():
        """Read one centred window with its own dataset handle, differenced against numpy.

        The `rasterio.open` is inside the worker deliberately. Handing one default handle
        to several threads does not raise — it takes the process down — so each worker
        opens its own. `rasterio.open(..., thread_safe=True)` is the other way out.
        """
        side = int(size.value)
        offset = (SIZE - side) // 2
        try:
            # GDAL's driver registry is per-thread, and this runs in a worker: without
            # an Env entered here every driver reads as unregistered.
            with rasterio.Env(), rasterio.open(PATH) as ds:
                started = time.perf_counter()
                data = ds.read(1, window=Window(offset, offset, side, side))
                elapsed = (time.perf_counter() - started) * 1000
            bad, worst = residual(
                data, ELEVATION[offset : offset + side, offset : offset + side]
            )
            readout.value = (
                f"{side}x{side} in {elapsed:.2f} ms, {data.nbytes:,} B - "
                f"{bad} differ, worst {worst:.3e}"
            )
        except Exception as err:
            readout.value = f"{type(err).__name__}: {err}"
        page.update()

    def build():
        """Write the surface as a tiled GeoTIFF, then fill the round-trip panel.

        Runs in the thread pool: at 1024x1024 the write plus a full read is long enough
        to drop frames. Every row is a measurement — bytes, milliseconds or a residual
        against `ELEVATION` — and the whole body is wrapped because `page.run_thread`
        retrieves no future, so an exception here would otherwise vanish.
        """
        try:
            # GDAL's driver registry is per-thread and this runs in a worker:
            # without an Env entered here every driver reads as unregistered.
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
                    blocks = len(list(ds.block_windows(1)))
                    bad, worst = residual(full, ELEVATION)
                    # The affine transform, not the CRS, is what turns a coordinate into a
                    # pixel — so this resolves with no PROJ database behind it.
                    row, col = ds.index(*PROBE)
                    here = float(next(ds.sample([PROBE]))[0])
                    # GDAL accumulates in float64; numpy's default for a float32 array is
                    # float32, which loses the last six digits and hides the real agreement.
                    drift = max(
                        abs(stats.min - float(ELEVATION.min())),
                        abs(stats.max - float(ELEVATION.max())),
                        abs(stats.mean - float(ELEVATION.mean(dtype="float64"))),
                        abs(stats.std - float(ELEVATION.std(dtype="float64"))),
                    )
                    rows = [
                        line(f"{'driver':<9}{ds.driver}, {ds.profile['compress']}"),
                        line(f"{'blocks':<9}{blocks} of {ds.block_shapes[0]}"),
                        line(
                            f"{'size':<9}{os.path.getsize(PATH):,} B on disk, "
                            f"{ELEVATION.nbytes:,} B as an array"
                        ),
                        line(f"{'crs':<9}{ds.crs.to_dict()}"),
                        line(f"{'':<9}to_epsg {ds.crs.to_epsg()}"),
                        line(
                            f"{'bounds':<9}{ds.bounds.left:.3f}..{ds.bounds.right:.3f}E, "
                            f"{ds.bounds.bottom:.3f}..{ds.bounds.top:.3f}N"
                        ),
                        line(
                            f"{'lookup':<9}{PROBE[0]}E {PROBE[1]}N -> row {row}, col {col}"
                        ),
                        line(
                            f"{'':<9}{here:.4f}, delta vs numpy "
                            f"{abs(here - float(ELEVATION[row, col])):.3e}"
                        ),
                        line(f"{'write':<9}{write_ms:.0f} ms"),
                        line(
                            f"{'read':<9}{read_ms:.0f} ms - {bad} differ, worst {worst:.3e}"
                        ),
                        line(
                            f"{'stats':<9}min {stats.min:.4f}, max {stats.max:.4f}, "
                            f"mean {stats.mean:.4f}"
                        ),
                        line(f"{'':<9}worst delta vs numpy {drift:.3e}"),
                    ]
                size.disabled = False
        except Exception as err:
            rows = [line(f"{type(err).__name__}: {err}")]
        report.controls = rows
        sample()  # carries the page.update() this worker needs

    def resize():
        """Re-read at the slider's new window size, off the UI thread."""
        page.run_thread(sample)

    page.appbar = ft.AppBar(title=ft.Text("Elevation tile"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=6,
                controls=[
                    *header(),
                    ft.Divider(),
                    heading(f"{SIZE}x{SIZE} float32 GeoTIFF, written then read back"),
                    report := ft.Column(spacing=6, controls=[line("writing...")]),
                    ft.Divider(),
                    heading("Windowed read"),
                    size := ft.Slider(
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
                    heading("What needs a PROJ database"),
                    epsg_row(),
                ],
            ),
        )
    )

    page.run_thread(build)


if __name__ == "__main__":
    ft.run(main)
