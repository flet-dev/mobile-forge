# rasterio

[`rasterio`](https://rasterio.readthedocs.io/en/stable/) reads and writes geospatial
rasters as numpy arrays. It is [GDAL](https://gdal.org/) with a Python API that does not
feel like C++: open a GeoTIFF, ask for a
[`Window`](https://rasterio.readthedocs.io/en/stable/api/rasterio.windows.html#rasterio.windows.Window)
of it, get an `ndarray` back. On a phone that matters more than on a desktop, because a
window read is what lets an app touch a raster far larger than its RAM — reading a 256×256
patch out of a 4096×4096 float32 elevation surface cost 3 ms and 1.3 MB of RSS against
195 ms and 134 MB for the whole raster (host figures — see
[Things to know](#things-to-know)). Everything happens in-process, with no network.

**Read [iOS notes](#ios-notes) before you plan anything, and treat this package as
Android-only for now.** Raster I/O works on Android and fails on iOS: measured on
2026-08-19, the same app writes and reads a 1024x1024 GeoTIFF on an arm64 emulator (0 of
1,048,576 pixels differing) and cannot open one at all on an iPhone simulator, where
`rasterio.open(..., "w", driver="GTiff")` raises
`DriverRegistrationError: ('No such driver registered: %s', b'GTiff')` even though the same
process has just listed `GTiff` among its eleven registered drivers. If you need raster I/O on
iOS, use [`gdal`](../gdal) — GDAL's own SWIG bindings against this same `flet-libgdal`. The
split that breaks rasterio does not exist in its module layout, and the device confirms it:
measured 2026-08-19, its example round-trips a 512x512 GeoTIFF with 0 of 262,144 pixels
differing on the iPhone simulator as well as on Android.

Beyond that, these wheels are a deliberately small GDAL: four raster drivers, no `proj.db`,
no libcurl. On Android GeoTIFF work is complete and fast; EPSG codes, PNG/JPEG/netCDF files
and `/vsicurl/` are not there on either platform, and none of that announces itself at
import.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "rasterio",
]
```

Nothing to configure: no
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry, no loader shim. All 119 entries are 56 `.py`, 15 `.so`, 41 Cython sources and stubs
and 7 `dist-info` files — **no data file of any kind** — and every extension filename
carries the ABI tag its own runtime looks for, which is what the import machinery matches
on: `_base.cpython-313-aarch64-linux-android.so` and its 3.14 twin on Android, the bare
`_base.cpython-312.so` on Android 3.12 (the tag Flet's own 3.12 build uses — numpy's cp312
Android wheel is named the same way), `_base.cpython-312-iphoneos.so` and up on iOS.

The requirements come along without configuring. **`numpy`** is on this index;
**`affine`**, **`attrs`**, **`certifi`**, **`click`**, **`cligj`** and **`pyparsing`** are
pure Python, absent from it, and resolve from PyPI. The rest are the native chain: the
recipe pins **`flet-libgdal`** on both platforms (plus `flet-libcpp-shared` on Android and
`flet-libjpeg` on iOS), `flet-libgdal` requires **`flet-libproj`**, and that pulls in
`flet-libtiff`, `flet-libcurl`, `flet-libjpeg` and `flet-libpsl`. Only Android loads any of
them at runtime — see [Android notes](#android-notes) and [iOS notes](#ios-notes).

Nineteen wheels at the same build number: Python 3.12, 3.13 and 3.14 × three Android ABIs
(arm64-v8a, armeabi-v7a, x86_64) and three iOS slices (device, arm64 simulator, x86_64
simulator), plus a legacy 32-bit `android_24_x86` slice on 3.12. No arch is excluded.
Upstream requires **Python 3.12 or newer** (`Requires-Python: >=3.12` in the wheel
`METADATA`), so your app's `requires-python` has to be at least `>=3.12` or `uv` fails the
resolve for the lower splits.

Flet's default [compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup)
matters here more than usual: **20.3 MB of every wheel is Cython-generated `.c`/`.cpp`
source**, and cleanup takes 20.6 MB off the payload in all. Leave it on. Nothing in the
package reads its own source, so compiling to `.pyc` is safe.

## Storage

Rasters belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, durable, included in backups, and from Flet 0.86.0 also the process working
directory on device. It has to be a **writable** directory rather than a bundled asset,
because GDAL writes beside the raster: computing
[`ds.stats(indexes=1, approx=False)`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetReader.stats)
on a 128×128 GeoTIFF left a 351-byte `s.tif.aux.xml` next to it, and
[`build_overviews`](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html#rasterio.io.DatasetWriter.build_overviews)
needs `r+` on the file itself.

Avoid
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it) and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) for anything you want to keep.

### No `proj.db`, and no `GDAL_DATA` — on either platform

Neither the rasterio wheels nor `flet-libgdal` ship a PROJ database or a GDAL data
directory. `unzip -l` finds zero entries matching `gdal_data`, `proj_data`, `share/` or
`.db` in either wheel, and `flet-libgdal` is 102 headers plus `opt/lib/libgdal.so` (or
`libgdal.a`) plus a `gdalplugins/drivers.ini`. Nor does anything further down the chain —
`flet-libproj`, `flet-libtiff`, `flet-libcurl`, `flet-libjpeg` and `flet-libpsl` are all
headers and libraries only. This is the same gap [`pyproj`](../pyproj#storage) documents,
reached by a different route, and it has the same single cause: both native recipes end
their build with `rm -rf $PREFIX/{bin,share}`.

**Unlike pyproj, rasterio is not crippled by it.** pyproj gates every `CRS`, `Proj` and
`Transformer` call behind a Python-level `DataDirError`; rasterio has no such gate, so only
*authority-database lookups* fail. With both data directories hidden — the exact shape the
mobile wheels are in:

- `import rasterio` **succeeds**, printing one line to stderr:
  `Warning 3: Cannot find gdalvrt.xsd (GDAL_DATA is not defined)`.
- [`CRS.from_string("+proj=longlat +datum=WGS84 +no_defs")`](https://rasterio.readthedocs.io/en/stable/api/rasterio.crs.html)
  and `+proj=utm +zone=33 …` and `CRS.from_wkt(…)` all **work**, and a GeoTIFF written with
  one keeps its CRS through a read-back.
- [`CRS.from_epsg(4326)`](https://rasterio.readthedocs.io/en/stable/api/rasterio.crs.html#rasterio.crs.CRS.from_epsg)
  raises `rasterio.errors.CRSError: The EPSG code is unknown. PROJ:
  internal_proj_create_from_database: Cannot find proj.db`. So does
  `CRS.from_string("EPSG:3857")`, `rasterio.open(…, crs="EPSG:4326")`, and any
  [`rasterio.warp`](https://rasterio.readthedocs.io/en/stable/api/rasterio.warp.html) call
  between two EPSG codes.
- `crs.to_epsg()` returns `None` on a proj-string CRS, because identifying it against the
  authority database is exactly the thing that cannot happen.

`GDAL_DATA` costs nothing beyond that one stderr line: with `gdal_data` hidden and PROJ data
present, EPSG lookups, `to_wkt()` and a GeoTIFF round trip tagged `EPSG:32633` all worked.

### Getting EPSG codes back

Ship `proj.db` as an asset and point rasterio's search path at the directory holding it.
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
is where a bundled `src/assets/` lands on device:

```python
rasterio._env.set_proj_data_search_path(
    os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "proj")
)
```

**There is no import-time-only window** — unlike pyproj's `PROJ_DATA`, this works at any
point after `import rasterio`. Verified against the same no-data process: `CRS.from_epsg(4326)`
raised before the call and returned `EPSG:4326` after it, with `CRS.from_epsg(32633)`,
`CRS(...).to_epsg()` and an `EPSG:4326 → EPSG:3857` warp all working afterwards
(Paris → 261845.70624393807, 6250564.349543124). `rasterio/env.py` also honours `PROJ_DATA`
and `PROJ_LIB` from `os.environ` on the way through the import, if you would rather set an
environment variable.

Take the database from the same-version PyPI wheel: `rasterio==1.5.0`'s macOS build carries
`rasterio/proj_data` at 9.3 MB, of which `proj.db` alone is 9,601,024 bytes. Note the
version skew — that file comes from PROJ 9.7.1 and the mobile chain is PROJ 9.5.0
(`Rel. 9.5.0, September 15th, 2024` in both `libproj.so` and the iOS extensions). The skew
runs the tolerated way: PROJ gates a database on `DATABASE.LAYOUT.VERSION`, requiring the
major to match and the minor to be *at least* what the library expects (the shipped
`libproj.so` carries both diagnostics — "whereas a number >= … is expected" is the minor
one). That file declares layout 1.6, and [`pyproj`](../pyproj#storage) measured 9.5.0's
expectation as 1.4, so 1 == 1 and 6 ≥ 4 both hold. Still unrun on a device; confirm it there
before shipping a database.

If you would rather ship the combination someone has already exercised, take `proj.db` from
`pyproj`'s wheel instead — layout 1.4, an exact match, and 9,273,344 bytes rather than
9,601,024. It is the same PROJ 9.5.0 reading either file here, so the choice is only about
which pairing has evidence behind it.

**pyproj's zero-byte stub does not transfer.** That page unlocks its whole proj-string API by
creating an empty file named `proj.db`, because pyproj's Python-level gate checks only that
one exists. rasterio has no such gate — proj-strings already work here with nothing supplied —
so the stub buys nothing and costs clarity: with one in place `CRS.from_epsg(4326)` fails as
`SQLite error [ no such table: metadata ]` instead of the plain *Cannot find proj.db*.

**Or do not ship one.** Write CRSes as `+proj=` strings or WKT and nothing needs a database
at all — that is what the [`elevation-tile`](examples/elevation-tile) example does, and it
costs zero bytes of payload. What you give up is discovery: you have to know the projection
parameters, and `to_epsg()` will not name them for you.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`elevation-tile`](examples/elevation-tile) — a GeoTIFF written to app storage, then read
  back and differenced against the array it came from.

## Threading

**Never share a default dataset handle between threads. It does not raise — it kills the
process.** Eight threads doing overlapping 1024×1024 reads on a single `rasterio.open`
result terminated the interpreter with SIGBUS (exit 138) on **4 of 5 runs**; the fifth
survived with a `RasterioIOError: Read failed` and two arrays of wrong data. Under
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — which
submits to a shared pool, so two taps really do overlap — that is a native crash with no
Python traceback anywhere.

Three arrangements were clean:

- **One `rasterio.open` per thread** — 40/40 calls on each of three runs. What the example
  does, and the simplest rule.
- **A `threading.Lock` around the whole read**, including consuming the array it returns —
  40/40 on each of three runs.
- **`rasterio.open(path, thread_safe=True)`**, new in 1.5.0 — it adds GDAL's
  `GDAL_OF_THREAD_SAFE` open flag, so one handle really can be shared. 12/12 clean runs of
  an eight-thread overlap that crashed the default handle, every array equal to the
  reference. The flag is compiled into the shipped GDAL: `GDALGetThreadSafeDataset` is in
  Android's `libgdal.so` dynamic symbol table and in the iOS extensions, and rasterio raises
  `GDALOptionNotImplementedError` below GDAL 3.10 (the chain is at 3.13.1). **Mode `"r"`
  only, and silently so** — `rasterio.open` forwards `thread_safe` to `DatasetReader` and
  drops it for `"r+"` and `"w"` without a word, so a writer handle accepts the keyword and
  is an ordinary unguarded dataset.

[`rasterio.Env()`](https://rasterio.readthedocs.io/en/stable/api/rasterio.env.html#rasterio.env.Env)
itself is thread-local by design and is safe to enter per thread.

The standing Flet caveats apply on top: `run_thread` never retrieves the worker's future,
so an exception inside one surfaces nowhere — wrap the body — and auto-update does not
reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Android notes

**GDAL stays one shared library.** All fifteen extensions list exactly `libm.so`,
`libgdal.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` in `DT_NEEDED`, with
`libc++_shared.so` inserted in `_warp`, `_filepath` and `_fill` — and no `RUNPATH` or
`RPATH` at all. `libgdal.so` carries `SONAME libgdal.so`, so serious_python's flattening of
every wheel `.so` into `jniLibs/<abi>/` is enough for the loader to resolve it — confirmed on
a built APK, whose `lib/arm64-v8a/` holds `libgdal.so`, `libproj.so`, `libtiff.so`,
`libcurl.so`, `libjpeg.so` and `libpsl.so` under their bare sonames alongside the fifteen
extensions as `librasterio-<module>.so`, with an empty `assets/extract.zip`. Below that,
`libgdal.so` names `libproj.so`; `libproj.so` names `libsqlite3_python.so`, `libtiff.so` and
`libcurl.so`; `libtiff.so` names `libjpeg.so` and `libz.so`; `libcurl.so` names `libpsl.so`,
`libssl_python.so`, `libcrypto_python.so` and `libz.so`. Every `LOAD` segment in all of them
reports `align 0x4000`, the 16 KB page alignment Android 15 requires.

| slice (cp314) | wheel | after cleanup | rasterio `.so` | `libgdal.so` | PROJ chain `.so` |
| --- | --- | --- | --- | --- | --- |
| arm64-v8a | 4,324,965 | 3,819,498 | 3,356,840 | 13,997,320 | 7,513,872 |
| armeabi-v7a | 4,172,820 | 2,705,173 | 2,242,516 | 9,702,048 | 5,227,468 |
| x86_64 | 4,405,721 | 3,815,592 | 3,352,952 | 15,283,480 | 8,347,680 |

That is **24.9 MB of native code on arm64-v8a**, most of it GDAL and PROJ rather than
rasterio; the payload after cleanup, counting only the rasterio and `flet-libgdal` wheels,
is 17.8 MB.

## iOS notes

**GDAL is absorbed into the extensions instead, ten times over.** `flet-libgdal` ships a
524,528,736-byte `libgdal.a` and no shared library, and the link pulls it into every
extension that touches GDAL: `_base`, `_env`, `_features`, `_fill`, `_io`, `_transform`,
`_version`, `_warp`, `crs` and `shutil` each carry their own copy of the `GDAL 3.13.1`
version string and weigh 25.3–26.1 MB, while `_err`, `_example`, `_filepath`, `_vsiopener`
and `cache` are 0.1–1.2 MB. **259,746,200 bytes of extension on the device slice against
3,356,840 on Android arm64-v8a** — the same functionality, 77× the native bytes — and
`import rasterio` loads eleven of the fifteen regardless, so an app that only reads a
GeoTIFF pays for all of it. Budget for it; there is nothing a consumer can do.

**And that absorption is what costs iOS its driver registry.** The symbol tables say so
directly: on iOS `_env`, `_io`, `_base` and `_features` each *define* `GDALRegister_GTiff`
themselves and import it from nobody, so each carries its own copy of GDAL's global driver
table. On Android every extension instead carries `DT_NEEDED: libgdal.so` and `_env` imports
`GDALAllRegister` as an undefined symbol resolved at load — one library, one table, shared.
`rasterio.Env()` lives in `_env` and registers drivers there; `rasterio.open` resolves the
name in `_io`. On Android, where a single shared `libgdal.so` is linked by all of them,
that is one table and everything works. On iOS the two do not agree: `env.drivers()`
returns the full eleven while `rasterio.open(path, "w", driver="GTiff")` raises
`DriverRegistrationError`, and a windowed read of an existing file raises
`SystemError: Unknown GDAL Error`. Entering an explicit `rasterio.Env()` around the call
does not help, which independently rules out the ordinary per-thread explanation.

Measured 2026-08-19 with the [`elevation-tile`](examples/elevation-tile) example: Android
arm64 emulator wrote 2,377,664 B and read it back with 0 pixels differing; the iPhone
simulator failed both. Until this is fixed, an iOS app can import rasterio and read its
version and driver list, and can do nothing else with a raster.

The diagnosis is specific to how rasterio is split, which is why [`gdal`](../gdal#ios-notes) is
worth trying instead on that platform: `osgeo/gdal.py` binds every native call to one
extension, `_gdal`, whose own module init calls `GDALAllRegister` — so the register-here,
look-up-there gap above has nowhere to open. That structural argument from the symbol
tables is backed by a device run: measured 2026-08-19, `osgeo.gdal` wrote and read back a
512x512 GeoTIFF on the iPhone simulator with 0 of 262,144 pixels differing.

| slice (cp314) | wheel | unpacked | after cleanup |
| --- | --- | --- | --- |
| arm64 (device) | 95,334,754 | 280,827,742 | 260,208,677 |
| arm64 (simulator) | 98,126,064 | — | — |
| x86_64 (simulator) | 104,441,092 | — | — |

All fifteen are `MH_DYLIB`, so forge's `MH_BUNDLE` conversion has nothing to do, and
`otool -L` on each lists only its own install name, `@rpath/Python.framework/Python`,
`/usr/lib/libsqlite3.dylib`, `/usr/lib/libz.1.dylib` and `/usr/lib/libSystem.B.dylib`, plus
`/usr/lib/libc++.1.dylib` on the same three that need `libc++_shared` on Android. No
libcurl, libtiff or libproj: those are static archives already inside. `flet-libgdal`'s iOS
wheel is 112,772,601 bytes of which cleanup's `**.a`/`**.h`/`**.hpp` globs delete all but
11,986, so it contributes nothing to the bundle.

Build-machine cost follows from that: an `ipa` or `ios-simulator` build downloads three
~95–105 MB rasterio wheels and three ~113 MB `flet-libgdal` wheels, each of which unpacks a
half-gigabyte archive that is then deleted. Expect a slow first build and plenty of free
disk; nothing to configure.

SQLite differs too — Android's `libproj.so` links `libsqlite3_python.so` from Flet's Python
bundle, iOS binds the system `/usr/lib/libsqlite3.dylib`. Whichever `proj.db` you supply is
opened by that SQLite.

Everything else is the same on both platforms: the driver set, the compression codecs, the
missing `proj.db` and `GDAL_DATA`, and the absence of libcurl are identical. Only the
linkage model and the size differ.

## Things to know

- **Four raster drivers, eleven in the whole registry.** `GDALAllRegister` on device
  registers: `GTiff`, `COG`, `MEM` and `VRT` for raster, the five OGR vector drivers
  `ESRIJSON`, `GeoJSON`, `GeoJSONSeq`, `ESRI Shapefile` and `TopoJSON`, and the two network
  drivers `GNMFile` and `GNMDatabase` that come with GNM. Two independent reads agree, and
  are exhaustive because `gdalallregister.cpp` calls nothing else: the `GDALRegister_*` /
  `RegisterOGR*` / `RegisterGNM*` entries in `libgdal.so`'s dynamic symbol table on Android,
  and the undefined symbols of `gdalallregister.cpp.o`, `ogrregisterall.cpp.o` and
  `gnmregisterall.cpp.o` inside iOS's `libgdal.a`. No PNG, JPEG, HFA, netCDF, GRIB, JP2, HDF
  or anything else — the recipe builds GDAL with `-DGDAL_BUILD_OPTIONAL_DRIVERS=OFF`. Ask
  the live registry on device rather than guessing, and ask it through
  [`rasterio.Env`](https://rasterio.readthedocs.io/en/stable/api/rasterio.env.html#rasterio.env.Env):
  `with rasterio.Env() as env: env.drivers()` returns the whole short-name → long-name map
  (147 entries on a desktop, those eleven on device).
  [`raster_driver_extensions()`](https://rasterio.readthedocs.io/en/stable/api/rasterio.drivers.html#rasterio.drivers.raster_driver_extensions)
  answers a narrower question — which *file extension* maps to which driver — and neither
  `MEM` nor `COG` appears in it even on a desktop, so it under-reports what you can write.
- **`flet-libgdal`'s `gdalplugins/drivers.ini` is not a capability list.** It is a
  2,787-byte ordering table naming 251 drivers, installed unconditionally; its own header
  says it keeps in sync with `gdalallregister.cpp`. Reading it as what was compiled in
  over-counts what the registry holds by a factor of twenty-three. On Android it does not
  even reach the device: `serious_python` copies a `flet-lib*` `opt/` tree into `jniLibs`
  with a `**/*.so` glob, so every non-library file in it is dropped — `unzip -l` on a built
  APK finds `lib/<abi>/libgdal.so` and no `drivers.ini` anywhere.
- **Each way of hitting an unsupported format fails differently.** Naming an unregistered
  driver — `rasterio.open(p, "w", driver="PNG")` — raises
  `DriverRegistrationError: ('No such driver registered: %s', b'PNG')` (message format
  confirmed with a driver name that is unregistered on the host too);
  `rasterio.drivers.driver_from_extension("x.png")` raises
  `ValueError: Unable to detect driver. Please specify driver.` because it is a lookup in
  the same registry-derived extension map; opening an unrecognised file raises
  `RasterioIOError: '<path>' not recognized as being in a supported file format.` Pass
  `driver="GTiff"` (or `COG`) explicitly instead of relying on extension sniffing, convert
  other formats off-device, and use Pillow or opencv-python to decode a PNG or JPEG on a
  phone.
- **The GTiff `COMPRESS` option list inside the binary lies.** It advertises `ZSTD`,
  `WEBP`, `LZMA` and `LERC_ZSTD` with matching `ZSTD_LEVEL`/`WEBP_LEVEL`/`LZMA_PRESET`
  options — GDAL compiles those XML literals in unconditionally and builds the real list at
  runtime from `TIFFGetConfiguredCODECs()`. The codecs actually linked are LZW, Deflate,
  PackBits, JPEG, LERC, PixarLog, SGILog, ThunderScan, NeXT and the CCITT family
  (`_TIFFInit*` in the iOS symbol table; the same `LZWDecode`/`ZIPDecode`/`JPEGDecode`/
  `PackBitsDecode`/`LERCDecode`/`lerc_encode` markers appear in Android's stripped
  `libgdal.so`). `ZSTDDecode`, `WebPDecode` and `LZMADecode` appear in **neither** binary,
  and neither carries a `ZSTD_compress`, `WebPEncode` or `lzma_code` symbol. So
  [`compress="DEFLATE"`](https://gdal.org/en/stable/drivers/raster/gtiff.html#creation-options)
  (with `predictor=2` for integers, `3` for floats) is the sane default, `LZW` or
  `PACKBITS` where speed matters, `LERC`/`LERC_DEFLATE` for lossy float elevation — and
  `ZSTD`, `WEBP` and `LZMA` will fail at write time.
- **GDAL is compiled without libcurl, so rasterio on device is strictly offline.** Both
  binaries carry GDAL's `#else`-branch diagnostic, *"GDAL/OGR not compiled with libcurl
  support, remote requests not supported."*, and Android's `libgdal.so` has no libcurl in
  `DT_NEEDED` and zero `curl_easy` dynamic symbols. `/vsicurl/`, `/vsis3/`, `/vsigs/`,
  `/vsiaz/` and `rasterio.session`'s AWS/GS/Azure support are all dead — even on iOS, where
  libcurl objects *are* linked into the extensions by the recipe's `GDAL_LIBS` chain and
  GDAL simply never calls them. (`flet-libcurl` still installs on Android because
  `libproj.so` needs it.)
- **`ds.crs == crs_you_wrote` is `False` after a GeoTIFF round trip**, with or without a
  PROJ database. The GeoTIFF keys normalise the WKT, so a semantically identical CRS
  compares unequal — while `to_dict()` on both gives
  `{'proj': 'longlat', 'datum': 'WGS84', 'no_defs': True}`. Compare `crs.to_dict()`, or
  `to_epsg()` when a database is available, not `==`.
- **`rasterio.show_versions()` prints its header and then raises**
  `AttributeError: module 'importlib' has no attribute 'metadata'`. Upstream bug in 1.5.0,
  not a build artefact: `_show_versions.py` does `import importlib` and calls
  `importlib.metadata.version`, so it only survives if something else in the process
  imported `importlib.metadata` first — importing `flet` does not. Do
  `import importlib.metadata` yourself, or build a header from
  `rasterio.__version__`, `__gdal_version__` and `__proj_version__`, which all work with no
  data at all.
- **Windowed reads are the whole point on a phone.** Scale the example's surface up to
  4096×4096 float32, tiled 256×256 with DEFLATE and `predictor=3` (32,652,710 bytes on disk,
  67,108,864 as an array), and a
  [`Window(1000, 1000, 256, 256)`](https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html)
  read costs 3 ms and 1.3 MB of RSS while `ds.read(1)` costs 195 ms and 134 MB. The RSS
  figures are what matters on a phone and they are structural — the window allocates its
  256 KB, the full read allocates the whole 64 MB band and a decode buffer beside it. The
  *times* are host numbers (macOS arm64, GDAL 3.12.1) and they track how compressible the
  data is, not the pixel count: a near-planar surface of the same shape writes to 908,105
  bytes and reads fully in 107 ms on the same machine. Measure on device before budgeting.
  Tiling, `block_shapes`, `block_windows` and internal overviews all work too —
  `build_overviews([2, 4], Resampling.average)` in `r+` wrote them *inside* the file, with
  no `.ovr` sidecar.
- **`ds.stats(approx=False)` returns a cached number once an `.aux.xml` exists, and the
  cache is coarser than the computation.** On a 1024×1024 float32 surface the first call
  agrees with a float64 numpy pass to 1.4e-13; a second call on the same file agrees only to
  4.3e-12, because GDAL then reads the sidecar it wrote and the sidecar stores 14 significant
  digits (`<MDI key="STATISTICS_STDDEV">167.43569923974</MDI>`). Both were measured on the
  same raster. Re-opening in `"w"` deletes the sidecar, so a writer that rewrites the file
  each run — the [`elevation-tile`](examples/elevation-tile) example does — always shows the
  computed figure. Quote which one you mean, and do not assert a tolerance tighter than 1e-11
  without knowing whether a sidecar was there.
- **GEOS is not compiled in** — no `HAVE_GEOS` in `flet-libgdal`'s `cpl_config.h`, and both
  binaries carry GDAL's *"GEOS support not enabled."* string — so OGR geometry predicates
  and operations are unavailable. This is not a mobile-only limitation: rasterio's own PyPI
  wheels report `__geos_version__ == '0.0.0'` too, and
  [`rasterio.features`](https://rasterio.readthedocs.io/en/stable/api/rasterio.features.html)
  and [`rasterio.mask`](https://rasterio.readthedocs.io/en/stable/api/rasterio.mask.html)
  work anyway — they want GeoJSON-shaped dicts, not GEOS geometries. Use `shapely` if you
  need real geometry operations.
- **Your desktop is not a preview of the device, and the gap is enormous.** `flet run`
  resolves rasterio from PyPI, whose macOS wheel bundles `rasterio/gdal_data` (2.1 MB) and
  `rasterio/proj_data` (9.3 MB) and registers 44 raster drivers across 59 extensions against
  the mobile build's four. EPSG codes, PNG, netCDF and `compress="ZSTD"` all work on your
  Mac and fail on the phone. Reproduce the device shape locally by renaming
  `site-packages/rasterio/gdal_data` and `.../proj_data` aside — that is how the CRS findings
  above were established — and validate on a device or simulator before shipping.

## Build notes (maintainers)

Two recipes: `flet-libgdal` builds GDAL, `recipes/rasterio` consumes it.
`patches/mobile.patch` explains its own hunk and `meta.yaml` comments its `script_env` next
to it, so what is left here is shape and the bump checklist.

**Everything this page warns about is a `flet-libgdal` decision, not a rasterio one.** The
eleven-driver registry comes from `-DGDAL_BUILD_OPTIONAL_DRIVERS=OFF` /
`-DOGR_BUILD_OPTIONAL_DRIVERS=OFF`; the missing `GDAL_DATA` and `proj.db` come from
`rm -rf $PREFIX/{bin,share}` in `flet-libgdal/build.sh` and `flet-libproj/build.sh`; the
absent libcurl comes from `-DGDAL_USE_CURL=OFF` on Android and `-DGDAL_USE_EXTERNAL_LIBS=OFF`
on iOS. A `flet-libgdal` bump can therefore invalidate most of this README without the
rasterio recipe changing a line. Bump the two together and re-read the claims off the built
wheels.

**The iOS size is a linking artefact worth fixing at the source.** `meta.yaml`'s
`GDAL_LIBS` names the whole static chain because `libgdal.a` leaks undefined symbols;
that is what drags a full copy of GDAL into ten of the fifteen extensions and turns the
17.8 MB rasterio-plus-`flet-libgdal` payload Android carries into a 260 MB one. Aligning
the iOS cmake with Android's would let `GDAL_LIBS` drop back to `gdal` and would rewrite
the [iOS notes](#ios-notes), the size tables and the `Requires-Dist` reasoning at once.

What to re-verify on a bump — a green build establishes almost none of what this page
claims:

- **`tests/test_rasterio.py` asserts far less than it appears to.** `test_gdal_version` is
  a genuine canary for the `GDAL_LIBS` chain. `test_drivers_listed` is not: `is_blacklisted`
  is `return mode in blacklist.get(name, ())`, a pure-Python dict lookup with no
  `@ensure_env` decorator, so only the *import* of `rasterio.drivers` touches native code
  and the registry itself is untested. Replace it with an assertion over
  `rasterio.Env().drivers()` inside its context (the exact eleven keys, so a driver
  appearing is as red as one vanishing), a write-read-compare of a real GeoTIFF, and an
  assertion that `CRS.from_epsg(4326)` raises `CRSError`. That pins the exact boundary this
  page documents and turns a `flet-libgdal` driver change red instead of silent.
- **The driver set and the codec set**, from the symbol tables on both platforms — Android's
  `libgdal.so` is stripped, so cross-check it by dynamic symbols and codec marker strings
  rather than by `nm`.
- **The linkage split.** Android: `DT_NEEDED` still naming `libgdal.so` by bare soname,
  `libc++_shared.so` on exactly `_warp`/`_filepath`/`_fill`, the libproj chain intact, and
  16 KB `PT_LOAD` alignment everywhere. iOS: still fifteen `MH_DYLIB`, still exactly ten
  carrying GDAL, `otool -L` still naming no libcurl/libtiff/libproj. If iOS ever links
  dynamically, the iOS section and both size tables change.
- **The threading crash.** SIGBUS on a shared dataset handle is GDAL's behaviour, not
  rasterio's, so a GDAL bump can move it in either direction. Nothing in CI exercises it and
  the example is written to avoid it, so it will not surface on its own.
- **The `proj.db` version pairing.** The database the [Storage](#storage) section points at
  is PROJ 9.7.1's and the chain is 9.5.0; that combination has never been run on a device.
  If someone does, record the result here.
- **The sizes and timings are measured.** Re-measure rather than adjusting by eye; the iOS
  total in particular is the whole argument for budgeting a quarter of a gigabyte.
