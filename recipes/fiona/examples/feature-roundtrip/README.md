# fiona feature roundtrip

Four vector layers written into app storage, read back through a fresh
[`fiona.open`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.open), and compared
feature by feature against the in-memory records they were built from. The reference is
those records — nothing fiona derived — so every number on screen is a residual rather than
a claim.

The features are generated from a formula in `src/vectors.py`, written into
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
with an explicit `driver=`, and read straight back. It ships no data file, bundles no
`proj.db` and reaches no network.

Every probe in `src/vectors.py` runs inside its own `try/except` and returns
`type(err).__name__` and `str(err)` as a result line for `src/main.py` to render. That is
the point of the app as much as the round trip is: an unhandled exception in a Flet handler
ends the session with a crash screen, which would throw away exactly the diagnosis this
example exists to capture — and the write path's `fiona._err.FionaNullPointerError` is not
a `fiona.errors.FionaError`, so a narrower `except` would miss it anyway.

What it demonstrates:

- **Which side of the iOS split this build is on.** Section 2 prints the driver table
  [`fiona.Env()`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.env.Env) registers
  into, and section 3 exercises the one `fiona.open` reads. On Android those are the same
  shared `libgdal.so`. On iOS they are separate statically linked copies, so section 2 is
  expected to be a false green light and is printed directly above section 3 for that
  reason.
- **A round trip that checks itself**, for `GeoJSON` and `ESRI Shapefile` × `Point` and
  `Polygon`: feature count, geometry type per feature, worst absolute coordinate residual,
  worst float-property residual, and mismatched integer and string properties. On a desktop
  every layer reports `ROUND TRIP OK`, with worst coordinate residuals of 5.38e-17 (GeoJSON
  points), 1.42e-14 (GeoJSON polygons) and 0 (both Shapefiles).
- **What a Shapefile actually leaves on disk** — four files, listed with their combined
  size, which is why each layer gets its own directory.
- **The read-back schema as information, not an assertion.** The same
  `{"name": "str", "n": "int", "v": "float"}` comes back as `n: int32` from GeoJSON and as
  `name: str:80, n: int:18, v: float:24.15` from a Shapefile.
- **Where the missing PROJ database bites** —
  [`CRS.from_string("+proj=…")`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.crs.CRS.from_string)
  beside
  [`CRS.from_epsg(4326)`](https://fiona.readthedocs.io/en/stable/fiona.html#fiona.crs.CRS.from_epsg),
  both run rather than described. No CRS is passed to any layer, which keeps the driver
  question separate from the database question.
- **What [`fiona.transform`](https://fiona.readthedocs.io/en/stable/fiona.html#module-fiona.transform)
  costs to reach.** It is the one extension `import fiona` does not load, so importing it is
  a decision rather than a side effect — and on iOS it maps another statically linked copy of
  GDAL, tens of megabytes for that one line. The card reprojects a point through it, so the
  import is shown working rather than merely attempted; both CRSs are proj-strings, which
  keeps the missing `proj.db` out of that answer.
- **The cost of a real dataset, measured.** A [`ft.Slider`](https://flet.dev/docs/controls/slider/)
  from 10 to 2000 features re-runs the four round trips from
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and
  reports elapsed milliseconds and bytes on disk per layer. The worker opens and closes
  every `Collection` inside its own thread, because sharing one across threads silently
  returns wrong feature counts, and the slider disables itself for the duration, because
  `run_thread` submits to a shared pool and two overlapping runs clear each other's layer
  directories mid-write — which surfaces as `FileExistsError` and
  `DriverError: Failed to create GeoJSON datasource` under fiona's name.

Polygon rings are wound clockwise on purpose. An ESRI Shapefile rewrites a
counter-clockwise outer ring into clockwise order, so a counter-clockwise polygon comes back
with its vertices reversed and the comparison reports a coordinate mismatch that is really a
format convention.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

There is no useful desktop run: fiona 1.10.1 publishes no CPython 3.14 wheel, and its sdist
needs a system GDAL, so `pyproject.toml` declares it under `[tool.flet.android]` and
`[tool.flet.ios]` rather than in `[project] dependencies` — which means only an `apk`, `ipa`
or `ios-simulator` build carries it. `uv run flet run` starts and shows a card naming the
missing module instead of crashing.
