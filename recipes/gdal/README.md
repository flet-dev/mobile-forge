# gdal

[GDAL](https://gdal.org/)'s own Python bindings — `osgeo.gdal`, `osgeo.ogr`, `osgeo.osr` —
the raster and vector engine that sits underneath most of the geospatial stack, with the
thin SWIG wrapper the C++ API was designed around. On a phone that buys you a GeoTIFF round
trip, windowed reads out of a raster far larger than RAM, and GeoJSON or Shapefile I/O,
entirely in-process and with no network.

These wheels are a deliberately small GDAL: **eleven drivers**, no `proj.db`, no `GDAL_DATA`,
no libcurl, no GEOS. None of that announces itself at import; each missing piece surfaces as
one call failing, at the point of use. [`rasterio`](../rasterio) and [`pyogrio`](../pyogrio)
wrap the same GDAL build with friendlier APIs and are pleasanter to write against on
Android — but on iOS neither can reach a driver, and this package can, for a structural
reason set out under [Extension modules](#extension-modules).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
]

[tool.flet.android]
dependencies = [
    "gdal",
]

[tool.flet.ios]
dependencies = [
    "gdal",
]
```

**Keep gdal out of `[project] dependencies`, and not for the usual reason.** Both platforms
have wheels on the index, but **upstream publishes no wheel for any desktop** — PyPI carries
a source tarball whose build wants a system libgdal and `gdal-config`. Flet
[appends](https://flet.dev/docs/publish/#app-dependencies) `[tool.flet.<platform>].dependencies`
to the project list rather than replacing it, so a top-level `"gdal"` is *also* handed to the
host resolve `flet build` performs first, which tries that sdist and stops the build with
`Call to setuptools.build_meta.build_wheel failed` before it reaches a device. Measured
2026-08-19 against `flet build apk` and `flet build ios-simulator` alike.

The cost is that **gdal is then absent from `flet run` and from a web build**, since nothing
outside an Android or iOS `flet build` reads those tables: `from osgeo import gdal` raises
`ModuleNotFoundError` everywhere you develop. Guard the import so those runs explain
themselves instead of crashing, as [`geotiff-roundtrip`](examples/geotiff-roundtrip) does.

**`numpy` is an optional extra, not a dependency.** Write `"gdal[numpy]"`, or add `"numpy"`
alongside it, if you want the array API; a bare `"gdal"` leaves
[`band.ReadAsArray()`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Band.ReadAsArray)
raising `ModuleNotFoundError: No module named 'numpy'` at the point of use rather than at
import. numpy raises your own `requires-python` floor as a side effect — 2.4.6 needs
`>=3.11`, and `uv` fails the resolve for lower splits otherwise.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`geotiff-roundtrip`](examples/geotiff-roundtrip) — a GeoTIFF written to app storage and
  read back, with the `gdal_array`, `osr` and `ogr` paths measured beside it.

## Usage in a Flet app

Write a raster, close it, read a window back:

```python
gdal.UseExceptions()  # once, at startup — see Things to know

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "surface.tif")
ds = gdal.GetDriverByName("GTiff").Create(
    path, 512, 512, 1, gdal.GDT_Float32,
    options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"],
)
ds.SetGeoTransform([10.0, 0.001, 0.0, 60.0, 0.0, -0.001])  # origin, then pixel size
ds.GetRasterBand(1).WriteRaster(0, 0, 512, 512, values.tobytes())
ds = None  # dropping the last reference is what flushes the file

