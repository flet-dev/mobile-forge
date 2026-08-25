# rasterio

[`rasterio`](https://rasterio.readthedocs.io/en/stable/) reads and writes geospatial rasters
as numpy arrays: open a GeoTIFF, ask for a
[`Window`](https://rasterio.readthedocs.io/en/stable/api/rasterio.windows.html#rasterio.windows.Window)
of it, get an `ndarray` back. That window is why it is worth having on a phone — it lets an
app touch a raster far larger than its RAM, and on a 4096×4096 float32 surface it is the
difference between 1.3 MB of resident memory and 134 MB for the same file (host figures).
Everything happens in-process with no network, because these wheels are a deliberately small
GDAL: four raster drivers, no PROJ database, no libcurl.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "rasterio",
]
```

rasterio needs **Python 3.12 or newer**, so the app's `requires-python` has to be at least
`>=3.12`. Set it lower and `uv` fails the resolve for the lower splits rather than falling
back to an older rasterio.

**Treat this as Android-only. The iOS wheels build, install and import, and then cannot open
a raster.** Registering drivers and doing the I/O happen in two different extension modules,
and each iOS extension links its own copy of GDAL, so the driver table one of them fills in is
invisible to the other. In a process that has just listed `GTiff` among its eleven registered
drivers, `rasterio.open(path, "w", driver="GTiff")` raises
`DriverRegistrationError: ('No such driver registered: %s', b'GTiff')`, and a windowed read of
an existing file raises `SystemError: Unknown GDAL Error`; entering an explicit
`rasterio.Env()` around the call changes nothing. Fixing it means relinking the iOS slices,
not changing anything in your app. Measured 2026-08-19 with the
[`elevation-tile`](examples/elevation-tile) example: the same app wrote and read back a
1024×1024 GeoTIFF on an arm64 Android emulator with 0 of 1,048,576 pixels differing, and
failed both operations on an iPhone simulator. If the project also builds for iOS, move
rasterio out of `[project] dependencies` into
[`[tool.flet.android] dependencies`](https://flet.dev/docs/publish/#app-dependencies) so the
iOS app does not ship a package it cannot use, and guard the import.

For raster I/O on iOS use [`gdal`](../gdal), GDAL's own SWIG bindings against the same
libraries. It binds every native call to a single extension whose module init registers the
drivers, so the split that breaks rasterio has nowhere to open. Measured on an iPhone 16
simulator on 2026-08-25: [`gdal`](../gdal)'s own example wrote and re-read a 512×512 float32
GeoTIFF through the GTiff driver with 0 of 262,144 elements differing, and handed the band on
to `_gdal_array`, `_osr` and `_ogr` intact. Note the one thing that does not survive the move:
an authority-named CRS still fails, since the chain ships no `proj.db` — spell CRSs as
proj-strings.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`elevation-tile`](examples/elevation-tile) — a GeoTIFF written to app storage, then read
  back and differenced against the array it came from.

## Usage in a Flet app

Write with an explicit driver, read a window, put the result on screen:

```python
import os
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.windows import Window

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "elevation.tif")

with rasterio.Env(), rasterio.open(
    path,
    "w",
    driver="GTiff",  # name it: extension sniffing is a registry lookup
    height=1024, width=1024, count=1, dtype="float32",
    crs=CRS.from_string("+proj=longlat +datum=WGS84 +no_defs"),  # not "EPSG:4326"
    transform=from_origin(10.0, 60.0, 0.0005, 0.0005),
    tiled=True, blockxsize=256, blockysize=256,
    compress="DEFLATE", predictor=3,
) as dst:
    dst.write(elevation, 1)

with rasterio.Env(), rasterio.open(path) as ds:
    patch = ds.read(1, window=Window(384, 384, 256, 256))

