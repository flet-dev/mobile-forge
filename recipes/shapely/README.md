# shapely

[`shapely`](https://shapely.readthedocs.io/) is Python's 2D geometry library: points, lines and
polygons, the predicates between them (`contains`, `intersects`, `within`, `touches`), the set
operations (`union`, `intersection`, `difference`, `buffer`), and an
[`STRtree`](https://shapely.readthedocs.io/en/stable/strtree.html) spatial index over any of it.
It is a thin binding over [GEOS](https://libgeos.org/), the C++ engine behind PostGIS and QGIS.

What it is worth carrying on a phone is the index and the vectorisation. A geofence check, a
"which zone am I standing in" lookup, clipping a recorded track to a boundary, merging coverage
areas — each of those is a nested loop over geometry if you write it yourself, and shapely 2.x
turns it into one call over numpy arrays with a GEOS-side index underneath, computed on the
device.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "shapely",
]
```

There are two APIs in the package and they take different arguments. The 1.x object API is
scalar — `shapely.Point(x, y).buffer(3.0).contains(other)` — and crosses into GEOS one geometry
at a time. The 2.x module-level functions are ufuncs: they accept numpy arrays of geometries
(object dtype) or plain coordinate arrays, broadcast like any other ufunc, and return numpy
arrays — `shapely.points(xs, ys)`, `shapely.buffer(geoms, r)`, `shapely.contains(zones, points)`,
`shapely.area(zones)`. Both are in the wheel and both work. The array form is the one worth
shipping to a device, and everything below assumes it.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`zone-index`](examples/zone-index) — point-in-zone and nearest-zone queries answered through
  an `STRtree`, and then again with no index at all.

## Usage in a Flet app

```python
import flet as ft
import shapely

zones = shapely.buffer(shapely.points(xs, ys), 3.0)  # numpy array of polygons
tree = shapely.STRtree(zones)

# the predicate reads (query_geometry, tree_geometry), so "which zone is this
# point within" is spelled `within` — see Things to know
hits = tree.query(shapely.Point(x, y), predicate="within")

status = ft.Text(f"inside {hits.size} zone(s)")
```

[`tree.query`](https://shapely.readthedocs.io/en/stable/strtree.html#shapely.STRtree.query)
returns indices into the tree, so `zones[hits]` is the geometry and any parallel array of your
own — names, colours, ids — indexes the same way. Pass an array of points instead of one and the
return becomes a `(2, n)` array of `(point index, zone index)` pairs.

### Spatial indexing

The index is the difference between an answer and a stall. At 240 zones against 4,000 points on
a desktop, `tree.query(points, predicate="within")` took 1.1 ms against 30 ms for the same
answer from the all-pairs boolean matrix `shapely.within(points[:, None], zones[None, :])`, and
nearest-zone was 17 ms against 246 ms. A phone is slower than that machine, so treat the ratio
as the durable part — and note it widens with the zone count, because the all-pairs form grows
as N×M. The [`zone-index`](examples/zone-index) example computes both on device and prints the
two times next to each other.

Build the tree once — at startup, or when the zone set changes — and keep it for the life of the
screen. Construction is the one `STRtree` operation that holds the GIL (see below), and the tree
is immutable: there is no insert, so a changed zone set means a new tree.

### Storage

Persist geometry as [WKB](https://shapely.readthedocs.io/en/stable/reference/shapely.to_wkb.html),
which is binary and exact. `shapely.to_wkb` over an array returns one `bytes` object per
geometry rather than one blob, so wrap the set in a collection when it is going into a single
file. Ordinary `bytes` belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
like any other file you own:

```python
import os
import shapely

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "zones.wkb")

with open(path, "wb") as fh:
    fh.write(shapely.to_wkb(shapely.GeometryCollection(list(zones))))

with open(path, "rb") as fh:
    zones = shapely.get_parts(shapely.from_wkb(fh.read()))
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can recompute — a simplified outline for drawing, a merged footprint — and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for throwaway intermediates. Zone data shipped with the app is an asset: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).
Often no file is needed at all — WKB in memory is what moves geometry between a worker and the
UI.

### Threading

