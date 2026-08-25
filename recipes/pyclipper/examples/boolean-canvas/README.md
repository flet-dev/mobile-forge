# pyclipper boolean canvas

One screen, three panels, and a number under each picture that says whether the picture is
right. Every polygon in the app is built in code from a handful of literal coordinates, so there
is no asset, no file read and no network — and every area pyclipper produces is checked against
one derived from the rectangle corners on paper, with the residual printed as a signed number.
On axis-aligned integer rectangles that residual reads exactly `+0.0`, which is the point: it is
a real check, not a tolerance.

What it demonstrates:

- **The four boolean operations.** An
  [`ft.SegmentedButton`](https://flet.dev/docs/controls/segmentedbutton/) switches between
  `CT_INTERSECTION`, `CT_UNION`, `CT_DIFFERENCE` and `CT_XOR` over the same two rectangles —
  A = (0,0)–(400,300) filled blue, B = (150,100)–(600,400) filled green, the result outlined in
  red on an [`ft.canvas.Canvas`](https://flet.dev/docs/controls/canvas/). Underneath, a
  pure-Python shoelace sum over the returned rings against the area the corners give by hand:
  50,000 for the intersection (1 path, 4 vertices), 205,000 for the union (1 path, 8), 70,000 for
  A minus B (1 path, 6) and 155,000 for XOR (2 paths, 12). The shoelace is **signed**, because
  `Execute` returns a flat list in which a hole would be a ring wound the other way, and only the
  signed total is the real area.
- **The float trap, side by side.** The same clip is then written in floats with fractional
  corners — A = (0,0)–(4,3), B = (1.5,0.5)–(6,4), true overlap 2.5 × 2.5 = 6.25. The left half of
  the canvas feeds those floats straight into `AddPath`: the result is drawn, its area prints as
  9.00, the residual as +2.75 (+44%), and **no exception is raised anywhere**, which is the whole
  lesson. The right half runs the identical floats through `scale_to_clipper` /
  `scale_from_clipper` and lands on 6.25 with residual +0.00. Two red outlines of visibly
  different size, with the arithmetic underneath.
- **Offsetting, and how it ends.** An [`ft.Slider`](https://flet.dev/docs/controls/slider/) sets a
  delta from −160 to +100 and a `PyclipperOffset` with `JT_MITER` / `ET_CLOSEDPOLYGON` dilates or
  erodes rectangle A, drawn in orange inside a fixed frame so the outline grows in a still
  picture. The reference here is exact and hand-derivable — a mitre-joined offset of a w × h
  axis-aligned rectangle by d has area (w + 2d)(h + 2d) — so the panel prints computed, expected
  and residual, and the residual is `+0.0` at every delta from +100 down to −140. At −150 and
  below it prints *eroded away — 0 paths, no exception*, because that is how an inward offset
  really ends.

The app deliberately never feeds a coordinate outside ±(2\*\*62 − 1). That path aborts the
process with SIGABRT and cannot be demonstrated safely; it is described in the recipe's
[Things to know](../../README.md#things-to-know) instead.

The app is two files. `src/polygons.py` owns the geometry: it runs every clip and offset, checks
each answer against the arithmetic, and hands back rings already projected into canvas pixels
plus the lines of text to print. `src/main.py` is Flet only — paints, controls, and the three
handlers that put one on the other.

Each panel's work sits in its own `try/except` that renders the exception class and message into
that panel, so a device-only failure is legible on screen instead of becoming a crash screen that
says nothing about which of the three calls failed. Nothing runs in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), on purpose:
every clip here is four vertices against four, and the panels print their own elapsed time —
median 0.001–0.002 ms per recompute on desktop once warm, over 200 repeats — so a background
thread would be pure overhead. The slider still drives its recompute from `on_change_end` rather
than `on_change`, which is the habit you want by the time the geometry is big enough to matter:
a thread only starts paying somewhere past ten thousand vertices per ring. Whatever you do move
off the UI thread, give it its own `Pyclipper` — sharing one between threads segfaults the
process, and [Threading](../../README.md#threading) has the measurements.

The header prints `pyclipper.__version__`, the platform, a coordinate read back out of the
engine, and `pyclipper._pyclipper.__file__`. The coordinate is measured rather than asserted:
2\*\*40 goes in through `AddPath` and comes back out of `GetBounds`, which is how a 32-bit
Android ABI would betray itself, and it stays far below the ±(2\*\*62 − 1) limit the same line
quotes. The `__file__` is where you see Flet's relocation of the extension out of
site-packages, and is the reason not to locate anything relative to it — it is read with
`getattr(..., "__file__", None)` and prints `no __file__` when absent, because on Android a
relocated extension may have no `__file__` at all, and writing it plainly would raise while
`page.add` is building the header — a crash screen rather than a panel. The whole header sits in
its own `try/except` for the same reason.

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
