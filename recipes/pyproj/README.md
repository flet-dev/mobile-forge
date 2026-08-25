# pyproj

[`pyproj`](https://pyproj4.github.io/pyproj/stable/) is the Python interface to
[PROJ](https://proj.org/), the library underneath every GIS: it turns latitude and longitude
into metres on a map, converts one datum into another, and answers distance-and-bearing
questions on the WGS-84 ellipsoid. On a phone that is what stands between a GPS fix and a
coordinate anyone else can use — plotting a track on a national grid, showing metres rather
than degrees, or consuming survey data published in a projection your device knows nothing
about. It computes all of that in-process, with no network. These wheels ship no `proj.db`,
which splits the library in half on device: the geodesic API works out of the box, and
everything touching a coordinate reference system raises until your app supplies a data
directory — one line of code and, for a large class of apps, zero bytes of payload.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pyproj",
]
```

pyproj needs **Python 3.11 or newer**, so set the app's `requires-python` to at least
`>=3.11`. Leaving it at the `>=3.10` that `flet create` writes does not fail the resolve —
which is what makes it worth saying. uv simply splits, taking an older pyproj for the
`<3.11` range and the current one above it. The older one has no wheel on this index, so
what you get is a build that resolves cleanly and then cannot find a mobile wheel for the
low split.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`control-points`](examples/control-points) — coordinate maths that prints its own residuals,
  running off an empty `proj.db`.

## Usage in a Flet app

Point PROJ at a directory holding a file called `proj.db` before the import, then build a
transformer and put its result on screen:

```python
import os

proj_dir = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "proj")
os.makedirs(proj_dir, exist_ok=True)
open(os.path.join(proj_dir, "proj.db"), "ab").close()  # an empty stub is enough
os.environ["PROJ_DATA"] = proj_dir                     # before `import pyproj`

import flet as ft
import pyproj

WGS84 = "+proj=longlat +datum=WGS84 +no_defs"
WEB_MERCATOR = "+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +units=m +no_defs"

# always_xy=True, and feed it (lon, lat) — see Things to know
to_metres = pyproj.Transformer.from_crs(WGS84, WEB_MERCATOR, always_xy=True)
x, y = to_metres.transform(2.3522, 48.8566)

