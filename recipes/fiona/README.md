# fiona

[`fiona`](https://fiona.readthedocs.io/en/stable/) reads and writes **vector** geospatial
data — points, lines and polygons carrying attributes — through
[GDAL/OGR](https://gdal.org/), and hands each feature back as a plain Python mapping with
`geometry` and `properties`, shaped like a GeoJSON feature.
[`fiona.open`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.open) returns a
`Collection`: iterate it to read, hand it records to write. On a phone that is what lets an
app store, edit and exchange real vector data with no database and no network — everything
happens in-process, on files in app storage.

**Read [iOS notes](#ios-notes) before you plan around this.** On iOS each extension carries
its own statically linked copy of GDAL, and the symbol tables say nothing ever registers a
vector driver into the image `fiona.open` does its work in. **Both halves of that were
measured on 2026-08-19 and the binaries were right.** On an arm64-v8a Android 14 emulator
the round trip works, four times over: GeoJSON and ESRI Shapefile, each carrying 200 Point
features and 200 Polygon features out and back, all four reporting 200 of 200 read back
with 0 type, 0 integer and 0 string mismatches. On an iPhone 16 simulator the same build
reports, through `fiona._env`, a registry identical to Android's — `driver_count()` 17,
`Env().drivers()` six, `MEM` among them — and then fails all four in `fiona.ogrext` with
`FionaNullPointerError: NULL pointer error`. That pair is
the diagnosis rather than a symptom of it: one module can enumerate the drivers another
module cannot find, in the same process, at the same moment. Two extensions, two GDALs.
So: treat fiona as Android-only, and use [`gdal`](../gdal)'s `osgeo.ogr` for vector I/O
on iOS.

Android's one defect is the mirror image, and it is fixable in your `pyproject.toml`:
`import fiona.transform` fails there with
`ImportError: dlopen failed: library "libc++_shared.so" not found`, because that one
extension needs the Android C++ runtime and nothing in fiona's chain declares it. Add
`flet-libcpp-shared` beside `fiona` and it works; see [Android notes](#android-notes).
On iOS `fiona.transform` imports fine — libc++ is linked statically there — so each
platform breaks in exactly one place, and in a different place. The
[`feature-roundtrip`](examples/feature-roundtrip) example is the instrument for both.

Beyond that, these wheels are a deliberately small GDAL: **six vector drivers registered,
five of them reachable through fiona and three of those writable**, no `proj.db`, no
`GDAL_DATA`, no GEOS and no libcurl. None of that announces itself at import.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
]

[tool.flet.android]
dependencies = [
    "fiona",
    "flet-libcpp-shared",
]

[tool.flet.ios]
dependencies = [
    "fiona",
]
```

`flet-libcpp-shared` is on the Android side only, and only `fiona.transform` needs it —
without it that one import raises `ImportError: dlopen failed: library "libc++_shared.so"
not found` while everything else works. iOS links libc++ statically and needs nothing.
See [Android notes](#android-notes) for the measurement.

**Why the platform tables rather than `[project] dependencies`.** fiona publishes desktop
wheels, but only through CPython 3.13: PyPI carries 25 files for 1.10.1 — 24 wheels tagged
cp38 to cp313 across `macosx_10_15_x86_64`, `macosx_11_0_arm64`, `manylinux_2_17_x86_64`
and `win_amd64`, plus `fiona-1.10.1.tar.gz`. There is no cp314 wheel. Flet
[appends](https://flet.dev/docs/publish/#app-dependencies)
`[tool.flet.<platform>].dependencies` to the project list rather than replacing it, so a
top-level `"fiona"` is *also* handed to the host resolve `flet build` runs first — and on a
3.14 interpreter that resolve falls through to the sdist, which learns where GDAL is only
by shelling out to `gdal-config`. Measured on CPython 3.14.6 with `gdal-config` off `PATH`,
`uv sync` of `flet==0.86.5` plus `fiona==1.10.1` failed with ``Call to
`setuptools.build_meta.build_wheel` failed``, `Failed to get options via gdal-config:
[Errno 2] No such file or directory: 'gdal-config'` and `A GDAL API version must be
specified.` On a machine that happens to have a system GDAL it instead quietly builds a
*host* fiona from that sdist — a wheel no device will ever load, and one that then sits in
the resolver's cache: repeating the same `uv sync` on this machine, which has a Homebrew
`gdal-config`, succeeded in 28 ms off a cached `fiona-1.10.1-cp314-cp314-macosx_11_0_arm64`
wheel, and only `--no-cache` produced the failure above. The tables keep fiona out of that
resolve entirely.

The cost is worth stating plainly: **fiona is then absent from `flet run` on your desktop
and from a web build**, because nothing outside a `flet build` for Android or iOS reads
those tables, and `import fiona` raises `ModuleNotFoundError` everywhere you develop. Guard the import so
those runs explain themselves instead of crashing — the
[`feature-roundtrip`](examples/feature-roundtrip) example renders a card naming the missing
module. If you pin fiona to a version whose desktop wheels cover your interpreter, a
top-level entry works too; the platform tables are the shape that keeps working as Python
moves on.

The requirements come along without configuring. **`attrs`**, **`certifi`**, **`click`**,
**`click-plugins`** and **`cligj`** are pure Python and resolve from PyPI. The native side
is the recipe's: both wheels require **`flet-libgdal`** (3.13.1), and the iOS wheel
additionally requires **`flet-libjpeg`** (3.0.90). `flet-libgdal` requires
**`flet-libproj`** (9.5.0), which requires **`flet-libtiff`** (4.7.0) and
**`flet-libcurl`** (8.11.0); `flet-libtiff` requires **`flet-libjpeg`** (3.0.90) and
`flet-libcurl` requires **`flet-libpsl`** (0.21.5). Only Android loads any of them at
runtime — see
[Android notes](#android-notes) and [iOS notes](#ios-notes).

Nothing else to configure: no
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry and no loader shim. The Android wheel's 65 entries are 40 `.py`, eight `.so`, ten
Cython `.pxd`, one `.pxi` and six `dist-info` files — **no data file of any kind**, on
either platform — and a grep across every `.py` for `__file__`, `importlib.resources`,
`pkgutil`, `pkg_resources`, `ctypes`, `find_library`, `sys.platform`, `platform.system`,
`os.name` or `inspect.getsource` returns six lines, all inert here: three
`sys.platform == "win32"` guards in `_path.py` and `vfs.py`, `platform.system()` in
`_show_versions.py`'s printout, and a `platform.system() == "Windows"` block at
`fiona/__init__.py` line 31 that is the package's only use of `__file__`.

`Requires-Python` is `>=3.8`, so fiona imposes no floor of its own on your app. Nineteen
wheels ship at the current build number: Python 3.12, 3.13 and 3.14 × three Android ABIs
(arm64-v8a, armeabi-v7a, x86_64) and three iOS slices (device, arm64 simulator, x86_64
simulator), plus a legacy 32-bit `android_24_x86` slice on 3.12 only. No architecture is
excluded.

Leave Flet's default
[compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) on. Of
the 2,453,506 bytes an Android arm64-v8a wheel unpacks to, 237,053 are `.py` that become
`.pyc` and 43,542 are Cython `.pxd` headers cleanup deletes outright. One file slips
through: `serious_python`'s junk-file globs list `**.pxd` and not `**.pxi`, so
`fiona/gdal.pxi` (35,961 bytes) ships to the device for nothing. Nothing here reads its own
source, so compiling is safe.

## Storage

Vector files belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, durable and included in backups. It has to be a **writable** directory
rather than a bundled asset: OGR writes the dataset in place, and reopening one for writing
rewrites it.

**Give each dataset its own subdirectory**, because a Shapefile is not one file. Writing a
point layer with no CRS left `layer.shp`, `layer.shx`, `layer.dbf` and `layer.cpg`, and a
fifth file `layer.prj` appeared as soon as a CRS was supplied. Copy, move, back up or
delete them as a unit, and note that losing one **does not raise**: with the `.dbf`
deleted, `fiona.open(path)` still opened the layer and still returned the right geometry,
but the schema came back `{'properties': {}, 'geometry': 'Point'}` and every feature's
`properties` was empty. A half-copied Shapefile reads as a layer with no attributes rather
than as an error.

Avoid
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it) and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) for anything you want to keep.

### No `proj.db` and no `GDAL_DATA`, on either platform

`unzip -l` over the fiona wheels finds nothing matching `proj`, `share/`, `.db`,
`gdal_data` or `data` beyond the `dist-info` entries, and `flet-libgdal` is 102 headers
plus one library (`opt/lib/libgdal.so`, 13,997,320 bytes, on Android; a 524,528,736-byte
`opt/lib/libgdal.a` on iOS) plus a 2,787-byte `opt/lib/gdalplugins/drivers.ini`. The
diagnostics for the gap are compiled into the shipped binaries: `strings -a` finds *Cannot
find proj.db* and *Cannot find %s (GDAL_DATA is not defined)* in Android's `libgdal.so` and
in each of the iOS `_env`, `ogrext` and `crs`. Both native recipes end their build with
`rm -rf $PREFIX/{bin,share}`, which is where those files would have come from —
[`rasterio`](../rasterio), [`gdal`](../gdal) and [`pyproj`](../pyproj) sit on the same
chain and lose the same files.

**fiona's vector half is not crippled by it.** Reproducing the device's data situation on a
desktop — fiona 1.10.1 from PyPI with `GDAL_DATA`, `PROJ_DATA` and `PROJ_LIB` all pointed
at an empty directory — gave:

- `import fiona` **succeeds**.
- Writing features to GeoJSON and to an ESRI Shapefile with **no CRS** and reading them
  back **works**: 0 geometry-type mismatches and 0 integer or string property mismatches on
  both, worst coordinate residual 1.42e-14 through GeoJSON (a text format) against exactly 0
  through the Shapefile, worst float-property residual 0 and 4.44e-16 respectively.
- The GeoJSON reads back tagged `CRS.from_wkt('GEOGCS["WGS 84", …AUTHORITY["EPSG","4326"]]')`
  from the driver's own compiled-in string; the Shapefile reads back `CRS.from_wkt('')`.
- [`CRS.from_epsg(4326)`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.crs.CRS.from_epsg)
  raises `fiona.errors.CRSError: The EPSG code is unknown. PROJ:
  internal_proj_create_from_database: Cannot find proj.db`, and
  [`CRS.from_string("EPSG:4326")`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.crs.CRS.from_string)
  raises the same — the string form is not a way around it.
- `CRS.from_string("+proj=longlat +datum=WGS84 +no_defs")` **works**, but `to_string()` then
  returns `GEOGCS["unknown", …]` rather than `"EPSG:4326"`, because naming a CRS means
  identifying it against the authority database. With the database present the same call
  returns `"EPSG:4326"`.

So: write CRSes as proj-strings or WKT and everything works with nothing supplied, which is
what the [`feature-roundtrip`](examples/feature-roundtrip) example does. What you give up is
discovery — you have to know the projection parameters, because nothing on device will name
them for you.

**The device then reproduced those numbers exactly**, which is the reason to trust the
desktop recipe above as a proxy. On the arm64-v8a emulator on 2026-08-19, at 200 features
per layer: worst coordinate residual 1.42e-14 through GeoJSON and 0 through the Shapefile,
worst float-property residual 0 and 4.44e-16 respectively, 0 type, 0 integer and 0 string
mismatches on all four layers — the same figures the empty-directory desktop run gave, to
every digit. `CRS.from_string("+proj=longlat +datum=WGS84 +no_defs")` succeeded on device
and `CRS.from_epsg(4326)` failed on both platforms, on Android naming `proj.db` outright
(`CRSError: The EPSG code is unknown. PROJ: proj_create_from_database: Cannot find
proj.db`) and on iOS reporting only `The wrapped function returned an error code, but no
error message was set.` Android also logs `Cannot find header.dxf (GDAL_DATA is not
defined)` to logcat at startup; both messages are expected here and neither stops the app.

### Getting EPSG codes back

`fiona._env.set_proj_data_search_path(path)` exists in the shipped wheel, and `GDALEnv.start`
honours `PROJ_DATA` from the environment, then `PROJ_LIB`, then
`PROJDataFinder().search_wheel()` — which looks for a `fiona/proj_data` directory these
wheels do not ship. So the lever is there: ship a `proj.db` as an asset and point fiona at
the directory holding it, with
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
naming where a bundled `src/assets/` lands on device.

**That has not been run on a device for this recipe**, and on iOS there is a second reason
for caution: both the function and the environment-variable branch execute inside
`fiona/_env`, while `fiona/crs` is a separate extension carrying its own statically linked
PROJ — the string `Rel. 9.5.0, September 15th, 2024` appears independently in the iOS
`_env`, `ogrext`, `crs`, `_geometry` and `_transform` — so a database supplied through
`_env` is not the one `fiona.crs` would read there. On Android there is one `libproj.so`
and the question does not arise.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`feature-roundtrip`](examples/feature-roundtrip) — a GeoJSON and a Shapefile written to
  app storage, then read back and compared geometry by geometry and property by property
  against the records they came from.

## Threading

**Two threads must not share one `Collection`, and getting it wrong loses data without
raising anything.** Measured on a desktop fiona 1.10.1: eight threads each iterating the
same open `Collection` five times returned the correct feature count on only 15, 18 and 20
of 40 iterations across three runs — and raised **zero** exceptions. Giving each thread its
own `fiona.open` returned 40 of 40 correct on each of three runs.

That is worse than it sounds under
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), which
submits to a shared pool, so two taps really do overlap — and which never retrieves the
worker's future, so even a raised exception would surface nowhere. Open one `Collection`
per thread (what the example does: its worker opens and closes every `Collection` inside
the thread that uses it) or hold a `threading.Lock` around the whole use, **including
consuming the iterator** — a half-read `Collection` is still an open handle.

**There is no per-thread environment to enter by hand.** `fiona/env.py` keeps its `GDALEnv`
in a `threading.local` subclass, and `fiona.open` carries the `@ensure_env_with_credentials`
decorator, so a worker thread that calls `fiona.open` gets its own environment created and
its drivers registered with no preamble. Entering an explicit
[`fiona.Env()`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.env.Env) around a
call adds nothing to that.

Auto-update does not reach background threads either, so end a `run_thread` handler with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Android notes

**GDAL stays one shared library, and there is one driver table.** All eight extensions name
exactly `libm.so`, `libgdal.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` in
`DT_NEEDED` — plus `libc++_shared.so` on `_transform` and nowhere else — with no `RUNPATH`
and no `RPATH`, and every `PT_LOAD` segment reports `align 0x4000`, the 16 KB page
alignment Android 15 requires. Every GDAL and OGR symbol the extensions use is undefined
and resolved at load: `_env` imports `GDALAllRegister` and `OGRRegisterAll`, `ogrext`
imports 20 `GDAL*` and 56 `OGR*` entry points including `GDALGetDriverByName`, `GDALOpenEx`
and `GDALCreate`, and **`ogrext` defines no GDAL or OGR symbol of its own**. `libgdal.so`
carries `SONAME libgdal.so` and names `libm.so`, `libdl.so`, `libproj.so` and `libc.so`.

| slice (cp314) | wheel | unpacked | fiona `.so` |
| --- | --- | --- | --- |
| arm64-v8a | 893,120 | 2,453,506 | 2,128,416 |
| armeabi-v7a | 806,730 | 1,779,666 | 1,454,576 |
| x86_64 | 946,971 | 2,536,143 | 2,211,064 |

Behind those 2.1 MB sits the shared native chain, which on arm64-v8a is `libgdal.so` at
13,997,320 bytes plus `libproj.so` 4,640,656, `libturbojpeg.so` 748,184, `libtiff.so`
744,048, `libcurl.so` 723,712, `libjpeg.so` 589,784 and `libpsl.so` 67,488 — 21,511,192
bytes of shared library.

**`import fiona.transform` may fail, and only that import.** `_transform` is the one
extension whose `DT_NEEDED` names `libc++_shared.so`, and fiona's Android `METADATA`
declares only `flet-libgdal`, where the Android wheels of [`gdal`](../gdal) 3.13.1 and
[`rasterio`](../rasterio) 1.5.0 both additionally declare
`flet-libcpp-shared (>=27.2.12479018)`. Nothing else in fiona's chain declares it either,
and Flet does not supply one: of the `serious_python_android` releases 4.2.1 through 4.5.1
in this machine's pub cache, none ships a `libc++_shared.so`.

**Measured on 2026-08-19, and it does fail.** On an arm64-v8a Android 14 emulator, with
`fiona` as the only Android dependency, `import fiona.transform` raises:

```
ImportError: dlopen failed: library "libc++_shared.so" not found:
needed by /data/app/~~…/lib/arm64-v8a/libfiona-_transform.so in namespace clns-6
```

**The fix is one line, and it was verified on the same emulator.** Name the runtime beside
fiona:

```toml
[tool.flet.android]
dependencies = ["fiona==1.10.1", "flet-libcpp-shared"]
```

That puts `libc++_shared.so` into all three ABI slices of the APK — 1,292,904 bytes on
arm64-v8a, 872,872 on armeabi-v7a, 1,252,080 on x86_64 — and `import fiona.transform` then
succeeds, with the four round trips unaffected. The
[`feature-roundtrip`](examples/feature-roundtrip) example declares it for that reason and
still probes the import in its own `try/except`, so the failure stays visible if you drop
the dependency.

The recipe itself should arguably declare `flet-libcpp-shared` the way `gdal` and
`rasterio` do, which would make the extra line unnecessary; until a wheel ships that way,
add it yourself.

**Plain `import fiona` is not exposed to that**, and this is worth spelling out because the
opposite is easy to assume. `libgdal.so` leaves 215 C++ runtime symbols undefined — 200
mangled `_Z…` entries of which 112 are `_ZNSt6__ndk1…`, plus thirteen `__cxa_*`,
`__gxx_personality_v0` and `__dynamic_cast` — and sets `DT_FLAGS = 8` (`DF_BIND_NOW`) and
`DT_FLAGS_1 = 1` (`DF_1_NOW`), so nothing binds lazily. It resolves them without
`libc++_shared.so`: `libproj.so`, which it names in `DT_NEEDED`, statically links libc++ and
defines 828 symbols of that shape, covering 212 of the 215, and the remaining three
(`__cxa_atexit`, `__cxa_finalize`, `__cxa_thread_atexit_impl`) are defined by bionic's own
`libc.so`. `import fiona` loads seven of the eight extensions and not `_transform`.

## iOS notes

**There is no shared library at all, and the driver table splits.** `flet-libgdal` ships
only `libgdal.a`, and the link pulls a full copy of GDAL into five of the eight extensions:
`ogrext` (25,158,696 bytes on the device slice), `_env` (25,085,416), `crs` (24,548,496),
`_geometry` (24,410,968) and `_transform` (24,336,152), against `_vsiopener` (1,256,432),
`_err` (1,015,264) and `schema` (270,840). All eight are `MH_DYLIB`, so forge's
`MH_BUNDLE` conversion has nothing to do, and `otool -L` on `ogrext` names only its own
install name, `@rpath/Python.framework/Python`, `/usr/lib/libsqlite3.dylib`,
`/usr/lib/libz.1.dylib` and `/usr/lib/libSystem.B.dylib` — no libproj, libtiff or libcurl,
because those are already inside it.

**And that is where fiona breaks.** `nm` on the shipped iOS binaries says:

- `_env` **defines** `GDALAllRegister`, `OGRRegisterAll` and all eleven registration entry
  points — `GDALRegister_GTiff`, `_COG`, `_MEM`, `_VRT`, `RegisterOGRShape`,
  `RegisterOGRGeoJSON`, `RegisterOGRGeoJSONSeq`, `RegisterOGRESRIJSON`,
  `RegisterOGRTopoJSON`, `RegisterGNMFile` and `RegisterGNMDatabase` — and imports none of
  them.
- `ogrext` defines its **own** `GetGDALDriverManager`, `GDALGetDriverByName`,
  `OGRGetDriverByName`, `GDALOpenEx` and `GDALCreate`, and imports no GDAL or OGR symbol at
  all (790 undefined symbols, none of them `GDAL*`, `OGR*`, `OSR*`, `CPL*` or `VSI*`). It
  contains **no symbol whose name matches `RegisterOGR`, `GDALAllRegister` or
  `OGRRegisterAll` at any binding, local or global** — the linker did drag in four
  `GDALRegister_*` entry points (`GTiff`, `COG`, `VRT`, `MEM`), but disassembling every
  branch in its `__text` finds exactly one call to any of them, `GDALRegister_VRT` from
  `VRTDataset`'s constructor, which nothing fiona does can reach. So the table stays empty
  in practice as well as by name. `crs`, `_geometry` and `_transform` are in the same state.
- `otool -hv` reports every image `TWOLEVEL`, so none of them can bind another's copy.

`fiona.Env()` registers drivers in `_env`. `fiona.open` resolves a driver name in `ogrext`.
On Android those are one shared `libgdal.so` and the distinction is invisible; on iOS they
are separate tables, and nothing ever registers a vector driver into the one `fiona.open`
reads. There is no app-side fix — `ogrext` exposes no registration entry point Python can
call, and entering an explicit `fiona.Env()` only registers into `_env` again.

**This was run on an iPhone 16 simulator (iOS 18.6) on 2026-08-19, and the binaries called it
exactly.** The write raises `FionaNullPointerError: NULL pointer error` — the class and
message predicted from `ogrext.pyx` line 1365,
`exc_wrap_pointer(GDALGetDriverByName(driver_c))`, with `_err.pyx` raising that class when
the pointer is NULL and GDAL set no message. It happens twice, once for GeoJSON and once
for ESRI Shapefile, and the display above it reads the registry out of `_env` in the same
breath: `driver_count()` 17, `Env().drivers()` six including `MEM`. The read half of the
prediction — `fiona.errors.DriverError: Failed to open dataset (flags=68): <path>` — was
never reached, because there is nothing to read after a write that could not start; treat
that one as still untested.

Android, run the same day on an arm64-v8a emulator, is the control: identical driver
counts, and 200 Point plus 200 Polygon features out and back through both drivers — four
layers, each reading back 200 of 200 with 0 type, 0 integer and 0 string mismatches. Same
wheel, same code path, same registry numbers, opposite outcome — which is what a
per-extension driver table looks like from the outside.

The same split is what breaks [`rasterio`](../rasterio) on iOS, and that one *has* been
measured: on 2026-08-19, while that recipe was being documented, its example wrote and read
back a GeoTIFF on an arm64 Android emulator with 0 pixels differing, and failed both halves
on an iPhone simulator, where `rasterio.open(…, "w", driver="GTiff")` raised
`DriverRegistrationError`.
**The alternative on iOS is [`gdal`](../gdal)'s `osgeo.ogr`**, whose registration and
lookups share one image: `osgeo/ogr.py` has 638 lines referencing `_ogr` and none
referencing any other extension, the iOS `_ogr` defines `OGRGetDriverByName`,
`GDALGetDriverByName` and `GDALOpenEx`, and — the part that matters — its module init
*calls* the registration: `PyInit__ogr` in the shipped `_ogr.cpython-314-iphoneos.so`
contains a `bl _OGRRegisterAll`. Defining is not calling, which is precisely why `ogrext`
having four registration functions of its own buys fiona nothing. What has *not* been shown
is a vector layer written on a device: the iOS measurement behind that recommendation is
raster, `osgeo.gdal` round-tripping a 512×512 GeoTIFF on the iPhone simulator on
2026-08-19 with 0 of 262,144 pixels differing. Treat `osgeo.ogr` as the structurally sound
bet, not as a settled one — and note it is not free, since `osgeo/__init__.py` imports
`_gdal` and `osgeo/ogr.py` imports `osr`, so the three iOS extensions together are
76,930,728 bytes. `gdal` also has to go under `[tool.flet.android]`/`[tool.flet.ios]`, for
a different reason than fiona's: upstream publishes no desktop wheel at all.

| slice (cp314) | wheel | unpacked | fiona `.so` |
| --- | --- | --- | --- |
| arm64 (device) | 44,856,928 | 126,407,304 | 126,082,264 |
| arm64 (simulator) | 46,211,443 | 127,966,519 | 127,641,416 |
| x86_64 (simulator) | 49,329,823 | 135,331,488 | 135,006,384 |

`flet-libgdal` contributes nothing executable here — its 112,772,601-byte iOS wheel is that
half-gigabyte `libgdal.a` plus headers, which Flet's cleanup deletes — but the build machine
still downloads and unpacks three of them. Expect a slow first `ipa` or `ios-simulator`
build and plenty of free disk; nothing to configure.

SQLite differs too: Android's `libproj.so` names Flet's `libsqlite3_python.so` in
`DT_NEEDED`, while every iOS extension binds the system `/usr/lib/libsqlite3.dylib`.
Whichever `proj.db` an app supplies is read by that one.

The `libc++_shared.so` question in [Android notes](#android-notes) has no iOS counterpart:
`_transform` is again the only extension needing a C++ runtime, and here `otool -L` shows it
binding `/usr/lib/libc++.1.dylib`, an OS library present on every device, where the other
seven bind none.

## Things to know

- **Six vector drivers are registered; fiona can reach five of them, three writable.** This
  GDAL registers eleven drivers in all — `GTiff`, `COG` and `VRT` (raster only), `MEM`
  (raster *and* vector), the five vector drivers `ESRI Shapefile`, `GeoJSON`, `GeoJSONSeq`,
  `ESRIJSON` and `TopoJSON`, and the two network drivers `GNMFile` and `GNMDatabase`. That
  list is exhaustive: `GDALAllRegister` in Android's `libgdal.so` and in the iOS `_env`
  calls exactly those eleven registration functions and nothing else. Which of them OGR
  will show you is decided by the `DCAP_VECTOR` metadata each one sets, and
  `OGRGetDriverCount`/`OGRGetDriver` — the pair `fiona.Env().drivers()` loops — filter on
  precisely that string. `GDALRegister_MEM` sets `DCAP_VECTOR`, `DCAP_CREATE_LAYER`,
  `DCAP_DELETE_LAYER` and `DCAP_CREATE_FIELD` on both platforms and calls itself *In Memory
  raster, vector and multidimensional raster*, so **`env.drivers()` returns six names, not
  five** — the sixth is `MEM`. `GNMFile` and `GNMDatabase` set only `DCAP_GNM` and do not
  appear. fiona cannot use `MEM` regardless: its static table in `fiona/drvsupport.py` has
  no `MEM` entry at all (the old `Memory` name survives only as a comment there), so it
  never enters `fiona.supported_drivers` and `fiona.open(..., driver="MEM")` raises
  `fiona.errors.DriverError: unsupported driver: 'MEM'` before any native call. Of the five
  fiona does keep, its mode table marks `ESRI Shapefile`, `GeoJSON` and `GeoJSONSeq` as
  `raw` (read, append, write) and `ESRIJSON` and `TopoJSON` as `r`. **No GPKG, no SQLite,
  no GML, no GPX, no CSV, no FlatGeobuf, no DXF, no OpenFileGDB, no MapInfo, no DGN and no
  S57** — convert those off-device. Ask both lists rather than trusting either alone:
  `with fiona.Env() as env: env.drivers()` is OGR's vector-capable subset of the registry,
  `fiona.supported_drivers` is what `fiona.open` will accept, and they differ by `MEM`.
  Because `MEM` carries both capability flags, a raster-side census of this same
  `flet-libgdal` counts it among four raster drivers and this one counts it among six
  vector drivers: eleven registrations, counted twice from two sides. A listing taken
  through `GDALGetDriverCount` — which references no `DCAP_*` string at all — returns all
  eleven, so a driver count from a raster package against this same library is not
  comparable with this one.
- **`fiona.driver_count()` is not the number of drivers you can use.** It is
  `GDALGetDriverCount() + OGRGetDriverCount()` evaluated inside `fiona._env`, so it counts
  every registered driver plus the vector-capable ones a second time. It read 124 on a
  desktop where `fiona.supported_drivers` held 17 names and `Env().drivers()` held 55. Read
  it off a device rather than reasoning from it; the
  [`feature-roundtrip`](examples/feature-roundtrip) example prints it.
- **`fiona.supported_drivers` is filtered at import — against the wrong table on iOS.**
  `fiona/drvsupport.py` runs `_filter_supported_drivers()` at module scope, which intersects
  fiona's static table with `Env().drivers()`, and that is `fiona._env.drivers()` looping
  `OGRGetDriverCount()` inside `_env`. On Android that is the same registry `fiona.open`
  uses. On iOS it is not, so an app that checks the driver list before writing gets a green
  light from a table `fiona.open` never consults.
- **`FionaNullPointerError` is not a `FionaError`.** `fiona/_err.pyx` defines
  `class FionaNullPointerError(CPLE_BaseError)` and `class CPLE_BaseError(Exception)`, with
  no relation to anything in `fiona/errors.py`; the measured MRO is `FionaNullPointerError →
  CPLE_BaseError → Exception`, and `isinstance(err, fiona.errors.FionaError)` is `False`.
  `except fiona.errors.FionaError` will not catch it, and an uncaught exception in a Flet
  handler ends the session with a crash screen. Catch bare `Exception` around fiona calls
  and render `type(err).__name__` alongside `str(err)`.
- **Always pass `driver=` explicitly when writing.** Left out,
  [`fiona.open`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.open) calls
  [`driver_from_extension`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.drvsupport.driver_from_extension),
  which builds its extension map by asking every driver in `supported_drivers` for its
  metadata through `fiona.ogrext._get_metadata_item`, and that function raises
  `FionaValueError: Could not find driver '<name>'` the moment `GDALGetDriverByName` returns
  NULL — so on iOS the convenient form fails inside the empty table before it ever reaches
  your file. The three messages you can see today, all measured on a desktop: an
  unrecognised extension gives `ValueError: Unable to detect driver. Please specify
  driver.`; a driver name absent from `supported_drivers` gives `fiona.errors.DriverError:
  unsupported driver: 'NoSuchDriver'` before any native call; opening a file that is not
  there gives `fiona.errors.DriverError: Failed to open dataset (flags=68): <path>`.
- **A round-tripped schema is not the schema you wrote**, so `src.schema == schema` is the
  wrong check. Writing `{"name": "str", "n": "int", "v": "float"}` read back as
  `{"name": "str", "n": "int32", "v": "float"}` from GeoJSON and
  `{"name": "str:80", "n": "int:18", "v": "float:24.15"}` from a Shapefile. The *values*
  round-tripped in both — worst residual 4.44e-16 on the floats — and coordinates came back
  as `tuple`, not `list`. Compare feature values element by element and treat the schema as
  information.
- **A Shapefile holds one geometry type and rewinds your rings.** A layer declared
  `Unknown` whose first feature is a Point becomes a point shapefile, and the next feature
  raises `RuntimeError: GDAL Error: Attempt to write non-point (LINESTRING) geometry to
  point shapefile.`; GeoJSON takes the mixture happily. Separately, an outer ring written
  counter-clockwise comes back with its vertices reversed, because the format fixes the
  winding order — measured on a desktop, a clockwise ring round-tripped identical through
  both drivers and the same ring counter-clockwise survived GeoJSON but not the Shapefile.
  Keep field names to ten characters or fewer while you are at it: DBF truncates silently,
  and a property written as `a_very_long_name` came back keyed `a_very_lon`.
- **`click`, `click-plugins` and `cligj` arrive as requirements and nothing you import uses
  them.** They exist for the `fio` console script: `import click` appears in 15 files, all
  of them under `fiona/fio/`, and `fiona/__init__.py` never imports `fiona.fio`. That
  subpackage is 53,196 bytes across 17 files.
- **`certifi` is different: it is imported on every `import fiona`.** The call is not in any
  `.py` — it is compiled into `fiona/_env`, which does `import certifi` at module scope and
  puts `certifi.where()` into `GDAL_CURL_CA_BUNDLE` and `PROJ_CURL_CA_BUNDLE`; the strings
  `certifi`, `GDAL_CURL_CA_BUNDLE` and `PROJ_CURL_CA_BUNDLE` are all in the shipped Android
  `_env.cpython-314-aarch64-linux-android.so`. Two consequences. `certifi.where()` needs a
  real filesystem path for `certifi/cacert.pem` (240,216 bytes at certifi 2026.7.22, and
  nothing pins it), so if your site-packages
  are zipped it is unpacked to a temporary file at import — the one data file in fiona's
  dependency tree that gets touched, and the reason the *no data file* finding above is
  about fiona's own wheel and not about the whole install. And the GDAL half of it is dead
  weight: this `libgdal` has no libcurl, so nothing reads `GDAL_CURL_CA_BUNDLE`. Do not drop
  `certifi` from a lockfile on the theory that fiona only declares it — the `try/except`
  around the import catches `ImportError` only.
- **GEOS is not compiled in and neither is libcurl.** Android's `libgdal.so` and the iOS
  extensions all carry the diagnostics *GEOS support not enabled.* and *GDAL/OGR not
  compiled with libcurl support, remote requests not supported.*, and `libgdal.so`'s
  dynamic symbol table holds no `GEOS*` and no `curl_*` symbol at all, defined or
  undefined. So OGR geometry predicates and operations are unavailable — use
  [`shapely`](../shapely) for those — and `/vsicurl/`, `/vsis3/`, `/vsigs/` and `/vsiaz/`
  are dead, which leaves fiona's `session` module nothing to drive. (`flet-libcurl` still
  installs on Android because `libproj.so` names it in `DT_NEEDED`.)
- **Your desktop is not a preview of the device.** `flet run` cannot see fiona at all with
  the install shape above, and a desktop fiona installed by hand is a different package:
  PyPI's macOS wheel bundles its own GDAL — 3.9.2, against 3.13.1 here — and its own
  `proj_data`, and reported 17 entries in `supported_drivers`, 55 from `Env().drivers()`
  and a working `CRS.from_epsg(4326)`. Twelve of those 17 — `CSV`, `DGN`, `DXF`,
  `FlatGeobuf`, `GML`, `GPKG`, `GPX`, `MapInfo File`, `OGR_GMT`, `OpenFileGDB`, `S57` and
  `SQLite` — are absent from the mobile registry. To approximate the device's *data*
  situation locally, run with `GDAL_DATA`, `PROJ_DATA` and `PROJ_LIB` pointed at an empty
  directory; that is how the CRS findings in [Storage](#storage) were established. It will
  not show you the driver set, and on iOS it will not show you the split.
- **Size.** Android arm64-v8a: an 893,120-byte wheel unpacking to 2,453,506, of which
  2,128,416 is the eight extensions, on top of 21,511,192 bytes of shared `flet-lib*`
  libraries. iOS device: a 44,856,928-byte wheel unpacking to 126,407,304, of which
  126,082,264 is the same eight extensions and nothing else installs. `import fiona` maps
  seven of the eight — everything but `_transform` — which is 2,026,280 bytes on Android
  arm64-v8a against 101,746,112 on the iOS device slice, **50× the native bytes for the same
  function**, before you touch a file. There is nothing a consumer can configure.

## Build notes (maintainers)

Two recipes: `flet-libgdal` builds GDAL, this one consumes it. `patches/mobile.patch`
explains its own hunks and `meta.yaml` comments the Android/iOS `GDAL_LIBS` split next to
it, so what is left here is shape and the bump checklist.

**Almost everything this page warns about is a `flet-libgdal` decision, not a fiona one.**
The eleven-driver registry, the missing `GDAL_DATA` and `proj.db`, the absent GEOS and
libcurl and the iOS static-only link all come from that recipe and from `flet-libproj`. A
`flet-libgdal` bump can invalidate most of this README without a line changing here — which
is why the version pin in `meta.yaml` is exact. Bump the two together and re-read the claims
off the built wheels.

**The iOS driver split is the one that matters, and it is a linking artefact.** `GDAL_LIBS`
names the whole static chain because `libgdal.a` leaks undefined symbols, and that is what
drags a full GDAL — including its global driver table — into five of the eight extensions.
Aligning `flet-libgdal`'s iOS CMake with Android's would let `GDAL_LIBS` drop back to `gdal`
and would rewrite the [iOS notes](#ios-notes), both size tables and the Android-only
recommendation at the top of this page in one go. It is the highest-value fix available to
this recipe.

What to re-verify on a bump — a green build establishes almost none of what this page
claims:

- **The Android `flet-libcpp-shared` gap.** `recipes/gdal/meta.yaml` and
  `recipes/rasterio/meta.yaml` both add `flet-libcpp-shared >=27.2.12479018` under
  `{% if sdk == 'android' %}` and this recipe does not, yet `_transform.so` carries
  `DT_NEEDED libc++_shared.so`. Note that `libgdal.so` itself does **not** need it — its 215
  undefined C++ symbols are covered by `libproj.so`'s statically linked libc++ (212) and
  bionic `libc.so` (3) — so the gap costs exactly `import fiona.transform` and nothing else.
  Add the host requirement, or establish on a device that it is genuinely unnecessary.
- **`tests/test_fiona.py` records the wrong cause for its iOS skip.**
  `test_write_read_geojson` skips iOS on the grounds that OGR's GeoJSON writer calls PROJ to
  stamp WGS84 and fails with *Cannot find proj.db*. Two things refute that: `ogrext.pyx`
  touches OSR only inside `if col_crs:`, so a CRS-less write never enters PROJ there; and a
  desktop run with `GDAL_DATA`, `PROJ_DATA` and `PROJ_LIB` all pointed at an empty directory
  wrote and read back both a GeoJSON and a Shapefile intact. The exception class the skip
  names is right; the reason is not — it is the driver-table split.
- **The tests assert almost nothing about this build.** `test_supported_drivers` checks two
  names in a dict `_filter_supported_drivers()` built from `_env`'s registry, which is
  exactly the table that is *not* in question on iOS. Worth adding: an assertion over the
  exact six driver names `fiona.Env().drivers()` returns — the five OGR ones plus `MEM`,
  which is registered with `DCAP_VECTOR` — so a driver appearing is as red as one
  vanishing; a write-read-compare through `fiona.open` with an explicit `driver=` and
  no CRS; an assertion that `CRS.from_epsg(4326)` raises `CRSError`; and an
  `import fiona.transform` that would catch a missing C++ runtime on Android.
- **The linkage split.** Android: `DT_NEEDED` still naming `libgdal.so` by bare soname,
  `libc++_shared.so` on `_transform` and nowhere else, `ogrext` still defining zero GDAL
  symbols, and 16 KB `PT_LOAD` alignment everywhere. iOS: still eight `MH_DYLIB`, still
  exactly five carrying GDAL, and `_env` still the only image with a `RegisterOGR*` in it.
  If iOS ever links dynamically, the [iOS notes](#ios-notes) and both size tables change
  together.
- **The driver set**, from the symbol tables on both platforms — Android's `libgdal.so` is
  stripped, so read it from dynamic symbols rather than `nm`. Two traps there. The exported
  `GDALRegister_*`/`RegisterOGR*` names are a superset of what is actually called: follow
  the `BL` targets out of `GDALAllRegister` instead, which is how the eleven above were
  fixed. And a name says nothing about vector capability — `MEM` registers with
  `DCAP_VECTOR` and shows up in `env.drivers()` — so read each registration function's
  `DCAP_*` strings, not its name.
- **The sizes are measured.** Re-measure rather than adjusting by eye; the 50× import
  footprint is the whole argument for budgeting 126 MB of extension on iOS.
- **The example is the live regression test, and the instrument for the open questions.**
  Bumping this recipe means bumping [`feature-roundtrip`](examples/feature-roundtrip)'s
  `fiona==` pin and rebuilding it on both platforms. Its sections map one-to-one onto the
  claims above, and the two things this page cannot settle — the iOS split and the Android
  C++ runtime — are the two it probes first.