ds = gdal.Open(path)
raw = ds.GetRasterBand(1).ReadRaster(128, 128, 64, 64)  # a window, not the whole band
caption = ft.Text(f"{ds.GetDriver().ShortName}: {len(raw):,} bytes back")
```

`ds = None` is not tidiness — GDAL flushes and closes when the last reference drops, and a
file still held open is one `Driver.Create` on the same path will refuse to replace.
[`ReadRaster`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Band.ReadRaster)
returns `bytes` in the band's dtype and native byte order, which
[`array.frombytes`](https://docs.python.org/3/library/array.html#array.array.frombytes) or
`numpy.frombuffer` unpacks; `ReadAsArray()` returns the numpy array directly, at the cost of
the optional extra above. Reading a window rather than a whole band is what lets a phone open
a raster larger than its RAM.

### Storage

Rasters and vector files belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, durable, included in backups, and from Flet 0.86.0 also the process working
directory on device. It has to be a **writable** directory rather than a bundled asset,
because GDAL writes beside the file: `band.ComputeStatistics(False)` on the example's
512×512 GeoTIFF left a 385-byte `surface.tif.aux.xml` next to it (measured on a host GDAL
3.13.0; PAM sidecars are GDAL's behaviour, not a mobile quirk), and updating an existing
raster needs `gdal.GA_Update` on the file itself.

Avoid
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it) and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) for anything you want to keep.

### Coordinate systems

**No `proj.db` and no `GDAL_DATA` reach the device, on either platform** — nothing in this
chain ships a data file of any kind, and the diagnostics for the gap (`Cannot find proj.db`,
`Cannot find %s (GDAL_DATA is not defined)`) are compiled into the shipped binaries. The
consequence is one rule: **anything that names an authority cannot resolve.**
[`ImportFromEPSG(4326)`](https://gdal.org/en/stable/api/python/spatial_ref_api.html#osgeo.osr.SpatialReference.ImportFromEPSG)
is the call to expect trouble from; a proj-string or WKT through
[`SetFromUserInput`](https://gdal.org/en/stable/api/python/spatial_ref_api.html#osgeo.osr.SpatialReference.SetFromUserInput)
needs no database at all:

```python
srs = osr.SpatialReference()
srs.SetFromUserInput("+proj=longlat +datum=WGS84 +no_defs")
ds.SetSpatialRef(srs)
```

The [`geotiff-roundtrip`](examples/geotiff-roundtrip) example builds its CRS that way and runs
the EPSG call anyway, so the difference shows on the device rather than being asserted here.

If you need EPSG codes, ship `proj.db` as an [asset](https://flet.dev/docs/cookbook/assets)
and point PROJ at the directory holding it — `osgeo/osr.py` exposes `SetPROJSearchPath(path)`
and `SetPROJSearchPaths([path])`, and PROJ's `PROJ_DATA`/`PROJ_LIB` variables are compiled in.
The database has to match: this chain is PROJ **9.5.0**, which validates a database's declared
layout version and rejects a mismatch with *"It comes from another PROJ installation"*. The
9,273,344-byte `proj.db` from the `pyproj` 3.7.2 PyPI wheel declares layout 1.4 and was
accepted by a PROJ 9.5.0 built from the tarball this chain uses; [`pyproj`](../pyproj) has
that measurement and the grid-file and network picture around it. **None of those routes has
been run on a device for this recipe.**

### Drivers and codecs

**Eleven drivers, four of them raster: `GTiff`, `COG`, `VRT`, `MEM`, plus `ESRI Shapefile`,
`GeoJSON`, `GeoJSONSeq`, `ESRIJSON`, `TopoJSON` and the two network drivers `GNMFile` and
`GNMDatabase`.** No PNG, JPEG, GPKG, SQLite, CSV, GML, KML, netCDF, GRIB or JP2 — decode a
PNG or JPEG with [`pillow`](../pillow) or [`opencv-python`](../opencv-python) instead, and
convert other formats off-device. Ask the live registry rather than trusting a list, this one
included:

```python
[gdal.GetDriver(i).ShortName for i in range(gdal.GetDriverCount())]
ogr.GetDriverCount()  # the vector-capable subset
```

**Five TIFF codecs are linked: LZW, Deflate, PackBits, JPEG and LERC. ZSTD, WEBP and LZMA are
not**, despite GDAL advertising all of them in the
[GTiff `COMPRESS` option list](https://gdal.org/en/stable/drivers/raster/gtiff.html#creation-options),
which it compiles in unconditionally and filters at runtime. `COMPRESS=DEFLATE` with
`PREDICTOR=3` for floats is the sane default.

Asking for one of the missing three is a **hard failure, not a fallback** — and a
neighbouring mistake behaves the opposite way, which is what makes this worth knowing. On a
host GDAL 3.13.0 built without WEBP, `Create(..., options=["COMPRESS=WEBP"])` logged
`ERROR 1: Cannot create TIFF file due to missing codec for WEBP.` and returned `None`, no
file written. A *misspelt* codec logs only `Warning 5: COMPRESS=NOTACODEC value not
recognised, ignoring.` and hands back a dataset that writes an uncompressed TIFF. Read
`ds.GetMetadata("IMAGE_STRUCTURE")` back to see which compression is actually in force.

**GDAL is compiled without libcurl and without GEOS.** Both platforms carry GDAL's
`#else`-branch diagnostics *"GDAL/OGR not compiled with libcurl support, remote requests not
supported."* and *"GEOS support not enabled."*, so `/vsicurl/`, `/vsis3/`, `/vsigs/` and
`/vsiaz/` are dead strings and OGR geometry predicates are unavailable. The virtual file
systems that do work are `/vsimem/`, `/vsizip/`, `/vsitar/`, `/vsigzip/`, `/vsisubfile/` and
`/vsisparse/`.

