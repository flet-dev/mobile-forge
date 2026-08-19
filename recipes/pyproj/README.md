# pyproj

[`pyproj`](https://pyproj4.github.io/pyproj/stable/) is the Python interface to
[PROJ](https://proj.org/), the library underneath every GIS: it turns latitude and longitude
into metres on a map, converts one datum into another, and answers distance-and-bearing
questions on the WGS-84 ellipsoid. On a phone that is what stands between a GPS fix and a
coordinate anyone else can use — plotting a track on a national grid, showing metres rather
than degrees, or consuming survey data published in a projection your device knows nothing
about. It computes all of that in-process, with no network.

**Read [Storage](#storage) before you plan anything.** These wheels ship no `proj.db`, which
splits the library in half on device: the geodesic API works out of the box, and everything
touching a coordinate reference system raises until your app supplies a data directory. That
is one line of code and, for a large class of apps, zero bytes of payload — but it is not the
default and it does not announce itself.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pyproj",
]
```

Six wheels come along and none needs configuring. **`certifi`** is pure Python and absent
from this index, so it resolves from PyPI — `import pyproj` calls `certifi.where()` on the way
in; see [Things to know](#things-to-know). The other five are PROJ and its chain: the recipe
pins **`flet-libproj`** in `Requires-Dist` on both platforms (`flet-libjpeg` as well on iOS),
`flet-libproj` requires `flet-libtiff` and `flet-libcurl`, and those two require
`flet-libjpeg` and `flet-libpsl` in turn. Only Android loads any of them at runtime — on iOS
they are static archives that Flet's cleanup deletes; see [Android notes](#android-notes) and
[iOS notes](#ios-notes).

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed, and no loader shim. All 65 entries in the wheel are ten extensions, 20 `.py`
files, Cython sources and stubs, and `dist-info` — **no data file of any kind**. Across the
whole package there is exactly one occurrence of `__file__`, `importlib.resources`,
`pkgutil`, `pkg_resources`, `ctypes`, `find_library`, `sys.platform`, `platform.system()` or
`os.name`: `datadir.py:73`, which probes for a bundled data directory that is not there and is
*meant* to fail. All ten extension filenames carry a full CPython ABI tag, which is what
Android's relocation needs. The environment variables pyproj's own Python and Cython layer
reads are `PROJ_DATA`, `PROJ_LIB`, `PROJ_NETWORK`, `PYPROJ_GLOBAL_CONTEXT`,
`PROJ_CURL_CA_BUNDLE`, `CURL_CA_BUNDLE` and `SSL_CERT_FILE`.

Flet's default [compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup)
takes 26 files and 202,508 bytes off the payload — the `.pyx`, `.pxd`, `.pyi` and `py.typed`
files, none of which are read at runtime — and leaves the two `.pxi` (23,144 bytes), which are
also unused. Nothing here reads its own source, so compiling to `.pyc` is safe.

Nineteen wheels at the same build number: Python 3.12, 3.13 and 3.14 × three Android ABIs
(arm64-v8a, armeabi-v7a, x86_64) and three iOS slices (device, arm64 simulator, x86_64
simulator), plus a legacy 32-bit `android_24_x86` slice on 3.12, which flet-cli 0.86.5 cannot
target (its `ANDROID_ARCH_TO_FLUTTER_TARGET_PLATFORM` holds only `armeabi-v7a`, `arm64-v8a`
and `x86_64`). No arch is excluded. Upstream requires **Python 3.11 or newer**
(`Requires-Python: >=3.11` in the wheel `METADATA`), which never bites Flet's mobile runtime
but does mean your app's `requires-python` has to be at least `>=3.11` or `uv` fails the
resolve for the 3.10 split.

## Storage

**Neither these wheels nor `flet-libproj` contain `proj.db`, or any file under `share/proj`,
on either platform.** `unzip -l` lists 65 entries in each pyproj wheel with no `proj_dir/`
path, and the `flet-libproj` wheels are fifteen headers plus one library. This is not an
oversight you can work around by installing something else — it is the single most important
fact on this page, and everything below follows from it.

### What that costs, exactly

PROJ refuses to build a *context* until it can find a directory holding a file called
`proj.db`, and every `CRS`, `Proj`, `Transformer`, `database` and `network` call goes through
a context. So with nothing supplied:

- `import pyproj` **succeeds**, emitting `UserWarning: Valid PROJ data directory not found…`.
- [`Geod`](https://pyproj4.github.io/pyproj/stable/api/geod.html#pyproj.Geod) works in full —
  `inv`, `fwd`, `npts`, `inv_intermediate`, `line_length` and `polygon_area_perimeter` all
  returned answers with no data directory at all. Paris → London measured 343,915.771 m.
- **Everything else raises `pyproj.exceptions.DataDirError`**, including
  `CRS.from_epsg`, `CRS("EPSG:3857")`, `CRS("+proj=utm …")`,
  [`Proj`](https://pyproj4.github.io/pyproj/stable/api/proj.html#pyproj.Proj),
  `Transformer.from_crs`, `Transformer.from_pipeline`, `database.get_authorities()`,
  `datadir.get_data_dir()`, `network.is_network_enabled()` and `show_versions()`.

It fails loudly, which is the good news. The bad news is that it fails at the *first* CRS
call, not at import, and an unhandled exception in a Flet handler ends the session with a
crash screen.

### Giving PROJ a directory

Two routes, both verified to work when the wheel ships nothing — in the main thread and in
worker threads, which build their own PROJ context:

```python
os.environ["PROJ_DATA"] = data_dir       # before `import pyproj`
pyproj.datadir.set_data_dir(data_dir)    # any time after it
```

The environment variable has to be set before the import because pyproj resolves the
directory once, on its way through `pyproj/__init__.py`; setting it there also means the
lookup succeeds first time and no warning is emitted.
[`append_data_dir`](https://pyproj4.github.io/pyproj/stable/api/datadir.html#pyproj.datadir.append_data_dir)
adds a second directory without displacing the first — which is how you add grid files. PROJ
takes the *database* from the first entry in that list and treats the rest as search paths.

### Zero bytes: an empty `proj.db`

`get_data_dir()` checks nothing but that a file named `proj.db` **exists**. A zero-byte file
passes, and what that unlocks is the whole PROJ-string API:

- **Works:** `Proj(proj="utm", zone=33, ellps="WGS84")`, `CRS("+proj=…")` and `.to_proj4()`,
  `Transformer.from_crs(<proj-string>, <proj-string>)`, `Transformer.from_pipeline(...)`,
  `Geod`, `network.is_network_enabled()`.
- **Fails:** anything naming an authority — `CRS.from_epsg(4326)` and
  `Transformer.from_crs("EPSG:4326", "EPSG:3857")` raise
  `CRSError: Invalid projection: EPSG:4326: (Internal Proj Error: proj_create: no database
  context specified)`.
- **Costs:** one `UserWarning: pyproj unable to set PROJ database path.` each time a context
  is built.

The accuracy cost is nil, because a proj-string reproduces the authority definition exactly.
Measured against the same transforms run with the full database present, all three agreed
**bit for bit**: `+proj=merc +a=6378137 +b=6378137` with EPSG:3857 at Paris
(261845.70624393807, 6250564.349543124); `+proj=utm +zone=33 +datum=WGS84` with EPSG:32633 at
15°E 60°N (500000.0000000009, 6651411.190362714); and
`+proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 +x_0=400000 +y_0=-100000 +ellps=airy
+towgs84=446.448,-125.157,542.06,0.15,0.247,0.842,-20.489` with EPSG:27700 at London
(530042.625993872, 180380.44930295716). What you give up is discovery — you have to know the
parameters, and `CRS(code).name`, `.area_of_use` and the `database` module are all closed to
you. The [`control-points`](examples/control-points) example runs entirely this way.

The stub belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, durable, and a real filesystem path on both platforms — and creating it costs
`os.makedirs` plus `open(path, "ab").close()`.

### Nine megabytes: the real database

If you need EPSG codes, ship `proj.db` as an asset and point
[`set_data_dir`](https://pyproj4.github.io/pyproj/stable/api/datadir.html#pyproj.datadir.set_data_dir)
at the directory holding it, the way other recipes here ship a model file:

```python
pyproj.datadir.set_data_dir(os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "proj"))
```

Take it from the same-version PyPI wheel: `pyproj-3.7.2`'s macOS arm64 build carries
`pyproj/proj_dir/share/proj` as 16 files totalling 9,412,256 bytes, of which `proj.db` alone
is 9,273,344. **`proj.db` on its own is sufficient** — the other fifteen are init files, JSON
schemas and `proj.ini`, and the database is the only one `get_data_dir()` looks for. Copied
alone into an empty directory it resolved `CRS("EPSG:27700").name` to
`OSGB36 / British National Grid`, ran `EPSG:4326 → EPSG:3857` and `EPSG:4326 → EPSG:27700`,
and worked from a worker thread.

**The version skew is real and harmless.** PROJ validates the database's
`DATABASE.LAYOUT.VERSION.MAJOR`/`MINOR` and rejects a mismatch with *"It comes from another
PROJ installation"* (the diagnostic is in the shipped `libproj.so`). That database declares
layout 1.4 and `PROJ.VERSION 9.5.1`, while `flet-libproj` is PROJ **9.5.0** (`strings` on
`libproj.so`: *"Rel. 9.5.0, September 15th, 2024"*) — but 9.5.0 wants layout 1.4 as well, and
a PROJ 9.5.0 built from the same tarball the recipe fetches accepted that exact file:
`proj_context_set_database_path` returned success and `EPSG:4326` resolved. It is still the
one part of this arrangement nothing in CI exercises, so confirm it on the device you ship.

### Grid files, and the network

No transformation grid ships either, and most transforms do not need one. Where one *is*
wanted — datum shifts like OSTN15 for the British National Grid, or NADCON for NAD27 — PROJ
silently falls back to a lower-accuracy operation instead of failing, which is covered in
[Things to know](#things-to-know). If you need one, bundle it as an asset and
[`append_data_dir`](https://pyproj4.github.io/pyproj/stable/api/datadir.html#pyproj.datadir.append_data_dir)
its directory; the alternative is one of the two download paths below.

There are two independent download paths and **both are off unless you turn them on**:

- **PROJ's own fetcher** (libcurl, endpoint `https://cdn.proj.org`, string present in the
  shipped library) is compiled in on both platforms but defaults to off:
  `_context.pyx` reads `strtobool(os.environ.get("PROJ_NETWORK", "OFF"))` at import, and
  [`set_network_enabled`](https://pyproj4.github.io/pyproj/stable/api/network.html#pyproj.network.set_network_enabled)
  flips it afterwards.
- **pyproj's own downloader** —
  [`TransformerGroup.download_grids`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.TransformerGroup.download_grids)
  over `urllib.request.urlretrieve` in `sync.py` — ignores `PROJ_NETWORK` entirely.

Nothing else reaches out, and a Python `socket` stub is no way to establish that — PROJ's
fetcher is libcurl, underneath Python entirely. Point `PROJ_NETWORK_ENDPOINT` at a local HTTP
server that logs every hit instead: importing pyproj, building
`Transformer.from_crs("EPSG:4326", "EPSG:27700")`, transforming and reading
`TransformerGroup(...).best_available` made **zero requests**, while the same run with
`PROJ_NETWORK=ON` made one — `GET /uk_os_OSTN15_NTv2_OSGBtoETRS.tif` — which is what says the
probe would have seen a leak. That covers the C layer only; the Python one needs its own probe,
and a `sys.addaudithook` over the same sequence recorded zero `socket.connect`, `getaddrinfo` and
`urllib.Request` events, which is where `sync.py`'s `urlretrieve` would have shown up.
Turning the fetcher on is also not a safety net: when that fetch failed,
the transform returned `(inf, inf)` rather than falling back. A plane is fine; a phone with no
signal is fine.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`control-points`](examples/control-points) — coordinate maths that prints its own residuals,
  running off an empty `proj.db`.

