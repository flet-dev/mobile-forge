# shapely zone index

A map-shaped workload where every number on screen is computed twice. From a fixed seed the app
generates N circular zones and M sample points, builds a
[`shapely.STRtree`](https://shapely.readthedocs.io/en/stable/strtree.html) over the zones, and
asks it two questions — *which zone is each point inside* and *which zone is nearest* — then
answers both again with no index at all, all-pairs, and prints whether the two agree.

The slider picks the workload, from 30 zones × 500 points up to 240 × 4,000. Nothing is
downloaded and nothing is bundled: the zones are
[`shapely.buffer`](https://shapely.readthedocs.io/en/stable/reference/shapely.buffer.html) circles
around random centres, so the same run is reproducible on any device.

What it demonstrates:

- **The index against the honest answer.** `tree.query(points, predicate="within")` gives
  point-in-zone pairs; `shapely.within(points[:, None], zones[None, :])` gives the full boolean
  matrix. The screen shows both pair counts and both point counts, and an **AGREE / DISAGREE**
  verdict that additionally compares the two per-point tallies element by element. That verdict
  exists because `STRtree` applies its predicate query-geometry-first — write the
  plausible-looking `predicate="contains"` here and you get an empty array with no error, no
  warning and no exception, which looks exactly like "no points hit any zone". Same for nearest:
  `tree.query_nearest(..., return_distance=True)` against
  `shapely.distance(points[:, None], zones[None, :]).min(axis=1)`, reporting how many of the M
  distances match to 1e-9.
- **What the index is worth.** Both times are on screen. Measured on desktop at the top level:
  1.1 ms through the tree against 30 ms all-pairs for containment, and 17 ms against 246 ms for
  nearest-zone.
- **The overlap the index exists to find.** `shapely.union_all(zones)` against a naive sum of
  `shapely.area` — 3974.3 separately, 3346.6 merged, so 627.7 counted twice at 240 zones.
- **Persisting geometry losslessly.** The zone set round-trips through
  [`to_wkb`/`from_wkb`](https://shapely.readthedocs.io/en/stable/reference/shapely.to_wkb.html)
  and every zone is asserted `equals_exact` afterwards, with the byte count shown. `to_wkt` would
  round to six decimals by default and fail that check.
- **What `prepare()` actually buys.** `shapely.contains(footprint, points)` is timed on a fresh
  geometry and on a prepared one, with the answers compared.
- **That invalid geometry lies rather than raising.** One deliberately self-intersecting polygon
  reports `area` 0.0; `is_valid_reason` and
  [`make_valid`](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html) are
  printed next to it.
- **Which file the import system actually resolved.** The header line prints
  `shapely.lib.__file__`, which is where you see Flet's relocation of the extension — a mangled
  `jniLibs` name on Android, a `.fwork` path inside the bundle on iOS — alongside the shapely,
  GEOS, numpy and Python versions the device is really running.

The run happens in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread),
driven from the slider's `on_change_end` so it fires once per gesture rather than once per pixel —
the all-pairs half is the expensive one and it grows as N×M. Disabling the slider is not on its own
enough to keep two runs from overlapping: that only queues the new state for the client, and
`run_thread` submits to a shared pool, so the handler reads `disabled` back as its guard and a
release arriving inside that window is dropped. The caption is then rewritten from the *result*
rather than from the thumb, so a dropped release cannot leave the label and the numbers describing
different levels. The worker body is wrapped in `try/except`, blanks the rows and the map before it
reports a failure — numbers from the previous level left under a fresh error read as that error's
own output — and ends in an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because `run_thread`
discards whatever a worker raises and auto-update does not reach background threads.

Underneath the numbers, an [`ft.canvas.Canvas`](https://flet.dev/docs/controls/canvas/) draws the
merged footprint as one `Path` per part, built from each polygon's ring coordinates, with the
sample points over it in two colours for inside and outside.
The picture is deliberately secondary and deliberately cheap: the outline is thinned by
`shapely.simplify` and the points are strided, because a phone-sized canvas cannot usefully show
5,756 vertices or 4,000 dots. The counts and the AGREE verdict are the deliverable.

`requires-python` is `>=3.11`, not the `>=3.10` that `flet create` writes: shapely pulls numpy in
unconditionally, the newest numpy on Flet's mobile index is 2.4.6 whose own `Requires-Python` is
`>=3.11`, and that index carries no cp310 numpy wheel at any version. `uv lock` on this
`pyproject.toml` alone resolves 55 packages.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