position = ft.Text(f"{x:,.1f} m E   {y:,.1f} m N")
```

### The PROJ database

**Neither these wheels nor `flet-libproj` contain `proj.db`, or any file under `share/proj`, on
either platform.** PROJ refuses to build a *context* until it finds a directory holding a file
of that name, and every
[`CRS`](https://pyproj4.github.io/pyproj/stable/api/crs/crs.html#pyproj.crs.CRS),
[`Proj`](https://pyproj4.github.io/pyproj/stable/api/proj.html#pyproj.Proj),
[`Transformer`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.Transformer),
`database` and `network` call goes through one. So `import pyproj` succeeds — emitting
`UserWarning: Valid PROJ data directory not found…` — and
[`Geod`](https://pyproj4.github.io/pyproj/stable/api/geod.html#pyproj.Geod) works in full with
no data directory at all (Paris → London measured 343,915.771 m), while everything else raises
[`pyproj.exceptions.DataDirError`](https://pyproj4.github.io/pyproj/stable/api/exceptions.html#pyproj.exceptions.DataDirError):
`CRS.from_epsg`, `CRS("EPSG:3857")`, `CRS("+proj=utm …")`, `Proj`, `Transformer.from_crs`,
`Transformer.from_pipeline`, `database.get_authorities()`, `datadir.get_data_dir()`,
`network.is_network_enabled()` and `show_versions()`. It fails loudly, but at the *first* CRS
call rather than at import — typically inside an event handler, where an unhandled exception
ends the session with a crash screen.

Two ways to supply a directory, both verified in the main thread and in worker threads, which
build their own PROJ context:

```python
os.environ["PROJ_DATA"] = data_dir       # before `import pyproj`
pyproj.datadir.set_data_dir(data_dir)    # any time after it
```

The environment variable has to be set before the import because pyproj resolves the directory
once, on its way through `pyproj/__init__.py`; setting it there also means the lookup succeeds
first time and no warning is emitted.
[`append_data_dir`](https://pyproj4.github.io/pyproj/stable/api/datadir.html#pyproj.datadir.append_data_dir)
adds a second directory without displacing the first, which is how you add grid files: PROJ
takes the *database* from the first entry and treats the rest as search paths.

**Zero bytes: an empty `proj.db`.** `get_data_dir()` checks nothing but that a file of that
name **exists**, and a zero-byte file passes. That unlocks the whole PROJ-string API —
`Proj(proj="utm", zone=33, ellps="WGS84")`, `CRS("+proj=…")` and `.to_proj4()`,
`Transformer.from_crs(<proj-string>, <proj-string>)`, `Transformer.from_pipeline(...)`, `Geod`
and `network.is_network_enabled()` — at a cost of one
`UserWarning: pyproj unable to set PROJ database path.` per context built. Anything naming an
authority still fails: `CRS.from_epsg(4326)` and
`Transformer.from_crs("EPSG:4326", "EPSG:3857")` raise `CRSError: Invalid projection:
EPSG:4326: (Internal Proj Error: proj_create: no database context specified)`. The accuracy
cost is nil, because a proj-string reproduces the authority definition exactly: `+proj=merc`
against EPSG:3857 at Paris, `+proj=utm +zone=33` against EPSG:32633 at 15°E 60°N and
`+proj=tmerc …` against EPSG:27700 at London each agreed **bit for bit** with the same
transform run against the full database. What you give up is discovery — you have to know the
parameters, and `CRS(code).name`, `.area_of_use` and the `database` module are closed to you.
The [`control-points`](examples/control-points) example runs entirely this way.

**Nine megabytes: the real database.** If you need EPSG codes, ship `proj.db` as an asset and
point
[`set_data_dir`](https://pyproj4.github.io/pyproj/stable/api/datadir.html#pyproj.datadir.set_data_dir)
at the directory holding it:

```python
pyproj.datadir.set_data_dir(os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "proj"))
```

Take it from the same-version PyPI wheel, whose macOS arm64 build carries
`pyproj/proj_dir/share/proj` as 16 files totalling about 9.4 MB. **`proj.db` on its own — about
9.3 MB — is sufficient**: the other fifteen are init files, JSON schemas and `proj.ini`, and
the database is the only one `get_data_dir()` looks for. Copied alone into an empty directory
it resolved `CRS("EPSG:27700").name` to `OSGB36 / British National Grid`, ran
`EPSG:4326 → EPSG:3857` and `EPSG:4326 → EPSG:27700`, and worked from a worker thread.

**The version skew is real and harmless.** PROJ validates the database's
`DATABASE.LAYOUT.VERSION.MAJOR`/`MINOR` and rejects a mismatch with *"It comes from another
PROJ installation"*. That database declares layout 1.4 and `PROJ.VERSION 9.5.1`, while
`flet-libproj` is PROJ **9.5.0** — but 9.5.0 wants layout 1.4 as well, and a PROJ 9.5.0 built
from the same tarball the recipe fetches accepted that exact file. Nothing in CI exercises it,
so confirm it on the device you ship.

### Storage

The empty stub is app-private state rather than an asset, which is why the snippet above
creates it under
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— durable, and a real filesystem path on both platforms, at a cost of one `os.makedirs` and one
`open(path, "ab").close()`.

A real `proj.db`, and any grid file, ships with the application instead: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and read
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir) for
the absolute path to hand `set_data_dir` or `append_data_dir`. Keep a 9 MB database out of app
storage unless the app downloads it itself — an asset costs nothing to install and nothing to
keep current.

### Grids and the network

No transformation grid ships either, and most transforms do not need one. Where one *is*
wanted — datum shifts like OSTN15 for the British National Grid, or NADCON for NAD27 — PROJ
silently falls back to a lower-accuracy operation instead of failing, which is the trap under
[Things to know](#things-to-know). Bundle the grid as an asset and `append_data_dir` its
directory, or use one of the two independent download paths, **both of which are off unless you
turn them on**:

- **PROJ's own fetcher** (libcurl, endpoint `https://cdn.proj.org`) is compiled in on both
  platforms and defaults to off: `_context.pyx` reads
  `strtobool(os.environ.get("PROJ_NETWORK", "OFF"))` at import, and
  [`set_network_enabled`](https://pyproj4.github.io/pyproj/stable/api/network.html#pyproj.network.set_network_enabled)
  flips it afterwards.
- **pyproj's own downloader** —
  [`TransformerGroup.download_grids`](https://pyproj4.github.io/pyproj/stable/api/transformer.html#pyproj.transformer.TransformerGroup.download_grids)
  over `urllib.request.urlretrieve` in `sync.py` — ignores `PROJ_NETWORK` entirely.

Turning the fetcher on is not a safety net either: when a fetch failed, the transform returned
`(inf, inf)` rather than falling back. Assume no signal.

To prove an app really is offline, a Python `socket` stub is no help — PROJ's fetcher is
libcurl, underneath Python entirely. Point `PROJ_NETWORK_ENDPOINT` at a local HTTP server that
logs every hit, and cover the Python half separately with a `sys.addaudithook` watching
`socket.connect`, `getaddrinfo` and `urllib.Request`, where `sync.py`'s `urlretrieve` would
show up. Importing pyproj, building `Transformer.from_crs("EPSG:4326", "EPSG:27700")`,
transforming and reading `TransformerGroup(...).best_available` made **zero requests** and
recorded zero events that way, while the same sequence with `PROJ_NETWORK=ON` made one —
`GET /uk_os_OSTN15_NTv2_OSGBtoETRS.tif` — which is what says the probe would have caught a leak.

### Threading

**`Transformer` and `CRS` objects are safe to share across threads, by design.** Both hold a
`threading.local` and rebuild their Cython object per thread on first use, and PROJ contexts
are thread-local too. Eight threads driving one shared `Transformer`, one shared `CRS` and one
shared `Geod`, each over its own disjoint slice of points so a shared-state bug could not hide
behind identical inputs, matched a single-threaded reference element for element across 48,000
calls, with zero exceptions.

**The transform loop releases the GIL**, so a projection in a worker thread genuinely runs
beside the UI. Clocked against a pure-Python counter thread, `Transformer.transform` let that
counter keep 93–99% of the rate an idle main thread allows — the same band as `hashlib.sha256`,
which also releases the GIL, and three to thirteen times what GIL-holding `math.factorial`
leaves it.

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

### App size

Everything in the wheel except the extensions is about 545 KB on every slice. The extensions
are the whole story, and iOS carries about seventy times what Android does:

| slice | wheel | unpacked | the ten extensions |
| --- | --- | --- | --- |
| Android arm64-v8a | 0.49 MB | 1.6 MB | 1.04 MB |
| Android armeabi-v7a | 0.46 MB | 1.3 MB | 0.72 MB |
| Android x86_64 | 0.52 MB | 1.6 MB | 1.02 MB |
| iOS arm64 (device) | 28.5 MB | 75.9 MB | 75.3 MB |
| iOS arm64 (simulator) | 29.2 MB | 76.2 MB | 75.7 MB |
| iOS x86_64 (simulator) | 30.9 MB | 79.4 MB | 78.9 MB |

Those are decimal MB; `du -h` and the Finder report binary units and read about 5% lower for
the same bytes.

Android loads PROJ from a separate chain of shared libraries on top of that — about 7.5 MB on
arm64-v8a, 5.2 MB on armeabi-v7a and 8.3 MB on x86_64 — while iOS installs none, because each
extension already contains its own copy. So on Android, use an app bundle, split APKs, or
narrow [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
when the app does not need every ABI; that lever is worth more here than the wheel column
suggests, since the native chain is carried once per ABI. **On iOS there is no lever.** Eight
of the ten extensions each absorb a full copy of PROJ, `import pyproj` loads all ten
regardless, and an app that only wants `Geod` pays the same 75 MB;
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) cannot reach
it. Budget for it, and add whatever database you decide to ship. These figures describe the
package payload, not the exact amount added to the final APK or IPA; packaging and compression
determine that.

### Other considerations

**Your desktop is not a preview of the device.** `flet run` resolves pyproj from PyPI, whose
wheel *does* bundle `proj_dir/share/proj/proj.db` — and that internal directory takes
precedence over `PROJ_DATA`, so EPSG codes work on your Mac and raise on the phone from the
same code. Test the CRS half on a device or simulator, or temporarily move
`site-packages/pyproj/proj_dir` aside to reproduce the device shape locally.

## Things to know

- **`import pyproj` succeeding proves nothing.** It succeeds when no data directory exists,
  with only a `UserWarning` to show for it, and nothing in your UI displays that. The failure
  surfaces at the first `CRS`/`Transformer` call, which is typically inside an event handler,
  where an unhandled exception gives you a crash screen rather than a message. Set the data
  directory at startup and wrap the first transform in `try/except Exception`.
- **[`pyproj.show_versions()`](https://pyproj4.github.io/pyproj/stable/api/show_versions.html#pyproj.show_versions)
  raises on device.** It prints `pyproj info:` and then reaches for the database. Build a
  header line from `pyproj.__version__`, `pyproj.__proj_version__`,
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
  With the full database present and no grid files (which is every device that ships `proj.db`
  and nothing else), `Transformer.from_crs("EPSG:4326", "EPSG:27700")` and the transform that
  follows raise **zero warnings** and return coordinates that look completely normal. PROJ has
  quietly picked *"Inverse of OSGB36 to WGS 84 (6)"*, declared accuracy **2.0 m**, in place of
  the *"(9)"* operation it wanted at **1.0 m**, which needs `uk_os_OSTN15_NTv2_OSGBtoETRS.tif`
  (about 3.0 MB). Run the same points with and without that grid and the error it really costs
  is Edinburgh 0.550 m, London 1.753 m, Cape Wrath 2.171 m, Norwich 3.152 m, Land's End
  4.270 m. Two diagnostics work, both offline: `TransformerGroup(src, dst)` *does* warn, and
  exposes `.best_available` (`False` here), `.unavailable_operations` — each with `.accuracy`
  and `.grids[i].short_name` / `.available` / `.url` — and `.transformers`; and
  `get_last_used_operation()`, once a transform has run, names what actually ran and carries
  its `.accuracy`. Do not reach for the transformer's own `.description` and `.accuracy`
  instead: where PROJ picks the operation lazily they read
  `unavailable until proj_trans is called` and `-1.0` for the object's whole life — after the
  transform exactly as before it.
- **`allow_ballpark=False` and `only_best=True` do not turn that into an error.** Both were
  passed to the same `EPSG:4326 → EPSG:27700` transformer, singly and together, with
  `errcheck=True` on the transform: it built without raising and returned the *same*
  lower-accuracy coordinates. pyproj does forward the flags to PROJ; the fallback here is a
  genuine Helmert operation rather than a ballpark, and `ONLY_BEST` did not fire. Gate on
  `TransformerGroup(...).best_available` instead.
- **`errcheck=True` does not catch an out-of-area point either.** Sydney (151.2093, −33.8688)
  through `EPSG:4326 → EPSG:27700` returns `(2910514.15, −21431829.56)` with and without it —
  large, finite and meaningless. `errcheck` catches PROJ errors (`inf`/`HUGE_VAL`), not
  nonsense. Compare your input against `CRS(code).area_of_use` (EPSG:27700's bounds are
  `(-9.01, 49.75, 2.01, 61.01)`) and range-check the output.
- **A `+towgs84` round trip is not exact, and that is the datum, not a bug.** London out to the
  British National Grid and back landed 1.0080 mm from where it started, Edinburgh 0.7904 mm;
  drop the seven-parameter shift from the same projection string and both go to 0.0000 mm, as
  does UTM 33N, which has no shift. Millimetres, but do not expect a bit-exact round trip
  through a datum transformation.
- **The vectorised path needs no numpy.** pyproj never imports it — `numpy` is absent from
  `sys.modules` after `import pyproj` — so `Transformer.transform` takes lists, tuples and
  `array('d')` buffers through the Python buffer protocol, and `inplace=True` writes back into
  the buffer you passed. Use it: 100,000 points took 3.2 ms against 6.8 ms for 20,000 through a
  scalar loop, about 10× per point. Building the transformer is the expensive part (8.8 ms
  first, 1.8 ms warm) — hoist it out of the loop.
- **`import pyproj` calls `certifi.where()` on every launch.** `pyproj/__init__.py` ends with
  `pyproj.network.set_ca_bundle_path()`, which takes the certifi branch unless
  `PROJ_CURL_CA_BUNDLE`, `CURL_CA_BUNDLE` or `SSL_CERT_FILE` is set — and does so *before* the
  call that can raise `DataDirError`. certifi's Python ≥3.11 branch resolves the path through
  `importlib.resources.as_file`, which materialises a temp copy of the 240 KB `cacert.pem` with
  an `atexit` cleanup when the package lives inside a zip, as it does in Android's
  `sitepackages.zip`. Set one of those environment variables to skip it; leaving it alone is
  only a cost if you are counting launch milliseconds.

## Build notes (maintainers)

### Recipe shape

Two recipes: `flet-libproj` builds PROJ, `recipes/pyproj` consumes it. `patches/mobile.patch`
explains both of its hunks in its own preamble and `meta.yaml` comments its `script_env` next
to it, so what is left here is shape, the linkage evidence the consumer sections rest on, and
the bump checklist.

**The missing `share/proj` is a `flet-libproj` decision, not a pyproj one.** PROJ's
`make install` writes the whole tree, and `recipes/flet-libproj/build.sh` ends with
`rm -rf $PREFIX/{bin,share}`, which deletes it. That is defensible — 9 MB in a library wheel
that most consumers of PROJ-the-C-library do not want, and pyproj expects it at
`pyproj/proj_dir/share/proj` rather than in `opt/` anyway — but it is why **The PROJ database**
is the longest section above. Changing it means deciding *which* wheel carries the database and
how it reaches `get_data_dir()`; do not "fix" the `rm` in isolation and expect pyproj to find
the result.

**`flet-libproj` is `requirements.host`, so it lands in `Requires-Dist` on both platforms.**
Right on Android, where `libproj.so` must reach `jniLibs`; redundant on iOS, where the static
archive has already been absorbed. One recipe has to satisfy both. On iOS `flet-libproj` and
the extra `flet-libjpeg` ship nothing but `.a` archives and headers, and serious_python's
cleanup deletes every `**.a` and `**.h`, so the installed wheels end up empty.

**Android: a chain of shared libraries, resolved by bare soname.** All ten extensions list
exactly `libm.so`, `libproj.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` in
`DT_NEEDED` — no `libc++_shared.so` — with a `RUNPATH` pointing at a build-host directory that
exists on no phone. Harmless: serious_python's Gradle `copyOpt` task flattens every `.so` under
a wheel's `opt/` into `jniLibs/<abi>/` under its plain basename, and `libproj.so` carries
`SONAME libproj.so`. `libproj.so` in turn names `libsqlite3_python.so` (from Flet's Python
bundle), `libtiff.so` and `libcurl.so`; `libtiff.so` names `libjpeg.so` and `libz.so`;
`libcurl.so` names `libpsl.so`, `libssl_python.so`, `libcrypto_python.so` and `libz.so`. That
chain is **7,513,872 bytes of `.so` on arm64-v8a** — `libproj.so` 4,640,656, `libturbojpeg.so`
748,184, `libtiff.so` 744,048, `libcurl.so` 723,712, `libjpeg.so` 589,784, `libpsl.so` 67,488 —
against 5,227,468 on armeabi-v7a and 8,347,680 on x86_64, on top of pyproj's own 1,039,288.
Every `LOAD` segment in all of them, across all three ABIs, reports `align 0x4000`.

**iOS: PROJ absorbed into the extensions instead, into eight of the ten separately.**
`flet-libproj` ships `libproj.a` (7,553,816 bytes) and no shared library at all, and the link
pulls it into each extension that touches the database. `_context`, `_crs`, `_network`,
`_sync`, `_transformer`, `_version`, `database` and `list` each carry PROJ's version string,
its `cdn.proj.org` endpoint and its database-layout checks, at 9,273,576–9,702,872 bytes
apiece; `_compat` (103,792) and `_geod` (202,664) do not, the geodesic code being small and
self-contained. Total **75,347,880 bytes of extension on the device slice**. All ten are
`MH_DYLIB`, so forge's `MH_BUNDLE` conversion has nothing to do, and `otool -L` on each lists
only its own install name, `@rpath/Python.framework/Python`, `/usr/lib/libsqlite3.dylib`,
`/usr/lib/libz.1.dylib` and `/usr/lib/libSystem.B.dylib` — no libcurl, no libtiff, no libc++.
The C++ runtime is instead 124 flat-namespace symbols in each of those eight (`nm -m`;
`_compat` and `_geod` have none), bound against the OS at `dlopen`. The static
curl/OpenSSL/tiff objects really are inside: `_context` *defines* `_SSL_connect`,
`_TIFFClientOpen` and `_psl_builtin` as text symbols. SQLite differs across the platforms too —
Android's `libproj.so` links `libsqlite3_python.so` from Flet's Python bundle, iOS binds the
system `/usr/lib/libsqlite3.dylib` — and either way it is that SQLite which opens whatever
`proj.db` the app supplies.

**No `extract_packages` entry and no loader shim.** All 65 entries in the wheel are ten
extensions, 20 `.py` files, Cython sources and stubs, and `dist-info` — no data file of any
kind — and across the whole package there is exactly one occurrence of `__file__`,
`importlib.resources`, `pkgutil`, `pkg_resources`, `ctypes`, `find_library`, `sys.platform`,
`platform.system()` or `os.name`: `datadir.py:73`, which probes for a bundled data directory
that is not there and is *meant* to fail. All ten extension filenames carry a full CPython ABI
tag, which is what Android's relocation needs. Nothing reads its own source, so `.pyc`
compilation is safe; Flet's default cleanup takes 26 files and 202,508 bytes of `.pyx`, `.pxd`,
`.pyi` and `py.typed`, and leaves two unused `.pxi` at 23,144 bytes. `certifi` is pure Python
and absent from this index, so it resolves from PyPI.

Nineteen wheels come out of one build number: Python 3.12, 3.13 and 3.14 × three Android ABIs
and three iOS slices, plus a legacy 32-bit `android_24_x86` slice on 3.12, which flet-cli
0.86.5 cannot target — its `ANDROID_ARCH_TO_FLUTTER_TARGET_PLATFORM` holds only `armeabi-v7a`,
`arm64-v8a` and `x86_64`. No arch is excluded.

### Upgrade hazards

- **The empty-`proj.db` trick lives in pyproj's Python layer, not in PROJ**, so a `flet-libproj`
  bump cannot break it on its own. The file only has to satisfy `datadir.py`'s
  `Path(dir, "proj.db").exists()`. PROJ then *rejects* it — `proj_context_set_database_path`
  returns false and `_context.pyx` warns *"pyproj unable to set PROJ database path"*, which is
  the tell that the stub is in play — and the proj-string API keeps working because it never
  wanted a database. What can break it is a **pyproj** bump that tightens `valid_data_dir`.
- **The behavioural claims in [Things to know](#things-to-know) are PROJ's, not pyproj's**, so a
  `flet-libproj` bump can move any of them without the Python half changing: the silent grid
  downgrade — both the declared accuracies (2.0 m versus 1.0 m for EPSG:27700) and the
  0.55–4.27 m it costs across Great Britain — the inertness of `allow_ballpark`/`only_best`, and
  the `+towgs84` round-trip residual. They are the most consumer-visible claims here and nothing
  asserts them.
- **If iOS ever links PROJ dynamically instead of absorbing it**, the size table, the **App
  size** "no lever" statement and the `Requires-Dist` reasoning all change together.

### Re-verification checklist

- **The three control points behind "bit for bit".** That claim is the reason the page can tell
  a reader the proj-string route costs no accuracy, so a bump has to re-run it rather than
  re-read it. Against the same transforms with the full database present, all three agreed
  exactly: `+proj=merc +a=6378137 +b=6378137` vs EPSG:3857 at Paris
  `(261845.70624393807, 6250564.349543124)`; `+proj=utm +zone=33 +datum=WGS84` vs EPSG:32633 at
  15°E 60°N `(500000.0000000009, 6651411.190362714)`; and
  `+proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 +x_0=400000 +y_0=-100000 +ellps=airy
  +towgs84=446.448,-125.157,542.06,0.15,0.247,0.842,-20.489` vs EPSG:27700 at London
  `(530042.625993872, 180380.44930295716)`. A PROJ bump that moves any digit means the
  accuracy sentence in Usage no longer holds.

- **The PROJ version, in two places**: `strings` on `flet-libproj`'s `libproj.so` (and
  `libproj.a`), and the eight iOS extensions that absorb it. They can disagree only if a pyproj
  rebuild is skipped after a `flet-libproj` bump — on Android those are genuinely separate
  files. The version belongs on the example's header line, not in an assertion.
- **The linkage split.** Android: `DT_NEEDED` still naming `libproj.so` with no
  `libc++_shared`, `SONAME libproj.so`, and the `libtiff`/`libcurl`/`libjpeg`/`libpsl` chain
  intact, plus 16 KB `PT_LOAD` alignment on all ten extensions and on `libproj.so`. iOS: still
  ten `MH_DYLIB`s, still exactly eight of them carrying PROJ, `otool -L` still naming no
  curl/tiff/c++.
- **A device run of the [`control-points`](examples/control-points) example.** If a pyproj bump
  tightened the data-directory check, every panel becomes a `DataDirError` row — visibly rather
  than silently.
- **The database version skew**, on the device you ship: nothing in CI loads a real `proj.db`
  against the shipped PROJ, and the layout-version gate is what would reject it.
- **The sizes and timings are measured.** Re-measure rather than adjusting by eye, and quote
  decimal; the iOS totals in particular are the whole argument for budgeting 75 MB.

### Coverage gaps

`tests/test_pyproj.py` covers `import pyproj` and two `Geod` calls, and nothing else. The whole
`CRS`/`Transformer` surface — the half this page spends most of its words on — is untested on
device, and it is untested precisely because it depends on data the wheel does not ship. A green
CI run is evidence about linking and geodesy, and nothing more. Worth adding: a test that plants
a directory containing an empty `proj.db`, calls `set_data_dir`, and asserts that a `+proj=utm`
transform returns the expected numbers while `CRS.from_epsg(4326)` raises `CRSError`. That pins
the exact boundary this page documents, needs no payload, and would turn a change in the stub's
behaviour red instead of silent.

The grid-downgrade figures are the other gap: they were measured on a desktop PROJ 9.5.1 with a
downloaded grid, and no device has run them, because neither the wheel nor the example ships
`proj.db` or a grid file.