### Extension modules

`osgeo` is six compiled extensions — `_gdal`, `_gdalconst`, `_ogr`, `_osr`, `_gnm` and
`_gdal_array` — and **how they are linked is the one place the two platforms genuinely
differ.** On Android they share one `libgdal.so`, so there is a single driver table. On iOS
there is no shared library at all: five of the six each absorb a whole GDAL at link time,
24.3 to 26.5 MB apiece, and none of them can see another's copy. **That is five independent
copies of GDAL's driver table, error state and configuration options in one process.**

`import osgeo.gdal` is never one extension — **it maps four**: `_gdal`, `_gdalconst`, `_ogr`
and `_osr`, because `osgeo/gdal.py` does a module-level `from . import ogr` / `from . import
osr`. On iOS that first line costs **77,019,224 bytes** of dylib before you have touched a
raster, against 2,884,216 on Android arm64-v8a. There is nothing an app can do — the imports
are unconditional in upstream's SWIG output. Budget for it; the example prints the live
number on screen.

**What makes gdal usable on iOS where its wrappers are not** is that `osgeo.gdal` does not
split registration from lookup. `PyInit__gdal` itself calls `GDALAllRegister`, and every
native call in `osgeo/gdal.py` binds to `_gdal` — all 838 of them — so the driver lookup, the
create, the band, both raster transfers and the re-open land in the same image that registered
the drivers. `rasterio` and `pyogrio` put registration and I/O in *different* extensions,
which on iOS means different GDALs, which is why they fail there.

What is not settled is the **handoffs between extensions**, and that is what
[`geotiff-roundtrip`](examples/geotiff-roundtrip) exists to measure: `band.ReadAsArray()` is
`_gdal_array` code on a `_gdal` object,
[`ds.GetSpatialRef()`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Dataset.GetSpatialRef)
returns an object `_gdal` minted whose methods run in `_osr`, and
[`gdal.OpenEx(path, gdal.OF_VECTOR).GetLayer(0)`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.OpenEx)
hands a `_gdal` pointer to `_ogr`. SWIG's cross-module type table *is* shared, so objects
type-check across the boundary either way — a failure here would arrive as a wrong answer or a
crash, not a `TypeError`. Run the example before you rely on any of it.

**On iOS, prefer routes that keep a dataset inside one extension.** `band.ReadRaster()` and
`WriteRaster()` take and return `bytes` and never leave `_gdal`. `ReadAsArray()` and
`WriteArray()` cross into `_gdal_array`, but only to do a RasterIO on a pointer, with no
registry involved. The sharpest edge is `gdal_array.SaveArray(arr, path)`, which is a driver
from `_gdal`'s table copying a dataset that `_gdal_array` created in *its* GDAL, whose table
holds only the in-memory `NUMPY` driver. Untested on device, and easy to avoid:
`Driver.Create(...)` then `band.WriteArray(...)`.

### Threading

**A GDAL dataset handle is not safe to use from two threads at once.** That matters more than
usual under
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), which
submits to a shared pool, so two taps really do overlap. On this same GDAL build, eight
threads doing overlapping reads on one shared handle took the interpreter down with SIGBUS on
four of five runs — a native crash with no Python traceback. Open one dataset per thread (the
simplest rule, and what the example does), or hold a `threading.Lock` around the whole use.

**There is no per-thread environment to enter, unlike rasterio.** Driver registration happens
once, in the extension's own module init, so a worker thread can call
[`gdal.Open`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Open) with no
preamble; the example's slider worker does exactly that, which is what tests it. GDAL's own
thread-safe dataset mode is compiled in and reachable —
`gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_THREAD_SAFE)` returned a dataset reporting
[`IsThreadSafe`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Dataset.IsThreadSafe)`(gdal.OF_RASTER) == True`
on a host GDAL 3.13.0 — but it has not been exercised on a device.

The standing Flet caveats apply on top: `run_thread` never retrieves the worker's future, so
an exception inside one surfaces nowhere — wrap the body — and auto-update does not reach
background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### App size

