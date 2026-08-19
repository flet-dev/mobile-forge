# rasterio elevation tile

A GeoTIFF written, read back and differenced against the array it came from, on a device
that carries no PROJ database. Every panel prints a count of mismatched elements and a
worst absolute residual, so what you read is a measurement rather than a claim.

A 1024×1024 float32 elevation surface is generated in numpy from a formula written in
`src/main.py`, written into
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
as a tiled DEFLATE GeoTIFF, and read back several ways. It ships no data file and reaches
no network — everything is generated at runtime.

What it demonstrates:

- **A GeoTIFF round trip that checks itself** — a full
  [`read`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.read)
  differenced element-wise against the source array, a
  [`Window`](https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html) read
  differenced against the equivalent numpy slice, and
  [`ds.stats(approx=False)`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.stats)
  against `min`/`max`/`mean`/`std` computed in float64. All three residuals are zero or a
  few times 1e-13.
- **A CRS with no database behind it** — the raster is tagged with a `+proj=` string,
  because these wheels ship no `proj.db`. The profile row prints the CRS as it survived the
  round trip, along with `to_epsg()` → `None`.
- **Georeferencing, which needs no database at all** — a longitude/latitude pair goes
  through [`ds.index`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.index)
  to a row and column and through
  [`ds.sample`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.sample)
  to an elevation, differenced against the same element of the source array. That is the
  affine transform, not the CRS, so it is the part of "geospatial" that still works here.
- **What the device actually supports**, read from the live registry rather than described:
  `env.drivers()` inside a
  [`rasterio.Env`](https://rasterio.readthedocs.io/en/stable/api/rasterio.env.html#rasterio.env.Env)
  names 147 drivers on a desktop and eleven on a phone, where GDAL was built with four
  raster drivers, five vector ones and the two GNM network ones.
- **Where the missing database bites** —
  [`CRS.from_epsg(4326)`](https://rasterio.readthedocs.io/en/stable/api/rasterio.crs.html#rasterio.crs.CRS.from_epsg)
  is run rather than avoided, and prints a CRS on a desktop and a `CRSError` on a phone.
- **Why a window is worth having** — a
  [`ft.Slider`](https://flet.dev/docs/controls/slider/) picks the window side and drives a
  re-read from [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread).
  The worker opens **its own** dataset, because handing one dataset object to several
  threads takes the process down rather than raising.

The `ds.stats(approx=False)` call also leaves an `elevation.tif.aux.xml` beside the raster —
GDAL's statistics sidecar, 385 bytes here — which is why the file has to live in writable
app storage and not in assets.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

A desktop run (`uv run flet run`) differs in three rows, over and above the timings that
move on every run: rasterio's PyPI wheel bundles its own `proj_data`, so
`CRS.from_epsg(4326)` succeeds and the profile's `to_epsg` reads `4326` rather than `None`,
and the driver line reads `147 drivers` rather than the eleven a phone registers. Every
residual is identical.