page.add(ft.Text(f"{patch.mean():.1f} m over {patch.shape}"))
```

`patch` is an ordinary `ndarray`, and that is as close to the screen as these wheels get on
their own: GTiff is the only image format they can write, while
[`ft.Image`](https://flet.dev/docs/controls/image/#flet.Image.src) wants PNG or JPEG bytes.
Either report numbers off the array, which is what the example does, or hand it to
[`pillow`](../pillow) or [`opencv-python`](../opencv-python) to encode.

### Storage

Rasters belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, durable, included in backups, and from Flet 0.86.0 also the process working
directory on device. It has to be a **writable** directory rather than a bundled
[asset](https://flet.dev/docs/cookbook/assets), because GDAL writes beside the raster:
[`ds.stats(indexes=1, approx=False)`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.stats)
on a 128×128 GeoTIFF left a 351-byte `s.tif.aux.xml` next to it, and
[`build_overviews`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetWriter.build_overviews)
needs `r+` on the file itself. Copy a shipped raster out of assets before opening it for
anything but a plain read.

Avoid
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it) and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for anything you want to keep.

### Coordinate systems

**Write a CRS as a `+proj=` string or WKT, not as an EPSG code.** Nothing in this chain ships
a PROJ database: neither the rasterio wheels nor `flet-libgdal` carry a `proj.db` or a GDAL
data directory, on either platform, because both native recipes end their build by deleting
`$PREFIX/share`. [`pyproj`](../pyproj) has the same gap for the same reason.

Unlike pyproj, which gates every `CRS`, `Proj` and `Transformer` call behind a Python-level
check, rasterio has no such gate, so only *authority-database lookups* fail.
`CRS.from_string("+proj=longlat +datum=WGS84 +no_defs")`, `+proj=utm +zone=33 …` and
`CRS.from_wkt(…)` all work, and a GeoTIFF written with one keeps its CRS through a read back.
[`CRS.from_epsg(4326)`](https://rasterio.readthedocs.io/en/stable/api/rasterio.crs.html#rasterio.crs.CRS.from_epsg)
raises `rasterio.errors.CRSError: The EPSG code is unknown. PROJ:
internal_proj_create_from_database: Cannot find proj.db`, and so do
`CRS.from_string("EPSG:3857")`, `rasterio.open(…, crs="EPSG:4326")` and any
[`rasterio.warp`](https://rasterio.readthedocs.io/en/stable/api/rasterio.warp.html) call
between two EPSG codes; `crs.to_epsg()` comes back `None` on a proj-string CRS, because
identifying it against the authority database is exactly what cannot happen. The import itself
succeeds, printing one line to stderr:
`Warning 3: Cannot find gdalvrt.xsd (GDAL_DATA is not defined)`.

Georeferencing is unaffected. `ds.index`, `ds.sample` and `ds.bounds` are the affine transform
rather than the CRS, so a longitude/latitude pair still resolves to a row, a column and a pixel
value with no database anywhere.

**To get EPSG codes back, ship `proj.db` as an asset** and point rasterio's search path at the
directory holding it.
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir) is
where a bundled `src/assets/` lands on device, and there is no import-time-only window — this
works at any point after `import rasterio`:

```python
rasterio._env.set_proj_data_search_path(
    os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "proj")
)
```

Verified with no data at all in the process, `CRS.from_epsg(4326)` raised before that call and
returned `EPSG:4326` after it. `rasterio/env.py` also honours `PROJ_DATA` and `PROJ_LIB` from
`os.environ` on the way through the import, if you would rather set an environment variable.

Take the database from `pyproj`'s wheel: about 9.3 MB, declaring database layout 1.4, which is
exactly what the PROJ 9.5.0 in this chain expects. `rasterio==1.5.0`'s own macOS wheel carries
a larger one — about 9.6 MB, PROJ 9.7.1, layout 1.6 — which the gate should also accept, since
PROJ wants the major to match and the minor to be at least what it expects, but that pairing
has never been run on a device. Do not substitute an empty file: pyproj unlocks its API from a
zero-byte stub because its gate only checks that the name exists, whereas here a stub turns the
plain *Cannot find proj.db* into `SQLite error [ no such table: metadata ]` and buys nothing.

**Or ship no database at all.** Write CRSes as `+proj=` strings or WKT and nothing needs one —
that is what the [`elevation-tile`](examples/elevation-tile) example does, at zero bytes of
payload. What you give up is discovery: you have to know the projection parameters, and
`to_epsg()` will not name them for you.

### Threading

**Never share a default dataset handle between threads. It does not raise — it kills the
process.** Eight threads doing overlapping 1024×1024 reads on a single `rasterio.open` result
terminated the interpreter with SIGBUS on four of five runs; the fifth survived with a
`RasterioIOError: Read failed` and two arrays of wrong data. Under
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — which
submits to a shared pool, so two taps really do overlap — that is a native crash with no Python
traceback anywhere. Three arrangements were clean:

- **One `rasterio.open` per thread** — 40 of 40 calls on each of three runs. What the example
  does, and the simplest rule.
- **A `threading.Lock` around the whole read**, including consuming the array it returns —
  40 of 40 on each of three runs.
- **`rasterio.open(path, thread_safe=True)`**, new in 1.5.0 — it sets GDAL's
  `GDAL_OF_THREAD_SAFE` open flag, so one handle really can be shared: 12 of 12 clean runs of
  the same eight-thread overlap that crashed a default handle. **Mode `"r"` only, and silently
  so** — `rasterio.open` forwards `thread_safe` to `DatasetReader` and drops it for `"r+"` and
  `"w"` without a word, so a writer handle accepts the keyword and is an ordinary unguarded
  dataset.

[`rasterio.Env()`](https://rasterio.readthedocs.io/en/stable/api/rasterio.env.html#rasterio.env.Env)
is thread-local by design, so enter one **inside** each worker rather than relying on one
entered on the UI thread. The standing Flet caveats apply on top: `run_thread` never retrieves
the worker's future, so an exception inside one surfaces nowhere — wrap the body — and
auto-update does not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Windows and memory

**Windowed reads are the whole point on a phone.** On a 4096×4096 float32 surface tiled 256×256
with DEFLATE and `predictor=3` — about 33 MB on disk, 67 MB as an array — a
[`Window(1000, 1000, 256, 256)`](https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html)
read cost 3 ms and 1.3 MB of resident memory while `ds.read(1)` cost 195 ms and 134 MB. The
memory figures are the structural ones — the window allocates its 256 KB, the full read
allocates the whole band and a decode buffer beside it — while the times are host numbers
(macOS arm64, GDAL 3.12.1) that track how compressible the data is rather than the pixel
count. Measure on device before budgeting.

Tile the file when you intend to window it — `tiled=True` with `blockxsize`/`blockysize` —
after which `ds.block_shapes` and `ds.block_windows` walk it a block at a time. Internal
overviews work too: `build_overviews([2, 4], Resampling.average)` on a dataset opened `r+`
wrote them *inside* the file, with no `.ovr` sidecar.

### App size

On Android the wheel is roughly 4.2–4.4 MB compressed, but the shared GDAL chain behind it is
the real payload: about **25 MB of native libraries per ABI on arm64-v8a** — 17 MB on
armeabi-v7a, 27 MB on x86_64 — of which only about 3.4 MB is rasterio's own extensions. Use an
app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI, and leave Flet's default
[compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) on: roughly
20 MB of every unpacked wheel is Cython-generated `.c`/`.cpp` source that cleanup removes, and
nothing in the package reads its own source, so compiling to `.pyc` is safe.

iOS is in a different league and there is nothing to configure. Each wheel is about 95–105 MB
compressed and about 260 MB unpacked after cleanup, because ten of the fifteen extensions carry
their own static copy of GDAL. A build downloads three of those plus three `flet-libgdal`
wheels of about 113 MB each, every one of which unpacks a half-gigabyte archive that is then
deleted — expect a slow first build and plenty of free disk. Since those wheels cannot open a
raster anyway, keeping rasterio out of the iOS dependency list is what actually saves the
space.

### Other considerations

**Your desktop is not a preview of the device, and the gap is enormous.** `flet run` resolves
rasterio from PyPI, whose macOS wheel bundles its own GDAL data directory (about 2 MB) and PROJ
database (about 10 MB) and registers 44 raster drivers across 59 extensions, against four on
the mobile build. EPSG codes, PNG, netCDF and `compress="ZSTD"` all work on your Mac and fail
on the phone. Reproduce the device shape locally by renaming
`site-packages/rasterio/gdal_data` and `.../proj_data` aside — that is how the CRS findings
above were established — and validate on a device or emulator before shipping.

## Things to know

- **Four raster drivers, eleven in the whole registry.** `GTiff`, `COG`, `MEM` and `VRT` for
  raster, the five OGR vector drivers `ESRIJSON`, `GeoJSON`, `GeoJSONSeq`, `ESRI Shapefile` and
  `TopoJSON`, and the two GNM network ones. No PNG, JPEG, HFA, netCDF, GRIB, JP2 or HDF —
  `flet-libgdal` is built with the optional drivers off. Ask the live registry on device rather
  than guessing, and ask it through
  [`rasterio.Env`](https://rasterio.readthedocs.io/en/stable/api/rasterio.env.html#rasterio.env.Env):
  `with rasterio.Env() as env: env.drivers()` returns the whole short-name → long-name map,
  147 entries on a desktop and those eleven on device.
  [`raster_driver_extensions()`](https://rasterio.readthedocs.io/en/stable/api/rasterio.drivers.html#rasterio.drivers.raster_driver_extensions)
  answers a narrower question — which *file extension* maps to which driver — and lists neither
  `MEM` nor `COG` even on a desktop, so it under-reports what you can write.

- **Each way of hitting an unsupported format fails differently.** `rasterio.open(p, "w",
  driver="PNG")` raises `DriverRegistrationError: ('No such driver registered: %s', b'PNG')`;
  `rasterio.drivers.driver_from_extension("x.png")` raises `ValueError: Unable to detect
  driver. Please specify driver.`, because it is a lookup in the same registry-derived
  extension map; opening an unrecognised file raises `RasterioIOError: '<path>' not recognized
  as being in a supported file format.` Pass `driver="GTiff"` (or `COG`) explicitly instead of
  relying on extension sniffing, convert other formats off device, and use
  [`pillow`](../pillow) or [`opencv-python`](../opencv-python) to decode a PNG or JPEG on a
  phone.

- **The GTiff `COMPRESS` option list inside the binary lies.** It advertises `ZSTD`, `WEBP` and
  `LZMA` with matching level options, because GDAL compiles those XML literals in
  unconditionally and builds the real list at runtime from the codecs libtiff was actually
  linked with — here LZW, Deflate, PackBits, JPEG, LERC, PixarLog, SGILog, ThunderScan, NeXT
  and the CCITT family. Neither platform's binary carries a `ZSTD_compress`, `WebPEncode` or
  `lzma_code` symbol, so those three fail at write time. Make
  [`compress="DEFLATE"`](https://gdal.org/en/stable/drivers/raster/gtiff.html#creation-options)
  the default (with `predictor=2` for integers, `3` for floats), `LZW` or `PACKBITS` where
  speed matters, `LERC`/`LERC_DEFLATE` for lossy float elevation.

- **GDAL is compiled without libcurl, so rasterio on device is strictly offline.** `/vsicurl/`,
  `/vsis3/`, `/vsigs/`, `/vsiaz/` and `rasterio.session`'s AWS/GS/Azure support are dead on
  both platforms — including iOS, where libcurl objects *are* linked into the extensions and
  GDAL simply never calls them. Both binaries carry GDAL's fallback diagnostic, *"GDAL/OGR not
  compiled with libcurl support, remote requests not supported."* Fetch a raster with an HTTP
  client and open the local file.

- **`ds.crs == crs_you_wrote` is `False` after a GeoTIFF round trip**, with or without a PROJ
  database. The GeoTIFF keys normalise the WKT, so a semantically identical CRS compares
  unequal while `to_dict()` on both gives `{'proj': 'longlat', 'datum': 'WGS84', 'no_defs':
  True}`. Compare `crs.to_dict()`, or `to_epsg()` when a database is available, not `==`.

- **`rasterio.show_versions()` prints its header and then raises**
  `AttributeError: module 'importlib' has no attribute 'metadata'` — an upstream bug in 1.5.0,
  not a build artefact: it does `import importlib` and then calls `importlib.metadata.version`,
  which only survives if something else in the process imported `importlib.metadata` first, and
  importing `flet` does not. Do that import yourself, or build a header from
  `rasterio.__version__`, `__gdal_version__` and `__proj_version__`, which work with no data at
  all.

- **`ds.stats(approx=False)` returns a cached number once an `.aux.xml` exists, and the cache
  is coarser than the computation.** On a 1024×1024 float32 surface the first call agreed with
  a float64 numpy pass to 1.4e-13 and a second call on the same file only to 4.3e-12, because
  GDAL then reads the sidecar it wrote and the sidecar stores 14 significant digits. Re-opening
  in `"w"` deletes the sidecar, so a writer that rewrites the file each run — as the example
  does — always shows the computed figure. Quote which one you mean, and do not assert a
  tolerance tighter than 1e-11 without knowing whether a sidecar was there.

- **GEOS is not compiled in**, so OGR geometry predicates and operations are unavailable. Not a
  mobile-only limitation: rasterio's own PyPI wheels report `__geos_version__` as `'0.0.0'`
  too, and [`rasterio.features`](https://rasterio.readthedocs.io/en/stable/api/rasterio.features.html)
  and [`rasterio.mask`](https://rasterio.readthedocs.io/en/stable/api/rasterio.mask.html) work
  anyway — they want GeoJSON-shaped dicts, not GEOS geometries. Use [`shapely`](../shapely) if
  you need real geometry operations.

## Build notes (maintainers)

### Recipe shape

Two recipes: `flet-libgdal` builds GDAL, this one consumes it. `patches/mobile.patch` explains
its own hunk and `meta.yaml` comments its `script_env` next to it, so what is left here is
shape and the bump checklist.

**Everything this page warns about is a `flet-libgdal` decision, not a rasterio one.** The
eleven-driver registry comes from `-DGDAL_BUILD_OPTIONAL_DRIVERS=OFF` /
`-DOGR_BUILD_OPTIONAL_DRIVERS=OFF`; the missing `GDAL_DATA` and `proj.db` come from
`rm -rf $PREFIX/{bin,share}` in `flet-libgdal/build.sh` and `flet-libproj/build.sh`; the absent
libcurl comes from `-DGDAL_USE_CURL=OFF` on Android and `-DGDAL_USE_EXTERNAL_LIBS=OFF` on iOS.
A `flet-libgdal` bump can therefore invalidate most of this README without the rasterio recipe
changing a line.

**The linkage split is the whole iOS story.** On Android all fifteen extensions name exactly
`libm.so`, `libgdal.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` in `DT_NEEDED`, plus
`libc++_shared.so` on `_warp`, `_filepath` and `_fill`, with no `RUNPATH` or `RPATH` anywhere.
`libgdal.so` carries `SONAME libgdal.so`, so serious_python's flattening of every wheel `.so`
into `jniLibs/<abi>/` is enough for the loader to resolve it, and every `LOAD` segment reports
`align 0x4000`. Further down the closure `libproj.so` names `libsqlite3_python.so`,
`libtiff.so` and `libcurl.so`, and `libcurl.so` names `libpsl.so`, `libssl_python.so` and
`libcrypto_python.so` — three of those come from Flet's Python bundle rather than from this
chain. Sizes on cp314, in bytes: arm64-v8a 3,356,840 of rasterio extension against 13,997,320
of `libgdal.so` and 7,513,872 of PROJ chain; armeabi-v7a 2,242,516 / 9,702,048 / 5,227,468;
x86_64 3,352,952 / 15,283,480 / 8,347,680.

On iOS `flet-libgdal` ships a 524,528,736-byte `libgdal.a` and no shared library, and the link
pulls it into every extension that touches GDAL: `_base`, `_env`, `_features`, `_fill`, `_io`,
`_transform`, `_version`, `_warp`, `crs` and `shutil` each carry their own `GDAL 3.13.1`
version string and weigh 25.3–26.1 MB, for 259,746,200 bytes of extension on the device slice
against 3,356,840 on Android arm64-v8a. The symbol tables say what that costs: on iOS `_env`,
`_io`, `_base` and `_features` each *define* `GDALRegister_GTiff` and import it from nobody, so
each carries its own copy of GDAL's global driver table, while on Android `_env` imports
`GDALAllRegister` as an undefined symbol resolved at load. `rasterio.Env()` registers into
`_env`; `rasterio.open` resolves the name in `_io`. One table on Android, ten on iOS — that is
the Install warning, and it is why an explicit `Env()` does not help.

`GDAL_LIBS` solves a *load* failure, not that *table* split: naming GDAL's static dependency
chain stops dyld aborting on an unresolved `_geod_init` at import and does nothing about the
registries. All fifteen iOS extensions are `MH_DYLIB`, so forge's `MH_BUNDLE` conversion has
nothing to do, and `otool -L` on each lists only its own install name,
`@rpath/Python.framework/Python`, `/usr/lib/libsqlite3.dylib`, `/usr/lib/libz.1.dylib` and
`/usr/lib/libSystem.B.dylib`, plus `/usr/lib/libc++.1.dylib` on the same three that need
`libc++_shared` on Android. Building `flet-libgdal` as a shared library for iOS the way Android
already has it would let `GDAL_LIBS` drop back to `gdal`, close the registry split, and turn a
~260 MB payload back into Android's ~18 MB at once. That is the fix; there is no consumer-side
workaround, and `gdal` is the interim answer only because its `_gdal` extension registers from
its own module init.

Two smaller platform differences worth knowing. Android's `libproj.so` links
`libsqlite3_python.so` from Flet's Python bundle while iOS binds the system
`/usr/lib/libsqlite3.dylib`, so whichever `proj.db` a consumer supplies is opened by a
different SQLite on each platform. And `flet-libgdal`'s `gdalplugins/drivers.ini` is **not** a
capability list: it is a 2,787-byte ordering table naming 251 drivers, installed
unconditionally, whose own header says it keeps in sync with `gdalallregister.cpp` — reading it
as what was compiled in over-counts the registry twenty-three-fold. On Android it never reaches
the device at all, because serious_python copies a `flet-lib*` `opt/` tree into `jniLibs` with
a `**/*.so` glob and drops every non-library file.

### Upgrade hazards

- **Bump `flet-libgdal` and rasterio together, and re-read the consumer claims off the built
  wheels.** The driver set, the codec set, the missing PROJ database and the absent libcurl are
  all decided there, and none of them turns a build red.
- **The build is steered entirely through the environment branch the patch adds** —
  `GDAL_INCLUDE_PATH`, `GDAL_LIB_PATH`, `GDAL_LIBS` — which exists only because upstream still
  uses `setup.py`. A move to meson or scikit-build-core retires both the patch and the
  `script_env` block at once: treat that release as a redesign, not a bump.
- **A python-build bump that renames `libsqlite3_python.so`, `libssl_python.so` or
  `libcrypto_python.so`** turns `import rasterio` into a `dlopen failed` on Android, because the
  PROJ and curl libraries name them directly. Walk the `DT_NEEDED` closure after one.
- **The build number has to keep outranking the published wheel.** pip picks the higher build
  tag when name and version collide, so a rebuild against a newer `flet-libgdal` that reuses a
  lower number is silently ignored downstream and the chain bump becomes invisible.

### Re-verification checklist

- **The wheel layout.** Every extension filename must still carry the ABI tag its own runtime
  matches on, and the wheel must still contain no data file of any kind — that is what keeps an
  `extract_packages` entry unnecessary and what the Install section quietly depends on.
- **The driver set and the codec set**, from the symbol tables on both platforms. Android's
  `libgdal.so` is stripped, so cross-check by dynamic symbols and codec marker strings rather
  than by `nm`.
- **The linkage split.** Android: `DT_NEEDED` still naming `libgdal.so` by bare soname,
  `libc++_shared.so` on exactly `_warp`/`_filepath`/`_fill`, the libproj chain intact, and
  16 KB `PT_LOAD` alignment everywhere. iOS: still fifteen `MH_DYLIB`, still exactly ten
  carrying GDAL, `otool -L` still naming no libcurl, libtiff or libproj. If iOS ever links
  dynamically, the Install warning and every size figure on this page change.
- **The threading crash.** SIGBUS on a shared dataset handle is GDAL's behaviour, not
  rasterio's, so a GDAL bump can move it in either direction.
- **The sizes and timings are measured.** Re-measure from byte counts rather than adjusting by
  eye or reading `du -h`, which is binary; the iOS total in particular is the whole argument
  for budgeting a quarter of a gigabyte.

### Coverage gaps

- **`tests/test_rasterio.py` asserts far less than it appears to.** `test_gdal_version` is a
  genuine canary for the `GDAL_LIBS` chain. `test_drivers_listed` is not: `is_blacklisted` is
  `return mode in blacklist.get(name, ())`, a pure-Python dict lookup with no `@ensure_env`
  decorator, so only the *import* of `rasterio.drivers` touches native code and the registry
  itself is untested. **The suite therefore passes on iOS while no raster can be opened
  there.** Replace it with an assertion over `rasterio.Env().drivers()` inside its context —
  the exact eleven keys, so a driver appearing is as red as one vanishing — a
  write-read-compare of a real GeoTIFF, and an assertion that `CRS.from_epsg(4326)` raises
  `CRSError`.
- **The threading results record no platform.** Nothing here says where the SIGBUS runs were
  made, nothing in CI exercises concurrency, and the example is written to avoid it. Say where
  when you re-run them.
- **Neither `proj.db` pairing has been run on a device.** The layout-1.4 and layout-1.6
  reasoning in **Coordinate systems** is host reasoning; record the result if someone tries it
  on a phone.
- Nothing on device covers overviews, the `.aux.xml` sidecar, `/vsimem`, `rasterio.warp`, or a
  raster larger than the 1024×1024 the example writes.