**This is one of the largest payloads in this index, and the two platforms are not
comparable.** On Android arm64-v8a the wheel is 1,374,152 bytes, unpacking to 5,359,714, of
which 3,163,704 is the six extensions — on top of 22.8 MB of shared native libraries, most of
it `libgdal.so` itself. On the iOS device slice the wheel is 45,163,517 bytes,
unpacking to 128,501,803, of which **126,305,872 is the six extensions** and nothing else
installs. That is 40× the extension bytes on iOS for the same eleven drivers, or roughly 5×
once Android's shared libraries are counted in.

Use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI; on iOS there is no equivalent lever, and no
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) entry will
help, because the bytes are the extensions themselves.

Leave Flet's default [compilation and
cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) on: 2,182,268 bytes of the
payload is `.py`, of which 1,325,117 is `osgeo_utils/` — command-line tools nothing in the
package imports — and nothing here reads its own source, so `.pyc` is safe.

Expect a slow first `ipa` or `ios-simulator` build, and plenty of free disk. Each iOS slice
downloads and unpacks a 112,772,601-byte native GDAL wheel of which 11,986 bytes survive
cleanup into the app; there is nothing to configure, but the machine does that three times.

### Other considerations

**Your desktop is not a preview of the device.** `flet run` resolves GDAL from PyPI or
Homebrew — one shared libgdal, a full `proj.db`, and a registry of 214 drivers against the
mobile build's eleven on the machine this page was written on. EPSG codes, PNG and `ZSTD` all
work on your Mac and fail on the phone, and the single-table-versus-five-tables difference
does not exist there at all. Validate on a device or simulator, and make the app render its
own exceptions on screen — an unhandled exception in a Flet handler produces
`SESSION_CRASHED` and you lose the diagnosis.

## Things to know

- **Exceptions are off by default, and the bindings nag about it.** Without a call, a failed
  [`gdal.Open`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Open) or
  [`Driver.Create`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Driver.Create)
  returns `None`, and the first such call emits `FutureWarning: Neither gdal.UseExceptions()
  nor gdal.DontUseExceptions() has been explicitly called. In GDAL 4.0, exceptions will be
  enabled by default.` There are 21 call sites in `osgeo/gdal.py` — `Open`, `OpenEx`,
  `Driver.Create`, `Driver.CreateMultiDimensional`, `Driver.CreateCopy`, `Driver.Delete`,
  `Info`, `VectorInfo`, `MultiDimInfo`, `Translate`, `Warp`, `VectorTranslate`,
  `DEMProcessing`, `Nearblack`, `Grid`, `Contour`, `Rasterize`, `Footprint`, `BuildVRT`,
  `TileIndex` and `MultiDimTranslate`. A `None` dataset dereferenced later is an
  `AttributeError` a long way from the real failure, so turn exceptions on and print
  `type(err).__name__` plus
  [`gdal.GetLastErrorMsg()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.GetLastErrorMsg).

- **[`gdal.UseExceptions()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.UseExceptions)
  — the call every GDAL tutorial opens with — maps two more extensions.** It loops over gdal,
  gdal_array, ogr, osr and gnm, so it adds `_gnm` (+24,938,936 bytes on iOS) and, when numpy
  is installed, `_gdal_array` (+24,347,712): all six extensions, 126,305,872 bytes. Call it
  anyway, once at startup — error-code returns are worse — but know what it costs, and call
  it once rather than per handler.

