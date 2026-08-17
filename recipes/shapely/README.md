# shapely

[`shapely`](https://shapely.readthedocs.io/) is Python's 2D geometry library: points, lines and
polygons, the predicates between them (`contains`, `intersects`, `within`, `touches`), the set
operations (`union`, `intersection`, `difference`, `buffer`), and an
[`STRtree`](https://shapely.readthedocs.io/en/stable/strtree.html) spatial index over any of it.
It is a thin binding over [GEOS](https://libgeos.org/), the C++ engine behind PostGIS and QGIS.

The reason to want it on a phone is the index and the vectorisation. A geofence check, a
"which zone am I standing in" lookup, clipping a recorded track to a boundary, merging coverage
areas — all of it is a nested loop over geometry if you write it yourself, and shapely 2.x turns
it into one call over numpy arrays with a GEOS-side index underneath. Measured in the example
below at 240 zones against 4,000 points, on a desktop, that was 1.1 ms through the tree against
30 ms for the same answer computed all-pairs, and 17 ms against 246 ms for nearest-zone. It reads
no files and opens no sockets: across the 43 modules that make up the library there is no
`socket`, `urllib`, `http`, `ssl` or `subprocess` import and no `open()` call, and the only
`Path(` hits are matplotlib path objects in `plotting.py`. (Upstream's own `shapely/tests` does
all three — it ships in the wheel, and nothing imports it.)

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "shapely",
]
```

Two more wheels come along and neither needs configuring:

- **`numpy`** — upstream shapely's own dependency, declared unconditionally
  (`Requires-Dist: numpy>=1.21`, outside any `extra ==` marker). It is not optional: the package
  `__init__` star-imports eleven modules and ten of them import numpy directly.
- **`flet-libgeos`** — GEOS itself, pinned by this recipe and appended to the wheel's
  `Requires-Dist` as `flet-libgeos (==3.13.1)` on *both* platforms. Only Android loads it at
  runtime; see [iOS notes](#ios-notes).

On Android a third arrives one level down: the mobile `numpy` wheel declares
`Requires-Dist: flet-libcpp-shared (>=27.2.12479018)`, so `libc++_shared.so` ends up in the APK.
Not for shapely's sake — none of its three extensions asks for it (see
[Android notes](#android-notes)) — but you will see it in the build.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed, and no app-side loader shim. All 136 entries in the wheel are 126 `.py` files,
two `.pxd` files, three extensions and five `dist-info` files — no data file, no `.pyi` stub.
Outside upstream's own `shapely/tests` package, which nothing imports, there is not one occurrence
of `__file__`, `importlib.resources`, `pkgutil`, `pkg_resources`, `ctypes`, `dlopen` or
`find_library`, and not one `sys.platform` / `platform.system()` / `os.name` gate; the only
environment variable read is `SPHINX_DOC_BUILD`, in `decorators.py`. All three extension
filenames carry a full CPython ABI tag, which is what Android's relocation needs.
So it runs as-is out of Android's zipped site-packages, and Flet's default
[compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) takes nothing it
needs: no module reads its own source — `getsource` appears nowhere, and the one `inspect` import
in the package is `unwrap`, in `decorators.py`, which reads a function's `__code__` rather than
its text — so compiling to `.pyc` is safe, and the only files the mobile junk-file globs remove
are the two `.pxd` Cython headers, which exist to build *against* shapely rather than to run it.

Nineteen wheels at the same build number: Python 3.12, 3.13 and 3.14 × three Android ABIs
(arm64-v8a, armeabi-v7a, x86_64) and three iOS slices (device, arm64 simulator, x86_64
simulator), plus a legacy 32-bit `android_24_x86` slice on 3.12. No arch is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) narrowing
is needed. Nothing on PyPI competes for a mobile target either: upstream's own 2.1.2 release is
57 files and not one carries an Android or iOS tag, and the wheel here needs `flet-libgeos`, which
exists only on this index.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`zone-index`](examples/zone-index) — answers two spatial questions through an `STRtree` and
  then again with no index at all, so the screen says whether the two agree.

## Threading

**The ufunc-backed calls release the GIL. The IO ones do not.** `lib` and `_geometry_helpers`
import `PyEval_SaveThread` and `PyEval_RestoreThread` on both platforms — the small `_geos` module
imports neither — and `shapely/decorators.py` says where the release lives: in the C ufunc loop,
under the 114 `@multithreading_enabled` functions of `predicates`, `measurement`, `constructive`,
`creation`, `set_operations`, `linear`, `_geometry` and `_coverage`. `shapely/io.py`,
`shapely/coordinates.py` and `shapely/strtree.py` carry that decorator nowhere, and the split
shows up in measurement. Running one long call on desktop with a counting thread spinning beside
it, `area`, `within`, `points`, `simplify`, `union_all`, `equals_exact`, `tree.query`,
`tree.query_nearest` and `tree.nearest` left that counter at 32–139% of its undisturbed rate,
while `to_wkb` (1%), `from_wkb` (0%), `to_wkt` (3%), `to_geojson` (0%), `get_coordinates` (1%) and
`STRtree` *construction* (5%) starved it exactly as the GIL-holding control did (`math.factorial`
0%, against a GIL-releasing `hashlib.sha256` control at 82%). Four threads on four separate point
arrays then scaled `shapely.within` 2.07×, `shapely.buffer` 1.82× and `tree.query` 1.58×, against
`to_wkb` 1.05× and `get_coordinates` 0.88× — the 0.84× a pure-Python loop manages. So a query in
a background thread genuinely runs alongside the UI, but serialising a big geometry array to WKB,
pulling its coordinates out, or building the index blocks the UI thread for its whole duration.
Nothing in the package starts a thread of its own — `pthread_create` is absent from every slice.

**One `STRtree` is safe to share.** Eight threads against one tree, each asking a *different*
question of a *different* 10,000-point slice — `query` under three predicates, `nearest`,
`query_nearest`, `contains` against a shared polygon, `distance`, `bounds` — 25 repetitions each,
every thread's answer compared against what that same call returned serially. All eight matched
exactly, with zero exceptions. That is the version of the test worth running: eight threads all
issuing the *same* query return the same number whether or not a result leaks between them, so it
cannot tell you anything. There is no handle to serialise with a lock here, unlike a database
connection.

**What is not safe is writing to a geometry array while another thread is reading it.**
`multithreading_enabled` sets `arr.flags.writeable = False` on every object-dtype array argument
for the duration of the call and restores it in a `finally`. So a second thread assigning into
that same array mid-call gets `ValueError: assignment destination is read-only` — reproduced on
desktop with a `shapely.buffer` over 400,000 points in one thread and a single element assignment
in another. Plain float coordinate arrays are untouched by this (the decorator only looks at
object dtype), and the flag is always restored afterwards. Give each thread its own array, or
treat a geometry array as immutable once it exists, which is the shapely 2.x idiom anyway.

The ordinary Flet rules still apply on top of that:
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) never
retrieves the worker's future, so an exception in a worker vanishes without a log — wrap the body
in `try/except`. Auto-update does not reach background threads, so end the worker with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). And since
`run_thread` submits to a *shared* pool while the `disabled` you just set is still only queued for
the client, disabling the control that started the run is not by itself a guard — read the flag
back before dispatching, or a second gesture inside that window puts a second worker on the same
controls, and nothing on screen admits that two levels are mixed.

## Android notes

**GEOS is a separate pair of shared libraries, resolved by bare soname.** All three extensions
list exactly `libm.so`, `libgeos_c.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` in
`DT_NEEDED`, on all four Android ABIs, with no `SONAME`, `RPATH` or `RUNPATH` — and they leave the
GEOS entry points undefined for it to satisfy (on arm64-v8a: 200 of them in `lib.so`, 15 in
`_geometry_helpers.so`, 4 in `_geos.so`). `libgeos_c.so` in turn needs `libgeos.so`, and both
carry a `SONAME` equal to their own basename. `flet-libgeos` ships exactly those two as
`opt/lib/*.so`, and serious_python's Gradle `copyOpt` task copies every `.so` under a wheel's
`opt/` into `jniLibs/<abi>/` under its plain basename, which is what makes the bare soname
resolve. That is the whole mechanism, and it is why `flet-libgeos` is load-bearing here and needs
no `extract_packages` entry of its own.

Its cost is 4,686,336 bytes of `.so` per ABI (`libgeos.so` 4,361,400 + `libgeos_c.so` 324,936).
The other 3.2 MB of that wheel is 514 headers, which `copyOpt` does not take and Flet's default
cleanup deletes anyway (`**.h` and `**.hpp` are in serious_python's junk-file list).

**The extensions do not need `libc++_shared.so`.** None of the three names it in `DT_NEEDED`, and
`libgeos.so` statically links libc++ — it needs only `libm`, `libdl` and `libc`, and defines
`_Znwm` / `_ZdlPv` and friends as weak symbols itself. It still arrives in the APK, because numpy
asks for it (see [Install](#install)). This differs from what `tests/test_shapely.py`'s docstrings
say; see [Build notes](#build-notes-maintainers).

All five native objects — the three extensions plus `libgeos.so` and `libgeos_c.so` — report
`align 0x4000` on every `LOAD` segment, which is the 16 KB page alignment Android 15 requires.

**`shapely.lib.__file__` is not a path inside your app.** Flet moves every ABI-tagged extension
out of site-packages into `jniLibs` and leaves a `.soref` marker at the import path, so the
attribute reports a mangled bare filename — or, for some packages, is absent entirely; for the
same Flet version [`pyyaml`](../pyyaml) reports a bare `libyaml-_yaml.so` while
[`pydantic-core`](../pydantic-core) reports no `__file__` at all. Nothing in shapely cares, since
nothing in it reads `__file__`, but code of yours that locates a resource relative to a native
module's `__file__` breaks here. The [`zone-index`](examples/zone-index) example prints the value
in its header line so you can read the answer off the device rather than off this page.

## iOS notes

**GEOS is linked *into* the extensions here — into all three of them, separately.** Each of
`lib`, `_geos` and `_geometry_helpers` is an `MH_DYLIB` that defines 271 `_GEOS*` symbols of its
own and leaves none of them undefined, and each carries its own copy of the C++ vtable member
`geos::geom::GeometryComponentFilter::filter_ro`. `otool -L` on each lists only its own install
name, `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`. What is left undefined is
CPython's API and libc/libm, two-level-bound to those two, plus **137 symbols per extension marked
for flat-namespace lookup at `dlopen`** (`nm -m`) — the whole slice of libc++/libc++abi that GEOS
uses, not a few stubs: 53 iostream entries, 18 `std::` exception classes, 15 `std::string`
members, 12 RTTI `typeinfo`/vtables, 12 `__cxa_*` plus `__gxx_personality_v0` and
`__dynamic_cast`, nine `std::locale`, four `operator new`/`delete`, three `std::mutex`, two
`std::random_device`, and nine others — `std::terminate`, `chrono::steady_clock::now`, a
`__sort<double*>` instantiation and the `__shared_weak_count` helpers among them. No `libc++`
appears in `otool -L` at all; iOS ships it in the OS, which is what those bind against.

That absorbed copy is the whole of the platform size difference: 9,788,664 bytes of `.so` on the
iOS device slice against 446,408 on Android arm64-v8a, a 22× ratio, for the same three modules.
It is not a 22× app-size difference, though — Android additionally carries `flet-libgeos`'s
4.69 MB of GEOS shared libraries per ABI (`libgeos.so` plus `libgeos_c.so`), which iOS does not.

**No extension depends on another, so there is no install-name relocation problem to hit.** This
is the opposite of the interdependent-dylib case that
[`pyarrow`](../pyarrow) needed serious_python#223 for: nothing here needs a `.fwork` shim to find
a sibling.

**`flet-libgeos` contributes nothing at runtime on iOS.** Its payload there is 8,423,296 bytes of
`libgeos.a` + `libgeos_c.a` and 3.2 MB of headers, and that is *all* it contains — the wheel has
no `.so` at any path. Flet's default cleanup removes `**.a` and `**.h`, which leaves the installed
wheel as nothing but its own `dist-info`. That is cleaner than the [`pyyaml`](../pyyaml) case,
where the equivalent iOS lib wheel leaves a stray `libyaml.so` behind to be lifted into a signed
framework. Nothing to configure and nothing to try to delete.

**`shapely.lib.__file__` is a `.fwork` path on iOS**, not a mangled `jniLibs` name as on Android.
serious_python turns each site-packages `.so` into a framework in the app bundle and leaves a
one-line `<name>.fwork` pointer file at the module's original path, and CPython's
`AppleFrameworkLoader` reports that pointer as `__file__`. Read it off the example's header line
rather than assuming either shape.

## Things to know

- **`STRtree.query` applies its predicate query-geometry-first, and getting the direction wrong
  returns an empty array with no error.** The signature is
  `predicate(query_geometry, tree_geometry)`, stated in
  [`STRtree.query`](https://shapely.readthedocs.io/en/stable/strtree.html#shapely.STRtree.query)'s
  docstring and enforced by nothing. So "which zone contains this point", with the zones in the
  tree, must be written `tree.query(point, predicate="within")`. On a tree of
  `box(i, 0, i+1, 1) for i in range(5)` queried with `Point(0.5, 0.5)`: `None`, `"intersects"`,
  `"within"` and `"covered_by"` all return `[0]`, while `"contains"`, `"covers"`,
  `"contains_properly"` and `"touches"` return `[]` — no exception, no warning. That failure is
  indistinguishable from "no points hit any zone", which is why the example computes the same
  count a second way. `predicate` accepts nine names (`intersects`, `within`, `contains`,
  `overlaps`, `crosses`, `touches`, `covers`, `covered_by`, `contains_properly`) plus `dwithin`,
  which needs `distance=` and raises `ValueError` without it. Anything else — `"disjoint"`, say —
  raises `ValueError` listing the valid set, so a *typo* is loud and only a *reversal* is silent.
- **`query_nearest` returns a `(2, n)` pair array even with `all_matches=False`.** Not the flat
  per-input index array the name suggests: 30 points against 12 zones gave shapes `(2, 30)` and
  `(30,)` for the distances, and `all_matches=True` gave `(2, 31)` because one tie duplicated its
  input. Unpack it as `input_idx, tree_idx = tree.query_nearest(...)`, and read the distances off
  the second return value rather than indexing the first. `tree.nearest()` is the one that returns
  a flat `(n,)` array, and `tree.query(array)` is `(2, n)` like `query_nearest`.
- **`shapely.ops.transform` with a multiplying callable silently returns duplicated,
  untransformed coordinates.** `transform(lambda x, y: (x*2, y*2), box(0, 0, 1, 1))` gives
  `POLYGON ((1 0, 1 1, 0 1, 0 0, 1 0, 1 0, 1 1, 0 1, 0 0, 1 0))` with bounds still `(0, 0, 1, 1)`;
  on a `LineString` it gives `LINESTRING (0 0, 1 1, 0 0, 1 1)`; on a `Point` it raises
  `ValueError: Point() takes only scalar or 1-size vector arguments`. The same call with `+ 1.0`
  is correct, which is what makes this look version- or geometry-specific instead of
  arithmetic-specific. The cause is visible in the shipped `shapely/ops.py`: the fast path hands
  the callable *tuples* of coordinates and only falls back to per-coordinate application on
  `TypeError` — and `tuple * 2` concatenates rather than raising, while `tuple + 1.0` raises. Use
  the 2.x array API [`shapely.transform(geom, lambda a: a*2)`](https://shapely.readthedocs.io/en/stable/reference/shapely.transform.html)
  (verified: bounds `(0, 0, 2, 2)`), or `shapely.affinity.scale`/`rotate`/`translate`, or make the
  callable numpy-aware (`lambda x, y: (np.asarray(x)*2, np.asarray(y)*2)` — also correct).
- **`to_wkt` rounds to 6 decimal places by default, so a WKT round trip is lossy.**
  `shapely.to_wkt(Point(1/3, 2/3))` is `POINT (0.333333 0.666667)`, and
  `equals_exact(from_wkt(to_wkt(pt)), pt, 0)` is then `False`. `rounding_precision=-1` gives the
  full `POINT (0.3333333333333333 0.6666666666666666)`. Persist geometry with
  [`to_wkb`/`from_wkb`](https://shapely.readthedocs.io/en/stable/reference/shapely.to_wkb.html)
  instead — binary, exact, and it round-tripped `equals_exact` on every zone in the example. Treat
  WKT as a display format. A WKB blob is an ordinary `bytes`, so it belongs in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  like any other file you own.
- **`prepare()` accelerates the *first* argument, and two functions have already done it for
  you.** Measured on the merged 240-zone footprint the [`zone-index`](examples/zone-index) example
  builds — 5,756 vertices, from its fixed seed — against 20,000 points, every call timed on a
  fresh `from_wkb` copy that had never been prepared: `shapely.contains` 13.5 ms → 4.5 ms,
  `intersects` 13.4 → 4.8, `covers` 13.4 → 4.9 — 2.7–3.0×. The *multiple* is as much a property
  of the geometry as of `prepare()`, so measure your own; the direction is the durable part. And
  `shapely.within(points, footprint)` stays at 13.0 → 13.3, because the footprint is argument *b*
  there; rewrite it as `contains(footprint, points)` to get the speedup.
  `contains_xy` / `intersects_xy` call `lib.prepare(geom)` themselves
  (`shapely/predicates.py`), mutating your geometry in place — `is_prepared` flips to `True` after
  one call — so calling `prepare()` before them buys nothing. Preparation is free to keep:
  `shapely.destroy_prepared` exists if you want the memory back.
- **Invalid geometry gives you a wrong number rather than an error.** A self-intersecting bowtie
  polygon reports `area` `0.0` — the two lobes cancel — with no exception anywhere.
  `shapely.is_valid_reason` on it returns `'Self-intersection[5 5]'`, and
  [`make_valid`](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html)
  turns it into 2 polygons totalling `50.0`, which is the right answer. Anything built by
  `buffer`, `union_all` or the other constructive functions is valid by construction; geometry you
  parse from WKB, WKT or GeoJSON is not, so validate at that boundary. GEOS predicates on invalid
  input are undefined, not erroring.
- **`shapely.geos_version` tells you what the wheel was *compiled* against, not what it loaded.**
  It is a string literal baked into `lib.so`: `GEOSversion` — the runtime query — is not among the
  GEOS symbols the extension imports at all. On Android those really are two different files, so a
  `flet-libgeos` bump that skipped a shapely rebuild would be invisible to anything printing the
  version. They agree today because the recipe pins the version and `Requires-Dist` carries it as
  `==`.
- **`import shapely.plotting` succeeds and then fails at the first call.** matplotlib is listed
  only under `extra == "docs"`, so with it absent the import is fine and
  `plot_polygon(...)` raises `ModuleNotFoundError: No module named 'matplotlib'` from the deferred
  `import matplotlib.pyplot` in `_default_ax`. In a Flet app an unhandled exception in a handler
  produces a crash screen, not a no-op. Either add matplotlib deliberately (there is a
  [recipe](../matplotlib)) or draw with Flet's own primitives —
  [`ft.canvas.Path`](https://flet.dev/docs/controls/canvas/) built from
  `shapely.get_coordinates` or `geom.exterior.coords`, plus `ft.canvas.Points`, which is what the
  example does.
- **Three modules exist only for shapely 1.x code.** `import shapely.geos` emits a
  `DeprecationWarning` at import (read versions off the top-level namespace instead:
  `shapely.geos_version_string`). `shapely.speedups.enable()` warns with `FutureWarning` and its
  `available`/`enabled` are hardcoded `True`. `shapely.vectorized.contains` warns too and is a
  wrapper over `shapely.contains` — use `shapely.contains_xy`. Shapely 2 is always fast; there is
  nothing to switch on.
- **Nothing in the API can raise `UnsupportedGEOSVersionError` on these wheels.** The highest
  `requires_geos(...)` anywhere in the shipped source is `3.12.0`, and every inline
  `lib.geos_version < (...)` check compares against `3.12.0` or lower, against a linked GEOS of
  3.13.1. The gated set — `coverage_is_valid`, `coverage_invalid_edges`, `coverage_simplify`,
  `get_m`, `has_m`, `disjoint_subset_union`, `disjoint_subset_union_all` at 3.12.0;
  `concave_hull`, `remove_repeated_points` at 3.11.0; `constrained_delaunay_triangles`,
  `segmentize`, `to_geojson`, `dwithin` at 3.10.0; `from_geojson` at 3.10.1 — was called and
  returned correct results on a version-matched desktop build, along with `make_valid`
  (including `method="structure"`), `orient_polygons`, `minimum_bounding_radius`,
  `to_ragged_array`, and the whole of `shapely.ops` (`unary_union`, `nearest_points`,
  `polygonize`, `triangulate`, `voronoi_diagram`, `split`, `substring`, `linemerge`, `snap`,
  `shared_paths`). Prepared geometries are complete too: 14 prepared predicates are in the import
  list, including the 3.12-era `ContainsXY`/`IntersectsXY` fast paths, and both spellings work —
  `shapely.prepare(geom)` and the legacy `shapely.prepared.prep(geom)`.
- **The Python half of the wheel is upstream's, byte for byte, and the GEOS is the desktop
  wheel's GEOS.** All 128 `.py`/`.pxd` files hash identically across the Android wheel, the iOS
  wheel and the same-version PyPI macOS wheel — the recipe carries no patches, which is why. And
  the version strings in the mobile extensions (`3.13.1`, `3.13.1-CAPI-1.19.2`) match
  `flet-libgeos`'s `geos_c.h`, and match what a desktop venv on `shapely==2.1.2` from PyPI
  reports, which bundles `libgeos.3.13.1.dylib` / `libgeos_c.1.19.2.dylib`. Upstream's
  documentation applies here without a translation step. What is *not* guaranteed is bit-for-bit
  identical floating-point output across platforms — same algorithms, different ISAs.
- **Size, and where it goes.** Everything but the extensions is 1,028,959–1,028,993 bytes on all
  six cp314 slices, the 34-byte spread being the extension filenames in `RECORD` and the platform
  tag in `WHEEL`:

  | slice | wheel | unpacked | the three `.so` |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 412 KB | 1,475 KB | 446 KB |
  | Android armeabi-v7a | 397 KB | 1,329 KB | 300 KB |
  | Android x86_64 | 429 KB | 1,490 KB | 461 KB |
  | iOS arm64 (device) | 3,434 KB | 10,818 KB | 9,789 KB |
  | iOS arm64 (simulator) | 3,515 KB | 10,862 KB | 9,833 KB |
  | iOS x86_64 (simulator) | 3,873 KB | 11,347 KB | 10,318 KB |

  Add `flet-libgeos` on top: 4.69 MB per ABI installed on Android, nothing installed on iOS.
  And note what dominates the small side — **576,296 bytes of every wheel, 39% of the unpacked
  Android arm64 total and 43% on armeabi-v7a, is upstream's own `shapely/tests` package** (82
  files plus `shapely/conftest.py`), against 43 `.py` files of actual library. Identical on both
  platforms. No app imports it.

## Build notes (maintainers)

Two recipes: `flet-libgeos` builds GEOS, `recipes/shapely` consumes it. The shapely half is one
`meta.yaml` with no patches and no `build.sh`, and every setting in it already carries
its own comment — the iOS `force_load` explanation in particular is long and self-contained — so
what is left here is shape and the bump checklist.

**`flet-libgeos` is `requirements.host`, not `requirements.host_build`.** `host_build` would put
it in the cross environment for the link and then not ship it: right on iOS, where GEOS is
statically absorbed, and fatal on Android, where all three extensions resolve `libgeos_c.so` by
bare soname at load time. One recipe has to satisfy both, so it is an ordinary runtime dependency
and appears in `Requires-Dist` on both platforms. On iOS that is redundant rather than harmful,
and Flet's cleanup empties the redundant wheel completely — unlike [`pyyaml`](../pyyaml)'s
equivalent, which leaves a stray `.so`. Same trade-off as [`lxml`](../lxml).

**`tests/test_shapely.py`'s docstrings describe a dependency the recipe does not declare.** Two
of them say the recipe has a "defensive `flet-libcpp-shared` host dep"; `requirements.host` is
exactly `[flet-libgeos 3.13.1, numpy ^2.0.0]`, with no such entry and no `sdk == 'android'`
block. libc++_shared does still reach the APK, but via numpy's own `Requires-Dist`, and GEOS
itself does not need it (`libgeos.so` needs only libm/libdl/libc and defines the C++ ABI symbols
as weak). Do not cite the tests for the dependency list; read `meta.yaml` and the wheel
`METADATA`. Fixing the docstrings is a separate change.

What to re-verify on a bump — a green build establishes almost none of what this page claims, and
a `flet-libgeos` bump moves GEOS underneath all of it:

- **The GEOS version, in three independent places**: `strings` on shapely's own `.so` (both
  platforms), `flet-libgeos`'s `opt/include/geos_c.h`, and the same-version PyPI desktop wheel.
  The "same GEOS as desktop" claim rests on all three matching, and because
  `shapely.geos_version` is compile-time, the shapely `.so` and `libgeos_c.so` can disagree
  silently on Android. Do not trust `shapely.geos_version_string` for this.
- **The version gates.** `grep -rn 'requires_geos(' shapely` and
  `grep -rn 'geos_version [<>]'` in the unpacked wheel. Today the ceiling is 3.12.0; a shapely
  release that starts gating on 3.14 or 3.15 would make part of
  [Things to know](#things-to-know) wrong and would raise the floor `flet-libgeos` has to meet.
- **The linkage split.** Android: `DT_NEEDED` still names `libgeos_c.so` with no
  `RPATH`/`RUNPATH`, and `flet-libgeos`'s two `SONAME`s still equal their basenames — those have
  to agree or nothing imports. iOS: still three self-contained `MH_DYLIB`s with 271 `_GEOS*`
  symbols each, `otool -L` naming no GEOS library, and the `GeometryComponentFilter::filter_ro`
  vtable present in each. If iOS ever links dynamically instead, the size table, the
  `Requires-Dist` reasoning and the "nothing to clean up" paragraph all change. Also re-check
  16 KB `PT_LOAD` alignment on all five Android objects.
- **`libc++_shared`.** Confirm the extensions still do not name it and `libgeos.so` still links
  libc++ statically. If GEOS ever starts needing it dynamically, the Android section is wrong and
  the recipe needs the host dep its tests already claim it has — and the tests would not catch it,
  because numpy drags libc++_shared in regardless.
- **Byte-identity with the desktop wheel.** Hash the `.py`/`.pxd` files against the same-version
  PyPI wheel. A new data file, a `.pyi` stub, or a diverging module would put both the
  no-`extract_packages` claim and "upstream's documentation applies" back in question — and a
  `.pyi` in particular is deleted by serious_python's junk-file globs, which is how lazy stub
  loaders break on device.
- **The measurements.** The threading figures, the 2.7–3.0× `prepare()` numbers, the
  index-versus-all-pairs times and the size table are all measured, most on desktop. Re-measure
  rather than scaling. The ratios transfer; the absolute times do not. The GIL half of
  [Threading](#threading) is a *source* claim as much as a measured one — re-run
  `grep -rn '@multithreading_enabled' shapely`: a release that decorates `io.py` or
  `coordinates.py` would move the "IO holds the GIL" half of that section.
- **The behavioural gotchas.** The reversed-predicate silence, `query_nearest`'s `(2, n)` shape,
  `ops.transform`'s tuple fast path, `to_wkt`'s default rounding and the auto-preparation inside
  `contains_xy` are all properties of shapely's Python layer, so a shapely bump can move any of
  them without the build noticing. They are the most consumer-visible claims here and the least
  protected: `tests/` asserts none of them.

`tests/test_shapely.py` covers import, a scalar predicate, buffer/intersection, the numpy bridge
and a `numpy.fft` libc++ canary — presence, essentially. Worth adding, in rough order of value:
the reversed-predicate pair (`tree.query(point, predicate="within")` non-empty and
`predicate="contains"` empty), which is the claim most likely to move and the one an app author
is most likely to get wrong; a WKB round trip asserting `equals_exact`, since nothing currently
touches IO; and one call into the 3.12-gated set (`coverage_is_valid` or `get_m`) so a
`flet-libgeos` downgrade turns CI red instead of turning a documented API into
`UnsupportedGEOSVersionError` on a device. Per the repo's test convention, assert relationships
rather than version numbers — the GEOS version belongs on the example's header line, not in an
assertion a bump has to chase.
