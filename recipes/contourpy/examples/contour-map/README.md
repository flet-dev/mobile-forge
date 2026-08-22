# contourpy contour map

A contour map computed on the device and drawn as real geometry — no image, no plotting library.
Seven filled bands from `filled()` and six isolines from `lines()`, both traced by contourpy's C++
core and handed straight to an [`ft.canvas.Canvas`](https://flet.dev/docs/controls/canvas/) as
[`Path`](https://flet.dev/docs/controls/canvas/path) subpaths. Underneath the picture, two numbers
that say whether the picture is right.

What it demonstrates:

- **Contours as geometry rather than pixels.** The field is four fixed Gaussian bumps on the unit
  square — a peak, a pit, a ridge and a notch — built in code from sixteen literal numbers, so
  there is no asset, no file read and no network, and the same input gives the same picture on
  every device. The levels are fixed at −0.6 … 0.8 in steps of 0.2 rather than derived from the
  data, so changing the grid changes the resolution of the answer and nothing else. `filled()`
  returns each band's outer boundary with its holes wound the opposite way, which is what lets one
  `Path` carrying several subpaths cut the holes out under the non-zero fill rule. They are real
  holes: at 65×65 the seven bands come back as twelve enclosed areas, eight of which carry a hole
  and one of which carries two.
- **A slider over grid resolution, from 33×33 to 129×129.** The stats line reports what came back:
  at 65×65, 7 bands, 21 rings, 2,267 vertices of filled polygon and 949 vertices of isoline; at
  129×129, 4,503 and 1,887. That is the number that costs you — the whole canvas is 8 shapes
  holding 1,638 path elements at the smallest grid and 6,411 at the largest.
- **All four algorithms, timed side by side and checked against each other.** An
  [`ft.SegmentedButton`](https://flet.dev/docs/controls/segmentedbutton/) chooses which one draws;
  the table under it runs all four every time and prints each one's elapsed milliseconds, its
  default `line_type` and `fill_type`, and how far its isolines differ from `serial`'s. `mpl2005`
  and `mpl2014` return their results in a different format (`SeparateCode` / `OuterCode` against
  `Separate` / `OuterOffset`), which the app converts with `convert_lines` and `convert_filled`.
  The comparison is by **total contour length** rather than vertex against vertex on purpose: a
  closed ring is free to start at a different vertex and does. Measured on desktop at all seven of
  the slider's stops, that column reads `Δlength 0.0e+00` for `threaded` every time and `4.4e-16`
  for `mpl2014` every time; `mpl2005` reads `4.4e-16` at six stops and `2.2e-16` at 49×49.
- **A contour whose answer is known in advance.** The second field is `z = x² + y²` over
  `[-1.5, 1.5]²`, whose contour at `z = 1` is exactly the unit circle: area π, perimeter 2π. The
  app traces it at the same grid resolution and prints the shoelace area and the summed edge
  length against those two constants, with the relative error. It is always slightly small,
  because the traced polygon is inscribed — −0.30835% at 33×33, −0.07271% at 65×65, −0.01880% at
  129×129 — and the error falls roughly with the square of the grid spacing. That is the panel to
  watch while dragging the slider.

The header prints the two package versions, the platform, `contourpy.max_threads()` and the
extension's `__file__`, which shows as `no __file__` where the device has none. Both of those last
two are things only a device can tell you.

`src/field.py` owns the contourpy work and returns plain numbers and arrays; `src/main.py` owns
the page, the canvas paths and the worker thread. Every generator is built inside the worker
rather than shared across taps, because
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) submits to a
pool and two quick taps genuinely overlap. The slider fires from `on_change_end` rather than
`on_change` for the same reason, which is the habit you want once the grid is large enough for it
to matter — on desktop one full recompute, all four algorithms plus the circle check plus every
canvas shape, took between 2.6 and 20 ms across the twenty-eight grid-and-algorithm combinations.

The app never sets `chunk_count`, so `threaded` here runs on one thread and matches `serial` — by
design, because chunking cuts rings at the chunk boundaries and this app draws whole rings.

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