## Threading

**`Transformer` and `CRS` objects are safe to share across threads, by design.** Both hold a
`threading.local` and rebuild their Cython object per thread on first use
(`transformer.py`'s `TransformerLocal`, `crs.py`'s `CRSLocal`), and PROJ contexts are
thread-local too (`_context.pyx` keys them off `PyThread_tss_*`). Eight threads driving one
shared `Transformer`, one shared `CRS` and one shared `Geod`, each over its own disjoint
slice of points so that a shared-state bug could not hide behind identical inputs, matched a
single-threaded reference element for element across 48,000 calls, with zero exceptions.

**The transform loop releases the GIL**, so a projection in a worker thread genuinely runs
beside the UI. A pure-Python counter thread, clocked strictly inside each call on a
development machine at 100,000 / 400,000 / 1,000,000 points: `Transformer.transform` let it
run at 35.5k / 34.6k / 33.4k ticks per ms, against 36.0k / 37.3k / 36.0k for an idle main
thread — the ceiling the harness can reach at all — 34.2k / 35.6k / 34.0k for `hashlib.sha256`
(releases the GIL) and 9.6k / 3.9k / 2.5k for `math.factorial` (holds it).

Two objects are explicitly *not* thread-safe, and pyproj's own docstrings say so: the
`Transformer`s and `CoordinateOperation`s handed out by
[`TransformerGroup`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.TransformerGroup)
(they wrap `TransformerUnsafe`, which skips the per-thread rebuild), and the one returned by
[`get_last_used_operation`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.Transformer.get_last_used_operation).
Use those on the thread that made them.

