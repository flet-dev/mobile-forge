# gdal

[GDAL](https://gdal.org/)'s own Python bindings — `osgeo.gdal`, `osgeo.ogr`, `osgeo.osr` —
the raster and vector engine that sits underneath most of the geospatial stack, with the
thin SWIG wrapper the C++ API was designed around. On a phone that buys you a GeoTIFF
round trip, windowed reads out of a raster far larger than RAM, and GeoJSON or Shapefile
I/O, entirely in-process and with no network. [`rasterio`](../rasterio) wraps the same
`flet-libgdal` with an `ndarray`-shaped API and is the friendlier one on Android, but it
cannot open a raster on iOS at all — for a reason that, structurally, does not apply here;
see [iOS notes](#ios-notes).

These wheels are a deliberately small GDAL: **eleven drivers**, no `proj.db`, no
`GDAL_DATA`, no libcurl, no GEOS. None of that announces itself at import.

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

**The platform tables are not a style choice here either, and the reason differs from
[`psutil`](../psutil)'s.** gdal is not platform-exclusive — both mobile platforms have wheels
on the index — but **upstream publishes no wheel for any desktop**: PyPI carries exactly one
file for 3.13.1, `gdal-3.13.1.tar.gz`, and building it needs a system libgdal and
`gdal-config`. Flet
[appends](https://flet.dev/docs/publish/#app-dependencies) `[tool.flet.<platform>].dependencies`
to the project list rather than replacing it, so a top-level `"gdal"` is also handed to the
host resolve that `flet build` performs first — which tries the sdist and stops the whole
build with `Call to setuptools.build_meta.build_wheel failed`, before it ever reaches a
device. Measured 2026-08-19: that failure hit `flet build apk` and `flet build ios-simulator`
alike until the entry moved into the two tables above.

The cost is the same one psutil's page states: **gdal is then absent from `flet run` on your
desktop**, because nothing outside a `flet build` for that platform reads those tables. Guard
the import so a desktop or web run explains itself instead of raising — the
[`geotiff-roundtrip`](examples/geotiff-roundtrip) example does exactly that, and renders a
card naming the missing module rather than a crash screen.

**`numpy` is an optional extra, not a dependency.** The wheel declares
`Provides-Extra: numpy` and `Requires-Dist: numpy>1.0.0; extra == "numpy"`, so a bare
`"gdal"` installs no numpy and `band.ReadAsArray()` then dies with
`ModuleNotFoundError: No module named 'numpy'` at the point of use rather than at import
(`osgeo/gdal.py` reaches `from osgeo import gdal_array` unguarded, and `osgeo/gdal_array.py`
does a bare `import numpy`). Write `"gdal[numpy]"`, or add `"numpy"` alongside it, if you
want the array API. Note that numpy raises your own `requires-python` floor — 2.4.6 needs
`>=3.11`, and `uv` fails the resolve for the lower splits otherwise.

Nothing else to configure: no
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry, and no loader shim. All 127 entries in the wheel are nine `osgeo/*.py`, 89
`osgeo_utils/**.py`, six `.so`, 18 console-script shims under `gdal-3.13.1.data/scripts/`
and five `dist-info` files — **no data file of any kind**, on either platform. Every
extension filename carries the ABI tag the import machinery matches on:
`_gdal.cpython-314-aarch64-linux-android.so` and its 3.13 twin on Android, the bare
`_gdal.cpython-312.so` on Android 3.12 (the tag Flet's own 3.12 build uses),
`_gdal.cpython-314-iphoneos.so` and friends on iOS.

The native chain comes along without configuring. The recipe pins **`flet-libgdal`** on
both platforms, plus **`flet-libcpp-shared`** on Android and **`flet-libjpeg`** on iOS;
`flet-libgdal` requires **`flet-libproj`** (PROJ 9.5.0), which requires **`flet-libtiff`**
and **`flet-libcurl`**, which require **`flet-libjpeg`** and **`flet-libpsl`** in turn.
Only Android loads any of them at runtime — see [Android notes](#android-notes) and
[iOS notes](#ios-notes).

Nineteen wheels at the same build number: Python 3.12, 3.13 and 3.14 × three Android ABIs
(arm64-v8a, armeabi-v7a, x86_64) and three iOS slices (device, arm64 simulator, x86_64
simulator), plus a legacy 32-bit `android_24_x86` slice on 3.12. No arch is excluded.
`Requires-Python` is `>=3.8.0`, so gdal itself imposes no floor on your app.

Leave Flet's default
[compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) on:
2,182,268 bytes of the payload is `.py`, of which 1,325,117 is `osgeo_utils/` — command-line
tools nothing in the package imports, 797,317 bytes of it `osgeo_utils/samples/`. Nothing
here reads its own source, so compiling to `.pyc` is safe.

## Storage

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

### No `proj.db` and no `GDAL_DATA`, on either platform

`unzip -l` on both gdal wheels and both `flet-libgdal` wheels finds zero entries matching
`proj.db`, `gdal_data`, `proj_data` or `share/` — the single grep hit is the header
`opt/include/gdal_dataset.h`. Both `flet-libgdal` wheels are 102 headers plus one library
(`opt/lib/libgdal.so` on Android, `opt/lib/libgdal.a` on iOS) plus
`opt/lib/gdalplugins/drivers.ini`. The diagnostics for the gap are compiled
into the shipped binaries: `Cannot find proj.db` appears in every iOS extension except
`_gdalconst` and in Android's `libproj.so`, and `Cannot find %s (GDAL_DATA is not defined)`
in the iOS `_gdal` and in Android's `libgdal.so`.

This is the same gap [`pyproj`](../pyproj#storage) and [`rasterio`](../rasterio#storage)
document, reached the same way — both native recipes end their build with
`rm -rf $PREFIX/{bin,share}` — and it has the same consequence: **anything that names an
authority cannot resolve.**
[`SpatialReference.ImportFromEPSG(4326)`](https://gdal.org/en/stable/api/python/spatial_ref_api.html#osgeo.osr.SpatialReference.ImportFromEPSG)
is the call to expect trouble from; a CRS given as a proj-string or WKT through
[`SetFromUserInput`](https://gdal.org/en/stable/api/python/spatial_ref_api.html#osgeo.osr.SpatialReference.SetFromUserInput)
needs no database at all. The [`geotiff-roundtrip`](examples/geotiff-roundtrip) example
builds its CRS that way and runs the EPSG call anyway, so the difference shows on the device
rather than being asserted here.

If you need EPSG codes, ship `proj.db` as an asset and point PROJ at the directory holding
it — `osgeo/osr.py` exposes `SetPROJSearchPath(path)` and `SetPROJSearchPaths([path])`
(both present in the shipped wheel), and PROJ's own `PROJ_DATA`/`PROJ_LIB` environment
variables are compiled into `libproj.so`. **None of those routes has been run on a device
for this recipe.** [`rasterio`](../rasterio#getting-epsg-codes-back) and
[`pyproj`](../pyproj#storage) work through the same problem in more detail, including which
`proj.db` pairs with PROJ 9.5.0's expected database layout; take the pairing from there.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`geotiff-roundtrip`](examples/geotiff-roundtrip) — a GeoTIFF written to app storage and
  read back, with the `gdal_array`, `osr` and `ogr` paths measured beside it.

## Threading

**A GDAL dataset handle is not safe to use from two threads at once.** That matters more
than usual under
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), which
submits to a shared pool, so two taps really do overlap.
[`rasterio`](../rasterio#threading) measured what that costs on this same GDAL build: eight
threads doing overlapping reads on one shared handle took the interpreter down with SIGBUS
on four of five runs — a native crash with no Python traceback. Open one dataset per thread
(the simplest rule, and what the example does), or hold a `threading.Lock` around the whole
use.

GDAL's own thread-safe dataset mode is compiled in and reachable from Python:
`GDALGetThreadSafeDataset` appears in the iOS `_gdal` and in Android's `libgdal.so` symbol
data, `osgeo/gdalconst.py` defines `OF_THREAD_SAFE`, and `osgeo/gdal.py` exposes
[`Dataset.IsThreadSafe`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Dataset.IsThreadSafe)
and
[`Dataset.GetThreadSafeDataset`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Dataset.GetThreadSafeDataset).
`gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_THREAD_SAFE)` returned a dataset reporting
`IsThreadSafe(gdal.OF_RASTER) == True` on a host GDAL 3.13.0; it has not been exercised on
a device.

**There is no per-thread environment to enter, unlike rasterio.** Driver registration
happens once, in the extension's own module init — `PyInit__gdal` calls `GDALGetDriverCount`
and then `GDALAllRegister` (visible in `otool -tV` on the shipped iOS `_gdal`) — so a worker
thread can call [`gdal.Open`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Open)
with no preamble. The example's slider worker does exactly that, which is what tests it.

The standing Flet caveats apply on top: `run_thread` never retrieves the worker's future,
so an exception inside one surfaces nowhere — wrap the body — and auto-update does not
reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Android notes

**GDAL stays one shared library, and there is one driver table.** All six extensions list
`libm.so`, `libpython3.<minor>.so`, `libgdal.so`, `libdl.so` and `libc.so` in `DT_NEEDED`,
with `libc++_shared.so` on five of the six — every one but `_gdalconst`. Every GDAL symbol
they use is undefined and resolved at load: `_gdal` imports `GDALAllRegister` and
`GDALGetDriverByName`, `_ogr` imports `OGRRegisterAll`, `_gdal_array` imports
`GetGDALDriverManager`. `libgdal.so` carries `SONAME libgdal.so` and names only
`libm.so`, `libdl.so`, `libproj.so` and `libc.so`; every `PT_LOAD` segment in all of them
reports `align 0x4000`, the 16 KB page alignment Android 15 requires. Below that,
`libproj.so` names `libsqlite3_python.so`, `libtiff.so` and `libcurl.so`; `libtiff.so`
names `libjpeg.so` and `libz.so`; `libcurl.so` names `libpsl.so`, `libssl_python.so`,
`libcrypto_python.so` and `libz.so`.

**`flet-libcpp-shared` is load-bearing, and not for the reason the file list suggests.**
`libgdal.so` on arm64-v8a leaves 213 symbols undefined that `libc++_shared.so` defines —
200 Itanium-mangled `_Z…` names (112 of them `_ZNSt6__ndk1…`), ten `__cxa_*` entry points, and
`__dynamic_cast`, `__gxx_personality_v0` and `__emutls_get_address` — and does
**not** name `libc++_shared.so` in its own `DT_NEEDED`; it can only resolve them through the
extension that pulls it in, and those extensions do name it. Drop that wheel and the
failure lands at `dlopen` of `_gdal`, not at anything GDAL-shaped.

`recipes/rasterio` confirmed on a built APK that serious_python's flattening of every
wheel `.so` into `jniLibs/<abi>/` under its bare soname is enough for this chain to resolve
— same `flet-libgdal`, same sonames.

| slice (cp314) | wheel | unpacked | six `.so` | `libgdal.so` | PROJ chain |
| --- | --- | --- | --- | --- | --- |
| arm64-v8a | 1,374,152 | 5,359,714 | 3,163,704 | 13,997,320 | 7,513,872 |
| armeabi-v7a | 1,307,982 | 4,418,422 | 2,222,412 | 9,702,048 | 5,227,468 |
| x86_64 | 1,451,276 | 5,336,985 | 3,140,984 | 15,283,480 | 8,347,680 |

The PROJ-chain column is `libproj.so` + `libtiff.so` + `libcurl.so` + `libjpeg.so` +
`libturbojpeg.so` + `libpsl.so`, the same three totals
[`pyproj`](../pyproj#android-notes) tabulates; on arm64-v8a that is 4,640,656 + 744,048 +
723,712 + 589,784 + 748,184 + 67,488. Add `libc++_shared.so` (1,292,904) and the whole
native payload on arm64-v8a is **25,967,800 bytes**, most of it `libgdal.so` rather than
the bindings.

## iOS notes

**There is no shared library at all: five of the six extensions each absorb a whole GDAL.**
`flet-libgdal` ships a 524,528,736-byte `libgdal.a` and nothing else executable, and the
link pulls it into `_gdal`, `_gdal_array`, `_gnm`, `_ogr` and `_osr` — 24.3 to 26.5 MB
apiece, against 127 KB to 1.5 MB for the same five on Android. `nm -m` shows each of the
five *defining* `GetGDALDriverManager`, `GDALGetDriverByName` and `GDALRegister_GTiff`
itself; `nm -u` finds zero undefined GDAL, PROJ, TIFF, curl or OpenSSL symbols in any of
them — the only undefined names left are Python's C API and the system `libsqlite3`, `libz`,
`libc++` and `libSystem`, and `otool -hv` reports `TWOLEVEL`, so none of the five can bind
another's copy. **That is five independent copies of GDAL's driver table, error state and
configuration options in one process.**

The whole native chain is inside each of them, which is what makes them that size: `nm -m`
on `_gdal` finds `_TIFFClientOpen`, `_geod_init`, `_proj_create`, `_psl_builtin`,
`_curl_easy_init`, `_jpeg_start_compress`, `_SSL_new` and `_OPENSSL_init_ssl` all defined
locally, and `otool -L` names only the image's own install name,
`@rpath/Python.framework/Python`, `/usr/lib/libsqlite3.dylib`, `/usr/lib/libz.1.dylib`,
`/usr/lib/libc++.1.dylib` and `/usr/lib/libSystem.B.dylib`. All six are `MH_DYLIB`, so
forge's `MH_BUNDLE` conversion has nothing to do. SQLite differs too: Android's
`libproj.so` links Flet's `libsqlite3_python.so`, iOS binds the system
`/usr/lib/libsqlite3.dylib` — whichever `proj.db` you supply is read by that one.

**And this is where `osgeo.gdal` differs from `rasterio`.** rasterio splits registration
(`_env`) from lookup (`_io`) across two extensions, which is why
[it cannot open a GeoTIFF on iOS](../rasterio#ios-notes). `osgeo.gdal` does not split:
`PyInit__gdal` itself calls `GDALAllRegister`, and **every** native call in `osgeo/gdal.py`
binds to `_gdal` — all 838 of them, with the file containing no reference to `_ogr`, `_osr`,
`_gnm`, `_gdal_array` or `_gdalconst` at all — so the driver lookup, the create, the band,
both raster transfers and the re-open all land in the same image that registered the
drivers. The other modules are internally
consistent too: `PyInit__ogr` and `PyInit__gnm` each call `OGRRegisterAll` (a one-instruction
branch to `GDALAllRegister`) into their own table, `_osr` registers nothing and needs
nothing, and `_gdal_array` registers only its own in-memory `NUMPY` driver.

**What is not settled is the handoffs between them**, and that is what
[`geotiff-roundtrip`](examples/geotiff-roundtrip) exists to measure:
[`band.ReadAsArray()`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Band.ReadAsArray)
is `_gdal_array` code operating on a `_gdal` object,
[`ds.GetSpatialRef()`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Dataset.GetSpatialRef)
returns an object `_gdal` minted whose methods run in `_osr`, and
[`gdal.OpenEx(path, gdal.OF_VECTOR).GetLayer(0)`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.OpenEx)
hands a `_gdal` pointer to `_ogr`. Each pair is two separately linked GDALs with their own
PROJ contexts. SWIG's cross-module type table *is* shared — the
`swig_runtime_data4` `type_pointer_capsule` string is in all six extensions — so the objects
type-check across the boundary either way, which means a failure here would show up as a
wrong answer or a crash rather than a `TypeError`. Run the example before you rely on any
of it.

| slice (cp314) | wheel | unpacked | six `.so` |
| --- | --- | --- | --- |
| arm64 (device) | 45,163,517 | 128,501,803 | 126,305,872 |
| arm64 (simulator) | 46,528,722 | 130,094,468 | 127,898,488 |
| x86_64 (simulator) | 49,678,685 | 137,384,045 | 135,188,064 |

Per extension on the device slice: `_gdal` 26,488,680, `_ogr` 25,678,176, `_gnm` 24,938,936,
`_osr` 24,763,872, `_gdal_array` 24,347,712, `_gdalconst` 88,496. **`flet-libgdal`
contributes nothing executable at runtime** — its 112,772,601-byte wheel is `libgdal.a` plus
102 headers, and Flet's cleanup `**.a`/`**.h`/`**.hpp` globs leave only 11,986 bytes of it
(`gdalplugins/drivers.ini` and the `dist-info`) — but the build machine still downloads and
unpacks three of them. Expect a slow first `ipa` or `ios-simulator` build and plenty of
free disk; nothing to configure.

Everything else is identical on the two platforms: the eleven drivers, the codec set, the
absent GEOS and libcurl, the missing `proj.db` and `GDAL_DATA`, the Python-level import
graph and the exception defaults. Only the linkage model and the size differ.

## Things to know

- **`import osgeo.gdal` is never one extension — it maps four.** `osgeo/__init__.py` imports
  `_gdal`; `osgeo/gdal.py` line 100 does `from osgeo.gdalconst import *`, and lines
  4856–4857 do a module-level `from . import ogr` / `from . import osr`. Measured by running
  the wheel's own Python half with the six extensions replaced by recording stubs:
  `import osgeo` → `_gdal`; `from osgeo import gdal` → `_gdal`, `_gdalconst`, `_ogr`, `_osr`;
  `from osgeo import osr` → `_gdal`, `_osr`. On iOS that first line costs **77,019,224 bytes**
  of dylib before you have touched a raster, against 2,884,216 on Android arm64-v8a. There is
  nothing an app can do — the imports are unconditional in upstream's SWIG output. Budget for
  it. The example prints the live number on screen.
- **[`gdal.UseExceptions()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.UseExceptions)
  — the call every GDAL tutorial opens with — maps two more.** It loops over gdal,
  gdal_array, ogr, osr and gnm (`osgeo/gdal.py` 521–553), so it adds `_gnm` (+24,938,936 on
  iOS) and, when numpy is installed, `_gdal_array` (+24,347,712): all six extensions,
  126,305,872 bytes. Call it anyway, once at startup — error-code returns are worse — but
  know what it costs.
  [`gdal.ExceptionMgr()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.ExceptionMgr)
  is a narrower switch that skips `_gnm`, yet its `__enter__` does `from . import gdal_array`
  inside a `try/except ImportError`, so it maps the 24.3 MB `_gdal_array` **even when numpy
  is absent** and the Python wrapper then fails. Prefer one `UseExceptions()`, which is
  guarded by `find_spec("numpy")`.
- **Exceptions are off by default, and the bindings nag about it.** Without a call, a failed
  [`gdal.Open`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Open) or
  [`Driver.Create`](https://gdal.org/en/stable/api/python/raster_api.html#osgeo.gdal.Driver.Create)
  returns `None` and the first such call emits `FutureWarning: Neither gdal.UseExceptions()
  nor gdal.DontUseExceptions() has been explicitly called. In GDAL 4.0, exceptions will be
  enabled by default.` There are 21 call sites in `osgeo/gdal.py` —
  `Open`, `OpenEx`, `Driver.Create`, `Driver.CreateMultiDimensional`, `Driver.CreateCopy`,
  `Driver.Delete`, `Info`, `VectorInfo`, `MultiDimInfo`, `Translate`, `Warp`,
  `VectorTranslate`, `DEMProcessing`, `Nearblack`, `Grid`, `Contour`, `Rasterize`,
  `Footprint`, `BuildVRT`, `TileIndex` and `MultiDimTranslate`. A `None` dataset dereferenced
  later is an `AttributeError` a long way from the real failure, so turn exceptions on and
  print `type(err).__name__` plus
  [`gdal.GetLastErrorMsg()`](https://gdal.org/en/stable/api/python/general.html#osgeo.gdal.GetLastErrorMsg).
- **Eleven drivers, four of them raster: `GTiff`, `COG`, `VRT`, `MEM`, plus
  `ESRI Shapefile`, `GeoJSON`, `GeoJSONSeq`, `ESRIJSON`, `TopoJSON` and the two network
  drivers `GNMFile` and `GNMDatabase`.** Read off the shipped binaries two independent ways:
  `otool -tV` on the iOS `_gdal` shows `GDALAllRegister` branching to exactly
  `GDALRegister_GTiff`, `_COG`, `_VRT`, `_MEM`, `GNMRegisterAllInternal` and
  `OGRRegisterAllInternal`, and those two to the five `RegisterOGR*` and two `RegisterGNM*`
  entries; independently, Android's `libgdal.so` dynamic symbol table defines exactly those
  eleven (plus the `OGRRegisterAll`/`OGRRegisterDriver` dispatchers). No PNG, JPEG, GPKG,
  SQLite, CSV, GML, KML, netCDF, GRIB or JP2 — decode a PNG or JPEG with Pillow or
  opencv-python instead, and convert other formats off-device. This agrees with what
  [`rasterio`](../rasterio#things-to-know) records for the same `flet-libgdal`.
- **`flet-libgdal`'s `gdalplugins/drivers.ini` is not a capability list.** It is a 2,787-byte
  ordering table naming 251 drivers, installed unconditionally; reading it as what was
  compiled in over-counts the registry by a factor of twenty-three. On Android it does not even
  reach the device — `serious_python` copies a `flet-lib*` `opt/` tree into `jniLibs` with a
  `**/*.so` glob, which [`rasterio`](../rasterio#things-to-know) confirmed on a built APK —
  while on iOS it is most of the 11,986 bytes of `flet-libgdal` that survive cleanup. Either
  way it describes ordering, not capability. Ask the live registry
  instead: `[gdal.GetDriver(i).ShortName for i in range(gdal.GetDriverCount())]`, which is
  what the example prints, beside `ogr.GetDriverCount()` for the vector-capable subset.
- **Codecs: LZW, Deflate, PackBits, JPEG and LERC are linked; ZSTD, WEBP and LZMA are not**,
  despite GDAL advertising all of them in the
  [GTiff `COMPRESS` option list](https://gdal.org/en/stable/drivers/raster/gtiff.html#creation-options),
  which it compiles in unconditionally and filters at runtime. Marker counts, as
  `strings -a <file> | grep -c <marker>`, in the iOS `_gdal`: `LZWDecode` 7, `ZIPDecode` 3,
  `JPEGDecode` 7, `PackBitsDecode` 3, `LERCDecode` 1, and
  `ZSTDDecode`/`WebPDecode`/`LZMADecode` all 0; Android's `libgdal.so` gives 5 / 2 / 4 / 2 / 1
  and the same three zeros. Those five are the ones worth reaching for, not the whole table:
  `nm` on the iOS `_gdal` also finds `_TIFFInitOJPEG`, `_TIFFInitPixarLog`, `_TIFFInitSGILog`,
  `_TIFFInitThunderScan`, `_TIFFInitNeXT`, `_TIFFInitDumpMode` and the four CCITT initialisers
  — the same libtiff set [`rasterio`](../rasterio#things-to-know) lists — and no `ZSTD`, `WebP`
  or `LZMA` initialiser at all. Deflate needs no `flet-lib*` of its own: Android links zlib
  statically into `libgdal.so` (no `deflate` symbol crosses its `DT_NEEDED`), iOS binds the
  system `/usr/lib/libz.1.dylib`. `COMPRESS=DEFLATE` with `PREDICTOR=3` for floats is the
  sane default; `ZSTD`, `WEBP` and `LZMA` will fail at write time.
- **GDAL is compiled without libcurl and without GEOS.** Both the iOS `_gdal` and Android's
  `libgdal.so` carry GDAL's `#else`-branch diagnostics *"GDAL/OGR not compiled with libcurl
  support, remote requests not supported."* and *"GEOS support not enabled."* So `/vsicurl/`,
  `/vsis3/`, `/vsigs/` and `/vsiaz/` are dead strings — the working virtual file systems are
  `/vsimem/`, `/vsizip/`, `/vsitar/`, `/vsigzip/`, `/vsisubfile/` and `/vsisparse/` — and OGR
  geometry predicates are unavailable. (`flet-libcurl` still installs on Android because
  `libproj.so` needs it.)
- **On iOS, prefer routes that keep a dataset inside one extension.**
  `band.ReadRaster()` / `WriteRaster()` take and return `bytes` and never leave `_gdal`;
  `ReadAsArray()` / `WriteArray()` cross into `_gdal_array` but only to do a RasterIO on a
  pointer, with no registry involved. The sharpest edge is `gdal_array.SaveArray(arr, path)`,
  which is `gdal.GetDriverByName(format).CreateCopy(filename, OpenArray(...))`
  (`osgeo/gdal_array.py` 383–388) — a driver from `_gdal`'s table copying a dataset that
  `_gdal_array` created in *its* GDAL, whose table holds only the `NUMPY` driver
  (`PyInit__gdal_array` calls a file-local `GDALRegister_NUMPY` and nothing else). Untested
  on device, and easy to avoid: `Driver.Create(...)` then `band.WriteArray(...)`.
- **`Driver.Create` silently deletes an existing file first — until it can't.**
  `GDALDriver::Create` runs `QuietDelete` on the path before handing over to the driver, so a
  second `gdal.GetDriverByName("GeoJSON").Create(path, 0, 0, 0, gdal.GDT_Unknown)` on a
  *closed* file simply replaces it. `RuntimeError: The GeoJSON driver does not overwrite
  existing files.` appears only where that delete cannot happen: the previous dataset is
  still referenced, the directory is read-only, the path is a directory, or
  `APPEND_SUBDATASET=YES` is passed (four cases, all measured on host GDAL 3.13.0). So drop
  the writer reference before re-creating a path — `ds = None`, as the example does after
  every write — and remember that a re-run overwrites your data without a word.
- **Your desktop is not a preview of the device.** `flet run` resolves GDAL from PyPI or
  Homebrew — one shared libgdal, a full `proj.db`, and a registry of 214 against the mobile
  build's eleven on the machine this page was written on. EPSG codes, PNG and `ZSTD` all work
  on your Mac and fail on the phone, and the single-table-versus-five-tables difference does
  not exist there at all. Validate on a device or simulator, and make the app render its own
  exceptions on screen — an unhandled exception in a Flet handler produces `SESSION_CRASHED`
  and you lose the diagnosis.
- **Size.** Android arm64-v8a: a 1,374,152-byte wheel unpacking to 5,359,714, of which
  3,163,704 is the six extensions, on top of 22.8 MB of shared `flet-lib*` libraries. iOS
  device: a 45,163,517-byte wheel unpacking to 128,501,803, of which 126,305,872 is the six
  extensions and nothing else installs. That is **40× the extension bytes on iOS for the same
  eleven drivers**, or roughly 5× once Android's shared libraries are counted in.

## Build notes (maintainers)

Two recipes: `flet-libgdal` builds GDAL, `recipes/gdal` builds upstream's own bindings
against it. `patches/config.patch` explains both of its hunks and its own bump hazard in its
preamble, and `meta.yaml` comments its `GDAL_LIBS` and version pin next to them, so what is
left here is shape and the bump checklist.

**Almost everything this page warns about is a `flet-libgdal` decision, not a gdal one.**
The eleven-driver registry, the codec set, the missing `GDAL_DATA` and `proj.db`, the absent
GEOS and libcurl and the iOS static-only link all come from that recipe and from
`flet-libproj`. A `flet-libgdal` bump can invalidate most of this README without a line
changing here. The version pin in `meta.yaml` is exact for a reason — bump the two together
and re-read the claims off the built wheels.

**The iOS size is a linking artefact worth fixing at the source.** `meta.yaml`'s `GDAL_LIBS`
names the whole static chain because `libgdal.a` leaks undefined symbols; that is what drags
a full GDAL into five of the six extensions and turns Android's ~26 MB of native code into
126 MB. Aligning `flet-libgdal`'s iOS cmake with Android's would let `GDAL_LIBS` drop back to
`gdal` and would rewrite the [iOS notes](#ios-notes), both size tables and the whole
cross-extension question at once. Note that `requirements.host`'s `openssl >=3.0.15` is a
build-time-only input: `build.py` promotes only `flet-*` host requirements into
`Requires-Dist`, so it never reaches a device, and it exists purely because `GDAL_LIBS` names
`ssl` and `crypto`.

What to re-verify on a bump — a green build establishes almost none of what this page claims:

- **`tests/test_gdal.py` cannot catch the thing this page is about.** Both tests stay inside
  `_gdal` and inside the `MEM` driver: `test_in_memory_raster` does
  `GetDriverByName("MEM")` → `Create("", 4, 3, 1)` → `Fill` → `ReadRaster`, and
  `test_version_loaded` asserts `gdal.VersionInfo()`. A broken GeoTIFF-on-disk path, a
  broken `osr` or `ogr` handoff, or a vanished driver would all pass CI green. Worth adding:
  an assertion over the exact eleven driver short names (so a driver appearing is as red as
  one disappearing), a GTiff write-read-compare in `tmp_path`, an `osr` round trip through
  `SetFromUserInput`, and an assertion that `ImportFromEPSG(4326)` fails. That pins the
  boundary this page documents.
- **The linkage split.** Android: `DT_NEEDED` still naming `libgdal.so` by bare soname,
  `libc++_shared.so` on exactly five of six, `libgdal.so` still *not* naming
  `libc++_shared.so` itself, the libproj chain intact, and 16 KB `PT_LOAD` alignment
  everywhere. iOS: still six `MH_DYLIB`, still exactly five carrying GDAL, `otool -L` still
  naming no libcurl/libtiff/libproj, and `nm -u` still finding no undefined GDAL/PROJ symbol.
- **The single-table property, which is the whole iOS argument.** Re-check that
  `PyInit__gdal` still calls `GDALAllRegister`, and that `osgeo/gdal.py` still contains no
  reference to `_ogr`, `_osr`, `_gnm`, `_gdal_array` or `_gdalconst`. Upstream moving one
  function to a different SWIG module would break iOS the way rasterio is broken, silently.
- **The import graph.** Re-run it against the new `osgeo/*.py` rather than assuming: the
  four-modules-on-import and six-after-`UseExceptions()` figures are upstream source
  behaviour and move on any bindings release.
- **The driver set and the codec set**, from the symbol tables on both platforms — Android's
  `libgdal.so` is stripped, so cross-check by dynamic symbols and codec marker strings rather
  than by `nm`.
- **The sizes are measured.** Re-measure rather than adjusting by eye; the iOS totals are the
  whole argument for budgeting 126 MB.
- **The example is the live regression test.** Bumping this recipe means bumping
  [`geotiff-roundtrip`](examples/geotiff-roundtrip)'s `gdal==` pin and rebuilding it on both
  platforms. Its panels are one-to-one with the claims above.