**The array calls release the GIL; the IO calls hold it.** Predicates, measurement, constructive
operations, set operations and every `STRtree` *query* release it, so a query in a
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) worker
genuinely runs alongside the UI. Serialising to WKB or WKT, pulling coordinates out with
`get_coordinates`, and *constructing* an `STRtree` do not, and block the UI thread for their
whole duration. Measured on desktop with a counting thread spinning beside one long call,
`area`, `within`, `points`, `simplify`, `union_all`, `equals_exact`, `tree.query`,
`tree.query_nearest` and `tree.nearest` left that counter at 32–139% of its undisturbed rate,
while `to_wkb`, `from_wkb`, `to_wkt`, `to_geojson`, `get_coordinates` and `STRtree` construction
starved it to 0–5% — the same as a deliberately GIL-holding control. Four threads over four
separate point arrays then scaled `shapely.within` 2.07×, `shapely.buffer` 1.82× and
`tree.query` 1.58×, against `to_wkb` 1.05× and `get_coordinates` 0.88×, which is what a
pure-Python loop manages. Nothing in the package starts a thread of its own.

**One `STRtree` is safe to share.** Eight threads against one tree, each asking a *different*
question of a *different* 10,000-point slice — `query` under three predicates, `nearest`,
`query_nearest`, `contains` against a shared polygon, `distance`, `bounds`, 25 repetitions each
— every answer matched what the same call returned serially, with no exceptions. There is no
handle to serialise behind a lock here, unlike a database connection.

**What is not safe is writing into a geometry array while another thread reads it.** The array
API sets `arr.flags.writeable = False` on every object-dtype argument for the duration of a call
and restores it in a `finally`, so a second thread assigning into that same array mid-call gets
`ValueError: assignment destination is read-only`. Give each thread its own array, or treat a
geometry array as immutable once built, which is the shapely 2.x idiom anyway. Plain float
coordinate arrays are untouched by this.

Flet's own rules apply on top. `run_thread` never retrieves the worker's future, so an exception
inside one vanishes without a log — wrap the body in `try/except`. Auto-update does not reach
background threads, so end the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). And disabling the
control that started the run is not by itself a guard: `run_thread` submits to a shared pool
while that `disabled` is still only queued for the client, so read the flag back before
dispatching, or a second gesture puts a second worker on the same controls.

### App size

Expect approximately 0.40–0.43 MB of compressed wheel and 1.3–1.5 MB unpacked per Android ABI,
against 3.4–3.9 MB compressed and 10.8–11.3 MB unpacked per iOS slice. The gap is GEOS: iOS
links it into the extensions, while Android loads it from a separate pair of shared libraries
that add a further 4.7 MB **per ABI** on top of the figures above.

Upstream's own test suite is about 0.58 MB of every one of those wheels — 39% of the unpacked
Android arm64 total, 43% on armeabi-v7a — and no application imports it. It is the one part
worth naming yourself:

```toml
[tool.flet.cleanup]
package_files = ["shapely/tests"]
```

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI. That lever is worth more here than the wheel figures suggest,
because the 4.7 MB of GEOS is carried once per ABI. These numbers describe the package payload,
not the amount added to the final APK or IPA; packaging and compression determine that.

### Other considerations

A desktop `flet run` installs PyPI's wheel, which bundles GEOS at the same version this recipe
pins, and the Python half of both wheels is upstream's own, unpatched. Upstream's documentation
therefore applies without translation, and so does anything you prototype on your laptop. Two
things still differ on a device.

`shapely.lib.__file__` is not a usable path on either platform. Flet moves every compiled
extension out of site-packages: on Android into `jniLibs`, leaving a mangled bare filename at
the attribute, and on iOS into a framework inside the app bundle, leaving a one-line `.fwork`
pointer file whose path is what `__file__` then reports. Nothing inside shapely reads
`__file__`, so the library does not care — but your own code that locates a resource relative to
a native module's `__file__` breaks here. The example prints the value in its header line, so
you can read the real answer off the device.

Floating-point results are not guaranteed bit-for-bit identical to your laptop's: same GEOS,
same algorithms, different instruction set. Compare geometry with
`shapely.equals_exact(a, b, tolerance)` rather than `==` on coordinates, and do not assert a
desktop-computed WKT string in a test that runs on device.

Leave Flet's [compilation](https://flet.dev/docs/publish/#compilation-and-cleanup) enabled. No
module in the package reads its own source, so compiling to `.pyc` is safe, and the only files
the default cleanup takes are the two `.pxd` Cython headers, which exist to build *against*
shapely rather than to run it.

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
  which needs `distance=` and raises `ValueError` without it. Anything else — `"disjoint"`, say
  — raises `ValueError` listing the valid set, so a *typo* is loud and only a *reversal* is
  silent.
