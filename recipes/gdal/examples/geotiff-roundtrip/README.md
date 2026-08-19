# gdal GeoTIFF round trip

A 512×512 float32 GeoTIFF written into app storage, read back and compared against the
numbers it was built from — with the `gdal_array`, `osr` and `ogr` paths run beside it,
because on iOS each of those is a **separate statically-linked copy of GDAL with its own
driver table**. Every row on screen is a residual or an exception class, not a claim.

The surface is generated at runtime by a formula in `src/main.py`, in pure Python via
`array("f")`, so the raster panel owes numpy nothing and the read-back is differenced
against a reference GDAL never touched. Nothing is bundled and nothing is downloaded.

What it demonstrates:

- **A round trip that stays inside one extension.**
  [`gdal.GetDriverByName("GTiff").Create(...)`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Driver.Create)
  with `COMPRESS=DEFLATE`, `PREDICTOR=3` and 256×256 tiles,
  [`band.WriteRaster`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Band.WriteRaster),
  then [`gdal.Open`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Open)
  and [`band.ReadRaster`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Band.ReadRaster)
  — every one of those resolves to `_gdal`, which is why this is the panel most likely to
  behave the same on both platforms. It prints how many of the 262,144 elements differ and
  the worst absolute residual.
- **How much of GDAL the import actually mapped.** The header reads the six `osgeo`
  extensions out of `sys.modules` before anything else runs, and again after
  `gdal.UseExceptions()`. Expect `4/6` on the first line and `6/6` on the second — the same
  two counts on both platforms. The bytes beside them are summed from whichever of those
  extension files the loader can still name on disk, which is where the two platforms part
  company.
- **Three cross-extension handoffs, each measured.**
  [`band.ReadAsArray()`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Band.ReadAsArray)
  is `_gdal_array` code operating on a `_gdal` object, differenced against the same
  reference. A CRS built in `_osr` is attached to two datasets two ways — as a WKT *string*
  via `SetProjection` and as an *object* via `SetSpatialRef` — and the two read-backs are
  compared byte for byte. A three-feature GeoJSON is written and re-opened with
  `gdal.OpenEx(path, gdal.OF_VECTOR)`, then walked with
  [`layer.GetFeatureCount()`](https://gdal.org/en/stable/api/python/vector_api.html#osgeo.ogr.Layer.GetFeatureCount)
  and [`feature.GetGeometryRef()`](https://gdal.org/en/stable/api/python/vector_api.html#osgeo.ogr.Feature.GetGeometryRef),
  with the coordinates differenced against the ones written.
- **What the missing PROJ database costs.**
  [`ImportFromEPSG(4326)`](https://gdal.org/en/stable/api/python/spatial_ref_api.html#osgeo.osr.SpatialReference.ImportFromEPSG)
  is run rather than avoided, so it prints a CRS name on a desktop and an exception on a
  phone. The raster itself carries no CRS: georeferencing here is the affine transform
  (`gdal.InvGeoTransform` → `gdal.ApplyGeoTransform`), which needs no database at all.
- **What the device actually supports**, read from the live registry:
  [`gdal.GetDriverCount()`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.GetDriverCount)
  with every short name, beside `ogr.GetDriverCount()` for the vector-capable subset.
- **The exception default that changes in GDAL 4.0.** `gdal.Open` on a missing file is
  called once before
  [`gdal.UseExceptions()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.UseExceptions)
  — printing `None`, `gdal.GetLastErrorMsg()` and the `FutureWarning` captured off the
  warnings machinery — and once after, printing the `RuntimeError`.
- **A windowed read off the UI thread.** An [`ft.Slider`](https://flet.dev/docs/controls/slider/)
  picks the window side and drives a re-read from
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread). The
  worker opens **its own** dataset, because sharing one handle between threads takes the
  process down rather than raising, and it calls `gdal.Open` with no preamble — unlike
  rasterio, `osgeo.gdal` has no per-thread environment to enter.

Each panel is wrapped in its own `try/except` and renders the exception's class and
message, because an unhandled exception in a Flet handler ends the session with a crash
screen and you lose the diagnosis.

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

A desktop run (`uv run flet run`) resolves GDAL from PyPI or Homebrew instead, and differs
in three places over and above the timings: the driver line reads hundreds rather than
eleven, `ImportFromEPSG(4326)` succeeds because that build bundles `proj.db`, and the
extension byte totals are whatever your host GDAL happens to weigh. Every residual should
be identical. Against a host GDAL 3.13.0 the whole screen came out as 0 of 262,144 elements
differing with a worst residual of 0.0, `4/6` then `6/6` extensions mapped, the two CRS
routes agreeing at 278 bytes each, and the three GeoJSON coordinates exact.