- **[`gdal.ExceptionMgr()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.ExceptionMgr)
  looks like the cheaper switch and is not.** It skips `_gnm`, but its `__enter__` does
  `from . import gdal_array` inside a `try/except ImportError`, so it maps the 24.3 MB
  `_gdal_array` **even when numpy is absent** — and the Python wrapper then fails anyway.
  `UseExceptions()` is guarded by `find_spec("numpy")` and does not have that failure mode.
  Prefer one `UseExceptions()` at startup to a context manager per call.

- **The `gdalplugins/drivers.ini` that ships beside GDAL is not a capability list.** It is a
  2,787-byte ordering table naming 251 drivers, installed unconditionally; reading it as what
  was compiled in over-counts the registry by a factor of twenty-three, and on Android it does
  not even reach the device. Ask the live registry instead.

- **`Driver.Create` silently deletes an existing file first — until it can't.**
  `GDALDriver::Create` runs `QuietDelete` on the path before handing over to the driver, so a
  second `gdal.GetDriverByName("GeoJSON").Create(path, 0, 0, 0, gdal.GDT_Unknown)` on a
  *closed* file simply replaces it. `RuntimeError: The GeoJSON driver does not overwrite
  existing files.` appears only where that delete cannot happen: the previous dataset is
  still referenced, the directory is read-only, the path is a directory, or
  `APPEND_SUBDATASET=YES` is passed (four cases, all measured on host GDAL 3.13.0). So drop
  the writer reference before re-creating a path — `ds = None`, as the example does after
  every write — and remember that a re-run overwrites your data without a word.

## Build notes (maintainers)

### Recipe shape

Two recipes: `flet-libgdal` builds GDAL, `recipes/gdal` builds upstream's own bindings
against it. `patches/config.patch` explains both of its hunks and its own bump hazard in its
preamble, and `meta.yaml` comments its `GDAL_LIBS` and version pin next to them.

**Almost everything the consumer sections warn about is a `flet-libgdal` decision, not a gdal
one.** The eleven-driver registry, the codec set, the missing `GDAL_DATA` and `proj.db`, the
absent GEOS and libcurl and the iOS static-only link all come from that recipe and from
`flet-libproj`. A `flet-libgdal` bump can invalidate most of this README without a line
changing here.

**The iOS size is a linking artefact worth fixing at the source.** `meta.yaml`'s `GDAL_LIBS`
names the whole static chain because `libgdal.a` (524,528,736 bytes) leaks undefined symbols;
that is what drags a full GDAL into five of the six extensions and turns Android's 25,967,800
bytes of native code into 126,305,872. Per extension on the iOS device slice: `_gdal`
26,488,680, `_ogr` 25,678,176, `_gnm` 24,938,936, `_osr` 24,763,872, `_gdal_array`
24,347,712, `_gdalconst` 88,496. Aligning `flet-libgdal`'s iOS cmake with Android's would let
`GDAL_LIBS` drop back to `gdal` and would rewrite **Extension modules**, **App size** and the
whole cross-extension question at once.

`requirements.host`'s `openssl >=3.0.15` is a build-time-only input: `build.py` promotes only
`flet-*` host requirements into `Requires-Dist`, so it never reaches a device, and it exists
purely because `GDAL_LIBS` names `ssl` and `crypto`.

### Upgrade hazards

The version pin in `meta.yaml` is exact for a reason — the bindings hard-require a
major.minor match with libgdal. Bump the two together and re-read the consumer claims off the
built wheels.

**The single-table property is the whole iOS argument, and upstream can retire it silently.**
`PyInit__gdal` calling `GDALAllRegister`, and `osgeo/gdal.py` containing no reference to
`_ogr`, `_osr`, `_gnm`, `_gdal_array` or `_gdalconst`, are what keep the raster path inside
one image. Upstream moving one function to a different SWIG module would break iOS the way
`rasterio` and `pyogrio` are broken, with no build error.

The import graph moves on any bindings release too: four-modules-on-import and
six-after-`UseExceptions()` are upstream source behaviour, not ours.

### Re-verification checklist

- **That nothing in the wheel reads a file from its own installation.** This is what keeps
  gdal off `extract_packages` on Android, where site-packages is a zip: the wheel ships no
  non-code data files at all, and the single `__file__` in `osgeo/__init__.py` is
  `basename(dirname(__file__))` deriving a module name for `swig_import_helper`, never a path
  to open. A bump that starts shipping a data file — a `drivers.ini`, a PROJ or GDAL data
  tree — or that opens one relative to `__file__` turns that into a
  `NotADirectoryError` on Android and nothing anywhere else. Re-check both on every bump:
  `unzip -l` the wheel for non-`.py`/`.so` entries, and grep `osgeo/` for `__file__`.

A green build establishes almost none of what this page claims.

- **The linkage split.** Android: `DT_NEEDED` still naming `libgdal.so` by bare soname,
  `libc++_shared.so` on exactly five of six extensions, `libgdal.so` still *not* naming
  `libc++_shared.so` itself, the libproj chain intact, and 16 KB `PT_LOAD` alignment
  everywhere. Note where the requirement actually comes
  from: `libgdal.so` does not name `libc++_shared.so` at all, and gets its C++ symbols from
  `libproj.so`, which statically links libc++. It is gdal's own SWIG extensions — `_gdal`,
  `_ogr`, `_osr` and `_gnm` — that each name `libc++_shared.so` directly, which is why
  dropping the wheel fails at `dlopen` of an extension rather than at anything GDAL-shaped. iOS: still six `MH_DYLIB`, still
  exactly five carrying GDAL, `otool -L` naming no libcurl/libtiff/libproj, `otool -hv` still
  `TWOLEVEL`, `nm -u` still finding no undefined GDAL/PROJ symbol.
- **The single-table property.** `otool -tV` on the iOS `_gdal` for `PyInit__gdal` →
  `GDALAllRegister`, and a grep of `osgeo/gdal.py` for the other five extension names.
- **The import graph.** Re-run it against the new `osgeo/*.py`: run the wheel's Python half
  with the six extensions replaced by recording stubs.
- **The driver set**, two independent ways: `otool -tV` on the iOS `_gdal` shows
  `GDALAllRegister` branching to exactly `GDALRegister_GTiff`, `_COG`, `_VRT`, `_MEM`,
  `GNMRegisterAllInternal` and `OGRRegisterAllInternal`; Android's `libgdal.so` dynamic symbol
  table defines the same eleven. That library is stripped, so go by dynamic symbols, not `nm`.
- **The codec set**, as `strings -a <file> | grep -c <marker>`. In the iOS `_gdal`:
  `LZWDecode` 7, `ZIPDecode` 3, `JPEGDecode` 7, `PackBitsDecode` 3, `LERCDecode` 1, and
  `ZSTDDecode`/`WebPDecode`/`LZMADecode` all 0; Android's `libgdal.so` gives 5 / 2 / 4 / 2 / 1
  and the same three zeros. `nm` on the iOS `_gdal` should still find the OJPEG, PixarLog,
  SGILog, ThunderScan, NeXT, DumpMode and four CCITT libtiff initialisers, and no `ZSTD`,
  `WebP` or `LZMA` one.
- **The `proj.db`/`GDAL_DATA` gap.** `unzip -l` on the gdal and `flet-libgdal` wheels should
  still match nothing under `proj.db`, `gdal_data`, `proj_data` or `share/` — both native
  recipes end their build with `rm -rf $PREFIX/{bin,share}`. If that changes, **Coordinate
  systems** needs rewriting, not relaxing.
- **The sizes**, re-measured rather than adjusted by eye; the iOS totals are the whole
  argument for budgeting 126 MB. Decimal units — `du -h` will disagree.
- **The example is the live regression test.** A bump means bumping
  [`geotiff-roundtrip`](examples/geotiff-roundtrip)'s `gdal==` pin and rebuilding on both
  platforms; its panels are one-to-one with the claims above.

### Coverage gaps

**The iOS argument has now run on a device — once.** On an iPhone 16 simulator on
2026-08-25 the [`geotiff-roundtrip`](examples/geotiff-roundtrip) example reported
`GDAL 3.13.1 - PROJ 9.5.0 - ios`, wrote and re-read a 512x512 float32 GeoTIFF through the
GTiff driver with **0 of 262,144 elements differing** (worst residual `0.000e+00`), did the
same for a 256x256 windowed read, handed the band to `_gdal_array` as a numpy float32
(512, 512) with 0 differing, round-tripped a proj4 string through `_osr` as identical, and
re-read 3 features through `_ogr` with names matching. That is the cross-extension handoff
this page argues for, on hardware, and it is what makes `rasterio` and `pyogrio` pointing
here more than a guess.

What that run does **not** cover: the five-copies-of-GDAL reading is still derived from the
binaries, and `EPSG:4326` failed on the same screen with
`RuntimeError: PROJ: proj_create_from_database: Cannot find proj.db` — so the recommendation
holds for raster and vector I/O with proj-strings, and not for authority-named CRSs.

`tests/test_gdal.py` cannot catch the thing this page is about: both tests stay inside `_gdal`
and inside the `MEM` driver, so a broken GeoTIFF-on-disk path, a broken `osr` or `ogr`
handoff, or a vanished driver would all pass CI green. Worth adding: an assertion over the
exact eleven driver short names (so a driver *appearing* is as red as one disappearing), a
GTiff write-read-compare in `tmp_path`, an `osr` round trip through `SetFromUserInput`, and an
assertion that `ImportFromEPSG(4326)` fails. That pins the boundary this page documents.

Untested anywhere: `SetPROJSearchPath` with a supplied `proj.db`, `OF_THREAD_SAFE` on device,
`gdal_array.SaveArray`, the `COG` and `VRT` drivers, and every network-drivers path.