- **`query_nearest` returns a `(2, n)` pair array even with `all_matches=False`.** Not the flat
  per-input index array the name suggests: 30 points against 12 zones gave shapes `(2, 30)` and
  `(30,)` for the distances, and `all_matches=True` gave `(2, 31)` because one tie duplicated
  its input. Unpack it as `input_idx, tree_idx = tree.query_nearest(...)`, and read the
  distances off the second return value rather than indexing the first. `tree.nearest()` is the
  one that returns a flat `(n,)` array, and `tree.query(array)` is `(2, n)` like
  `query_nearest`.
- **`shapely.ops.transform` with a multiplying callable silently returns duplicated,
  untransformed coordinates.** `transform(lambda x, y: (x*2, y*2), box(0, 0, 1, 1))` gives
  `POLYGON ((1 0, 1 1, 0 1, 0 0, 1 0, 1 0, 1 1, 0 1, 0 0, 1 0))` with bounds still
  `(0, 0, 1, 1)`; on a `LineString` it gives `LINESTRING (0 0, 1 1, 0 0, 1 1)`; on a `Point` it
  raises `ValueError: Point() takes only scalar or 1-size vector arguments`. The same call with
  `+ 1.0` is correct, which is what makes this look version- or geometry-specific instead of
  arithmetic-specific. The cause is visible in the shipped `shapely/ops.py`: the fast path hands
  the callable *tuples* of coordinates and only falls back to per-coordinate application on
  `TypeError` — and `tuple * 2` concatenates rather than raising, while `tuple + 1.0` raises.
  Use the 2.x array API
  [`shapely.transform(geom, lambda a: a*2)`](https://shapely.readthedocs.io/en/stable/reference/shapely.transform.html)
  (verified: bounds `(0, 0, 2, 2)`), or `shapely.affinity.scale`/`rotate`/`translate`, or make
  the callable numpy-aware (`lambda x, y: (np.asarray(x)*2, np.asarray(y)*2)` — also correct).
- **`to_wkt` rounds to 6 decimal places by default, so a WKT round trip is lossy.**
  `shapely.to_wkt(Point(1/3, 2/3))` is `POINT (0.333333 0.666667)`, and
  `equals_exact(from_wkt(to_wkt(pt)), pt, 0)` is then `False`. `rounding_precision=-1` gives the
  full `POINT (0.3333333333333333 0.6666666666666666)`. Treat WKT as a display format and
  persist with `to_wkb`/`from_wkb`, which round-tripped `equals_exact` on every zone in the
  example.
- **`prepare()` accelerates the *first* argument, and two functions have already done it for
  you.** Measured on the merged 240-zone footprint the [`zone-index`](examples/zone-index)
  example builds — 5,756 vertices, from its fixed seed — against 20,000 points, every call timed
  on a fresh `from_wkb` copy that had never been prepared: `shapely.contains` 13.5 ms → 4.5 ms,
  `intersects` 13.4 → 4.8, `covers` 13.4 → 4.9, so 2.7–3.0×. The *multiple* is as much a
  property of the geometry as of `prepare()`, so measure your own; the direction is the durable
  part. And `shapely.within(points, footprint)` stays at 13.0 → 13.3, because the footprint is
  argument *b* there; rewrite it as `contains(footprint, points)` to get the speedup.
  `contains_xy` / `intersects_xy` call `lib.prepare(geom)` themselves, mutating your geometry in
  place — `is_prepared` flips to `True` after one call — so calling `prepare()` before them buys
  nothing. Preparation is free to keep: `shapely.destroy_prepared` exists if you want the memory
  back.
- **Invalid geometry gives you a wrong number rather than an error.** A self-intersecting bowtie
  polygon reports `area` `0.0` — the two lobes cancel — with no exception anywhere.
  `shapely.is_valid_reason` on it returns `'Self-intersection[5 5]'`, and
  [`make_valid`](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html)
  turns it into 2 polygons totalling `50.0`, which is the right answer. Anything built by
  `buffer`, `union_all` or the other constructive functions is valid by construction; geometry
  you parse from WKB, WKT or GeoJSON is not, so validate at that boundary. GEOS predicates on
  invalid input are undefined, not erroring.
- **`shapely.geos_version` tells you what the wheel was *compiled* against, not what it loaded.**
  It is a string literal baked into `lib.so`; `GEOSversion`, the runtime query, is not among the
  GEOS symbols the extension imports at all. On Android those really are two different files, so
  a GEOS bump that skipped a shapely rebuild would be invisible to anything printing the
  version.
- **`import shapely.plotting` succeeds and then fails at the first call.** matplotlib is listed
  only under `extra == "docs"`, so with it absent the import is fine and `plot_polygon(...)`
  raises `ModuleNotFoundError: No module named 'matplotlib'` from the deferred
  `import matplotlib.pyplot` in `_default_ax`. In a Flet app an unhandled exception in a handler
  produces a crash screen, not a no-op. Either add matplotlib deliberately (there is a
  [recipe](../matplotlib)) or draw with Flet's own primitives —
  [`ft.canvas.Path`](https://flet.dev/docs/controls/canvas/) built from
  `shapely.get_coordinates` or `geom.exterior.coords`, plus `ft.canvas.Points`, which is what
  the example does.
- **Three modules exist only for shapely 1.x code.** `import shapely.geos` emits a
  `DeprecationWarning` at import (read versions off the top-level namespace instead:
  `shapely.geos_version_string`). `shapely.speedups.enable()` warns with `FutureWarning` and its
  `available`/`enabled` are hardcoded `True`. `shapely.vectorized.contains` warns too and is a
  wrapper over `shapely.contains` — use `shapely.contains_xy`. Shapely 2 is always fast; there
  is nothing to switch on.
- **Nothing in the API can raise `UnsupportedGEOSVersionError` on these wheels.** The highest
  `requires_geos(...)` in the shipped source is 3.12.0, against a linked GEOS well above it, so
  the whole gated set is live — `coverage_is_valid`, `coverage_simplify`, `get_m`, `has_m`,
  `disjoint_subset_union`, `concave_hull`, `remove_repeated_points`,
  `constrained_delaunay_triangles`, `segmentize`, `to_geojson`, `from_geojson` and `dwithin` —
  along with `make_valid(method="structure")`, `orient_polygons`, `to_ragged_array` and the
  whole of `shapely.ops`. Prepared geometry is complete too: 14 prepared predicates including
  the `ContainsXY`/`IntersectsXY` fast paths, under both spellings (`shapely.prepare(geom)` and
  the legacy `shapely.prepared.prep(geom)`).

## Build notes (maintainers)

### Recipe shape

Two recipes: `flet-libgeos` builds GEOS, `recipes/shapely` consumes it. The shapely half is one
`meta.yaml` with no patches and no `build.sh`, and every setting in it carries its own comment —
the iOS `force_load` explanation in particular is long and self-contained — so what is left here
is shape and the bump checklist.

**`flet-libgeos` is `requirements.host`, not `requirements.host_build`.** `host_build` would put
it into the cross environment for the link and then not ship it: correct on iOS, where GEOS is
statically absorbed into the extensions, and fatal on Android, where all three extensions
resolve `libgeos_c.so` by bare soname at load time. One recipe has to satisfy both, so it is an
ordinary runtime dependency and appears in `Requires-Dist` on both platforms.

That works on Android because the extensions name exactly `libgeos_c.so` in `DT_NEEDED` with no
`SONAME`, `RPATH` or `RUNPATH`; `libgeos_c.so` in turn needs `libgeos.so`, and both carry a
`SONAME` equal to their own basename. `flet-libgeos` ships those two as `opt/lib/*.so`, and
serious_python's Gradle `copyOpt` task copies every `.so` under a wheel's `opt/` into
`jniLibs/<abi>/` under its plain basename — which is what makes a bare soname resolve. On iOS
each of `lib`, `_geos` and `_geometry_helpers` is instead a self-contained `MH_DYLIB` that
defines its own copy of the GEOS symbols and binds 137 libc++/libc++abi symbols per extension
flat-namespace against the OS at `dlopen`. No extension depends on another there, so there is no
install-name relocation to arrange. The `Requires-Dist` entry is redundant on iOS but harmless:
that wheel's payload is `libgeos.a`, `libgeos_c.a` and headers, all of which Flet's default
cleanup removes, leaving the installed wheel as nothing but its own `dist-info`.

The wheel needs no `extract_packages` entry and no loader shim. Its entries are `.py`, `.pxd`,
three extensions and `dist-info` — no data file and no `.pyi` stub — nothing outside upstream's
own `shapely/tests` package touches `__file__`, `importlib.resources`, `pkgutil`,
`pkg_resources` or `ctypes`, and all three extension filenames carry a full CPython ABI tag,
which is what Android's relocation needs. So it runs as-is from zipped site-packages. PyPI does
not shadow it either: upstream's own release carries no Android or iOS tag, and this wheel
requires `flet-libgeos`, which exists only on this index.

**`tests/test_shapely.py`'s docstrings describe a dependency the recipe does not declare.** Two
of them claim a "defensive `flet-libcpp-shared` host dep"; `requirements.host` has no such entry
and no `sdk == 'android'` block. `libc++_shared.so` does still reach the APK, but through the
mobile numpy wheel's own `Requires-Dist`, and GEOS does not need it — `libgeos.so` links libc++
statically, requires only libm/libdl/libc, and defines the C++ ABI symbols weakly. Read
`meta.yaml` and the wheel `METADATA` for the dependency list, not the test docstrings. Fixing
them is a separate change.

### Upgrade hazards

- **A `flet-libgeos` bump moves GEOS underneath every claim on this page.** Bump the two
  together or not at all, and remember that `shapely.geos_version` is compile-time, so on
  Android shapely's `.so` and `libgeos_c.so` can disagree in silence.
- **The version gates.** Today the ceiling in the shipped source is `requires_geos(3.12.0)`. A
  shapely release that starts gating on 3.14 or 3.15 raises the floor `flet-libgeos` has to meet
  and makes the `UnsupportedGEOSVersionError` bullet in **Things to know** wrong.
- **The behavioural gotchas are Python-layer behaviour**, so a shapely bump can move any of them
  without the build noticing. They are the most consumer-visible claims here and the least
  protected — see **Coverage gaps**.
- **If iOS ever links GEOS dynamically instead of absorbing it**, the size figures, the
  `Requires-Dist` reasoning and the "nothing to clean up on iOS" statement all change together.

### Re-verification checklist

- **The GEOS version, in three independent places:** `strings` on shapely's own `.so` on both
  platforms, `flet-libgeos`'s `opt/include/geos_c.h`, and the same-version PyPI desktop wheel.
  The "same GEOS as desktop" claim rests on all three matching. Do not trust
  `shapely.geos_version_string` for this.
- **The version gates:** `grep -rn 'requires_geos(' shapely` and `grep -rn 'geos_version [<>]'`
  in the unpacked wheel.
- **Android linkage:** `DT_NEEDED` still names `libgeos_c.so` with no `RPATH`/`RUNPATH`, and
  `flet-libgeos`'s two `SONAME`s still equal their basenames — those have to agree or nothing
  imports. Re-check 16 KB `PT_LOAD` alignment on all five native objects while you are there.
- **iOS linkage:** still three self-contained `MH_DYLIB`s, `otool -L` naming no GEOS library,
  and the `GeometryComponentFilter::filter_ro` vtable present in each.
- **`libc++_shared`:** the extensions still do not name it and `libgeos.so` still links libc++
  statically. The device tests cannot catch a regression here, because numpy drags
  `libc++_shared.so` in regardless.
- **Byte-identity with the desktop wheel:** hash the `.py`/`.pxd` files against the same-version
  PyPI wheel. A new data file, a `.pyi` stub or a diverging module would put both the
  no-`extract_packages` claim and "upstream's documentation applies" back in question — and a
  `.pyi` in particular is deleted by serious_python's junk-file globs, which is how lazy stub
  loaders break on device.
- **The measurements:** the threading figures, the 2.7–3.0× `prepare()` numbers, the
  index-versus-all-pairs times and the size figures are all measured, most on desktop.
  Re-measure rather than scaling; the ratios transfer and the absolute times do not. The GIL
  half of **Threading** is a source claim as much as a measured one — re-run
  `grep -rn '@multithreading_enabled' shapely`, because a release that decorates `io.py` or
  `coordinates.py` moves it.

### Coverage gaps

`tests/test_shapely.py` covers import, a scalar predicate, buffer and intersection, the numpy
bridge, and a `numpy.fft` libc++ canary — presence, essentially. It asserts none of the
behaviour in **Things to know**, touches no IO path, and calls nothing from the 3.12-gated set.
Worth adding, in rough order of value: the reversed-predicate pair
(`tree.query(point, predicate="within")` non-empty and `predicate="contains"` empty), which is
the claim most likely to move and the one an app author is most likely to get wrong; a WKB round
trip asserting `equals_exact`; and one gated call (`coverage_is_valid` or `get_m`) so a GEOS
downgrade turns CI red instead of turning a documented API into an exception on a device. Per
the repo's test convention, assert relationships rather than version numbers.