The standing Flet caveats apply on top:
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) never
retrieves the worker's future, so an exception inside one surfaces nowhere — wrap the body —
and auto-update does not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Android notes

**PROJ is a chain of shared libraries, resolved by bare soname.** All ten extensions list
exactly `libm.so`, `libproj.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` in
`DT_NEEDED` — no `libc++_shared.so` — with a `RUNPATH` pointing at a build-host directory that
does not exist on any phone. That is harmless: serious_python's Gradle `copyOpt` task
flattens every `.so` under a wheel's `opt/` into `jniLibs/<abi>/` under its plain basename,
and `libproj.so` carries `SONAME libproj.so`, so the loader resolves it from the APK.
`libproj.so` in turn names `libsqlite3_python.so` (from Flet's Python bundle), `libtiff.so`
and `libcurl.so`; `libtiff.so` names `libjpeg.so` and `libz.so`, and `libcurl.so` names
`libpsl.so`, `libssl_python.so`, `libcrypto_python.so` and `libz.so`.

That chain is **7,513,872 bytes of `.so` on arm64-v8a** — `libproj.so` 4,640,656,
`libturbojpeg.so` 748,184, `libtiff.so` 744,048, `libcurl.so` 723,712, `libjpeg.so` 589,784,
`libpsl.so` 67,488 — on top of pyproj's own 1,039,288. It is not the same on the other two:
5,227,468 bytes on armeabi-v7a and 8,347,680 on x86_64. Every `LOAD` segment in all of them,
across all three ABIs, reports `align 0x4000`, the 16 KB page alignment Android 15 requires.

## iOS notes

**PROJ is absorbed into the extensions instead — into eight of the ten, separately.**
`flet-libproj` ships `libproj.a` (7,553,816 bytes) and no shared library at all, and the link
pulls it into each extension that touches the database. `_context`, `_crs`, `_network`,
`_sync`, `_transformer`, `_version`, `database` and `list` each carry PROJ's version string,
its `cdn.proj.org` endpoint and its database-layout checks, and each weighs 9,273,576–9,702,872
bytes. `_compat` (103,792) and `_geod` (202,664) do not — the geodesic code is small and
self-contained. **Total: 75,347,880 bytes of extension on the device slice, against 1,039,288
on Android arm64-v8a**, and `import pyproj` loads all ten regardless, so an app that only wants
`Geod` pays it too. Budget for it; there is nothing a consumer can do.

All ten are `MH_DYLIB` (so forge's `MH_BUNDLE` conversion has nothing to do), and `otool -L`
on each lists only its own install name, `@rpath/Python.framework/Python`,
`/usr/lib/libsqlite3.dylib`, `/usr/lib/libz.1.dylib` and `/usr/lib/libSystem.B.dylib` — no
libcurl, no libtiff, no libc++. What is left over is 124 flat-namespace symbols in each of
those eight (`nm -m`; `_compat` and `_geod` have none) — the C++ runtime iOS supplies itself,
the same pattern [`shapely`](../shapely#ios-notes) documents. The static curl/OpenSSL/tiff
objects really are inside: `_context` *defines* `_SSL_connect`, `_TIFFClientOpen` and
`_psl_builtin` as text symbols.

SQLite differs too: Android's `libproj.so` links `libsqlite3_python.so` from Flet's Python
bundle, iOS binds the system `/usr/lib/libsqlite3.dylib`. Either way it is that SQLite which
opens whatever `proj.db` your app supplies. Also iOS-only: the wheel declares an extra
`flet-libjpeg` in `Requires-Dist`. Both it and `flet-libproj` ship nothing but `.a` archives
and headers on iOS, and serious_python's cleanup deletes every `**.a` and `**.h` — those
objects are already inside the extensions.

## Things to know

- **`import pyproj` succeeding proves nothing.** It succeeds when no data directory exists,
  with only a `UserWarning` to show for it, and nothing in your UI displays that. The failure
  surfaces at the first `CRS`/`Transformer` call, which is typically inside an event handler,
  where an unhandled exception gives you a crash screen rather than a message. Set the data
  directory at startup and wrap the first transform in `try/except Exception`.
- **`pyproj.show_versions()` raises on device.** It prints `pyproj info:` and then reaches for
  the database. Build a header line from `pyproj.__version__`, `pyproj.__proj_version__`,
  `pyproj.__proj_compiled_version__` and `pyproj.geod.geodesic_version_str` — all of which work
  with no data at all — plus `datadir.get_data_dir()` and `network.is_network_enabled()` in
  their own `try/except`.
- **`always_xy=True` on every `Transformer.from_crs`, and feed it `(lon, lat)`.** EPSG:4326's
  authority axis order is latitude-first
  ([`CRS("EPSG:4326").axis_info`](https://pyproj4.github.io/pyproj/stable/api/crs/crs.html#pyproj.crs.CRS.axis_info)
  → `[('Lat','north'), ('Lon','east')]`), so a default transformer reads your `(2.3522,
  48.8566)` as latitude 2.35. It does not raise — to EPSG:3857 it returns
  `(5438691.83, 261919.29)`, a perfectly well-formed Web Mercator pair that is simply wrong.
  `+proj=longlat` strings are longitude-first and unaffected, which is exactly why testing
  against one proves nothing about the EPSG path.
- **A missing grid downgrades the transform silently — this is the one that will hurt you.**
  With the full database present and no grid files (which is every device that ships
  `proj.db` and nothing else), `Transformer.from_crs("EPSG:4326", "EPSG:27700")` and the
  transform that follows raise **zero warnings** and return coordinates that look completely
  normal. PROJ has quietly picked *"Inverse of OSGB36 to WGS 84 (6)"*, declared accuracy
  **2.0 m**, in place of the *"(9)"* operation it wanted at **1.0 m**, which needs
  `uk_os_OSTN15_NTv2_OSGBtoETRS.tif` (3,035,814 bytes). Those figures are PROJ's own; run the
  same points with and without that grid beside `proj.db` and the error it really costs is
  Edinburgh 0.550 m, London 1.753 m, Cape Wrath 2.171 m, Norwich 3.152 m, Land's End
  4.270 m — measured against the downloaded grid on a desktop PROJ 9.5.1, and the one claim
  here no device has exercised, because neither the wheel nor the example ships `proj.db` or a
  grid. Two diagnostics do work, both offline:
  [`TransformerGroup(src, dst)`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.TransformerGroup)
  *does* warn, and exposes `.best_available` (`False` here), `.unavailable_operations` — each
  with `.accuracy` and `.grids[i].short_name` / `.available` / `.url` — and `.transformers`;
  and [`get_last_used_operation()`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.Transformer.get_last_used_operation),
  once a transform has run, names what actually ran and carries its `.accuracy`. Do not reach
  for the transformer's own `.description` and `.accuracy` instead: where PROJ picks the
  operation lazily they read `unavailable until proj_trans is called` and `-1.0` for the
  object's whole life — after the transform exactly as before it.
- **`allow_ballpark=False` and `only_best=True` do not turn that into an error.** Both were
  passed to the same `EPSG:4326 → EPSG:27700` transformer, singly and together, with
  `errcheck=True` on the transform: it built without raising and returned the *same*
  lower-accuracy coordinates. pyproj does forward the flags to PROJ; the fallback here is a
  genuine Helmert operation rather than a ballpark, and `ONLY_BEST` did not fire. Gate on
  `TransformerGroup(...).best_available` instead.
- **`errcheck=True` does not catch an out-of-area point either.** Sydney (151.2093, −33.8688)
  through `EPSG:4326 → EPSG:27700` returns `(2910514.15, −21431829.56)` with and without it — large,
  finite and meaningless. `errcheck` catches PROJ errors (`inf`/`HUGE_VAL`), not nonsense.
  Compare your input against `CRS(code).area_of_use` (EPSG:27700's bounds are
  `(-9.01, 49.75, 2.01, 61.01)`) and range-check the output.
- **A `+towgs84` round trip is not exact, and that is the datum, not a bug.** London out to
  the British National Grid and back landed 1.0080 mm from where it started, Edinburgh
  0.7904 mm; drop the seven-parameter shift from the same projection string and both go to
  0.0000 mm, as does UTM 33N, which has no shift. Millimetres, but don't expect a bit-exact
  round trip through a datum transformation.
- **The vectorised path needs no numpy.** pyproj never imports it — `numpy` is absent from
  `sys.modules` after `import pyproj`, and the only mentions in the package are docstrings and
  a duck-typed converter — so `Transformer.transform` takes lists, tuples and
  `array('d')` buffers through the Python buffer protocol, and `inplace=True` writes back into
  the buffer you passed. Use it: 100,000 points took 3.2 ms against 6.8 ms for 20,000 through a
  scalar loop, about 10× per point. Building the transformer is the expensive part
  (8.8 ms first, 1.8 ms warm) — hoist it out of the loop.
- **Your desktop is not a preview of the device.** `flet run` resolves pyproj from PyPI, whose
  wheel *does* bundle `proj_dir/share/proj/proj.db` — and that internal directory takes
  precedence over `PROJ_DATA`, so EPSG codes work on your Mac and raise on the phone with the
  same code. Test the CRS half on a device or simulator, or temporarily move
  `site-packages/pyproj/proj_dir` aside to reproduce the device shape locally.
- **`import pyproj` calls `certifi.where()` on every launch.** `pyproj/__init__.py` ends with
  `pyproj.network.set_ca_bundle_path()`, which takes the certifi branch unless
  `PROJ_CURL_CA_BUNDLE`, `CURL_CA_BUNDLE` or `SSL_CERT_FILE` is set — and does so *before* the
  call that can raise `DataDirError`. certifi's Python ≥3.11 branch resolves the path through
  `importlib.resources.as_file`, which materialises a temp copy with an `atexit` cleanup when
  the package lives inside a zip, as it does in Android's `sitepackages.zip`. `cacert.pem` is
  240,216 bytes. Set one of those environment variables if you want to skip it; leaving it
  alone is only a cost if you are counting launch milliseconds.
- **Size.** Everything except the extensions is 545,214–545,445 bytes on every one of the
  nineteen wheels; the table below is the cp314 wheel of each slice:

  | slice | wheel | unpacked | the ten `.so` |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 481 KB | 1,548 KB | 1,015 KB |
  | Android armeabi-v7a | 449 KB | 1,232 KB | 700 KB |
  | Android x86_64 | 507 KB | 1,531 KB | 999 KB |
  | iOS arm64 (device) | 27,794 KB | 74,114 KB | 73,582 KB |
  | iOS arm64 (simulator) | 28,486 KB | 74,446 KB | 73,913 KB |
  | iOS x86_64 (simulator) | 30,190 KB | 77,575 KB | 77,042 KB |

  Add the native chain on Android — 7,513,872 bytes on arm64-v8a, 5,227,468 on armeabi-v7a,
  8,347,680 on x86_64 — nothing installed on iOS, and whatever database you decide to ship.

## Build notes (maintainers)

Two recipes: `flet-libproj` builds PROJ, `recipes/pyproj` consumes it. `patches/mobile.patch`
explains both of its hunks in its own preamble and `meta.yaml` comments its `script_env` next
to it, so what is left here is shape and the bump checklist.

**The missing `share/proj` is a `flet-libproj` decision, not a pyproj one.** PROJ's
`make install` writes the whole tree, and `recipes/flet-libproj/build.sh` ends with
`rm -rf $PREFIX/{bin,share}`, which deletes it. That is defensible — 9 MB in a library wheel
that most consumers of PROJ-the-C-library do not want, and pyproj expects it at
`pyproj/proj_dir/share/proj` rather than in `opt/` anyway — but it is the reason this README
has a Storage section three times the length of anything else. Changing it means deciding
*which* wheel carries the database and how it reaches `get_data_dir()`; do not "fix" the `rm`
in isolation and expect pyproj to find the result.

**`flet-libproj` is `requirements.host`, so it lands in `Requires-Dist` on both platforms.**
Right on Android, where `libproj.so` must reach `jniLibs`; redundant on iOS, where the static
archive has already been absorbed and Flet's cleanup empties the installed wheel. One recipe
has to satisfy both. Same trade-off as [`shapely`](../shapely#build-notes-maintainers).

What to re-verify on a bump — a green build establishes almost none of what this page claims,
and a `flet-libproj` bump moves PROJ underneath all of it:

- **`tests/test_pyproj.py` covers `import pyproj` and two `Geod` calls, and nothing else.** The
  entire `CRS`/`Transformer` surface — the half this README spends most of its words on — is
  untested on device, and it is untested precisely because it depends on data the wheel does
  not ship. A green CI run is evidence about linking and geodesy. Worth adding: a test that
  plants a directory containing an empty `proj.db`, calls `set_data_dir`, and asserts that a
  `+proj=utm` transform returns the expected numbers while `CRS.from_epsg(4326)` raises
  `CRSError`. That pins the exact boundary this page documents, needs no payload, and would
  turn a PROJ change in the stub's behaviour red instead of silent.
- **The empty-`proj.db` trick lives in pyproj's Python layer, not in PROJ**, so a
  `flet-libproj` bump cannot break it on its own. The file only has to satisfy
  `datadir.py`'s `Path(dir, "proj.db").exists()`. PROJ then *rejects* it —
  `proj_context_set_database_path` returns false and `_context.pyx` warns *"pyproj unable to
  set PROJ database path"*, which is the tell that the stub is in play — and the proj-string
  API keeps working because it never wanted a database. What can break it is a **pyproj**
  bump that tightens `valid_data_dir`, and the check is a device run of the
  [`control-points`](examples/control-points) example: the panels would all become
  `DataDirError` rows, visibly rather than silently.
- **The PROJ version, in two places**: `strings` on `flet-libproj`'s `libproj.so` (and
  `libproj.a`), and the eight iOS extensions that absorb it. They can disagree only if a
  pyproj rebuild is skipped after a `flet-libproj` bump — on Android those are genuinely
  separate files. The version belongs on the example's header line, not in an assertion.
- **The linkage split.** Android: `DT_NEEDED` still naming `libproj.so` with no `libc++_shared`,
  `SONAME libproj.so`, and the `libtiff`/`libcurl`/`libjpeg`/`libpsl` chain intact; plus 16 KB
  `PT_LOAD` alignment on all ten extensions and on `libproj.so`. iOS: still ten `MH_DYLIB`s,
  still exactly eight of them carrying PROJ, `otool -L` still naming no curl/tiff/c++. If iOS
  ever links dynamically, the size table, the `Requires-Dist` reasoning and the whole iOS
  section change.
- **The behavioural claims in [Things to know](#things-to-know) are PROJ's, not pyproj's**, so
  a `flet-libproj` bump can move any of them without the Python half changing: the silent grid
  downgrade — both the declared accuracies (2.0 m versus 1.0 m for EPSG:27700) and the
  0.55–4.27 m it costs across Great Britain — the inertness of
  `allow_ballpark`/`only_best`, and the `+towgs84` round-trip residual. They are the most
  consumer-visible claims here and nothing asserts them.
- **The sizes and timings are measured.** Re-measure rather than adjusting by eye; the iOS
  totals in particular are the whole argument for budgeting 75 MB.
