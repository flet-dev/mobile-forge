# contourpy contour map

A contour map computed on the device and drawn as real geometry — no image, no plotting library.
Seven filled bands from `filled()` and six isolines from `lines()`, both traced by contourpy's C++
core and handed straight to an
[`ft.canvas.Canvas`](https://flet.dev/docs/controls/canvas/) as `Path` subpaths. Underneath the
picture, two numbers that say whether the picture is right.

What it demonstrates:

- **The map.** The field is four fixed Gaussian bumps on the unit square — a peak, a pit, a ridge
  and a notch — built in code from sixteen literal numbers, so there is no asset, no file read and
  no network, and the same input gives the same picture on every device. The levels are fixed at
  −0.6 … 0.8 in steps of 0.2 rather than derived from the data, so changing the grid changes the
  resolution of the answer and nothing else. `filled()` returns each band's outer boundary with
  its holes wound the opposite way, which is what lets one canvas `Path` carrying several subpaths
  cut the holes out under the non-zero fill rule. They are real holes: at 65×65 the seven bands
  come back as twelve enclosed areas, eight of which carry a hole and one of which carries two.
- **A slider over grid resolution, from 33×33 to 129×129.** The stats line reports what came back:
  at 65×65, 7 bands, 21 rings, 2,267 vertices of filled polygon and 949 vertices of isoline; at
  129×129, 4,503 and 1,887. That number is the one that costs you — the whole canvas is 8 shapes
  holding 1,638 path elements at the smallest grid and 6,411 at the largest.
- **All four algorithms, timed side by side and checked against each other.** An
  [`ft.SegmentedButton`](https://flet.dev/docs/controls/segmentedbutton/) chooses which one draws;
  the table under it runs all four every time and prints each one's elapsed milliseconds, its
  default `line_type` and `fill_type`, and how far its isolines differ from `serial`'s. Measured on
  desktop at all seven of the slider's stops, that last column reads `Δlength 0.0e+00` for
  `threaded` every time and `4.4e-16` for `mpl2014` every time; `mpl2005` reads `4.4e-16` at six
  stops and `2.2e-16` at 49×49 — the four agree to double-precision rounding, whichever number
  lands in front of you, while `mpl2005` and `mpl2014` return
  their results in a different format (`SeparateCode` / `OuterCode` against `Separate` /
  `OuterOffset`), which the app converts with `convert_lines` and `convert_filled`. The comparison
  is by **total contour length** rather than vertex against vertex on purpose: a closed ring is
  free to start at a different vertex and does, so an element-wise diff of `mpl2005` against
  `serial` reports differences up to 0.62 in a field one unit across while the curves are in fact
  the same.
- **A contour whose answer is known in advance.** The second field is `z = x² + y²` over
  `[-1.5, 1.5]²`, whose contour at `z = 1` is exactly the unit circle: area π, perimeter 2π. The
  app traces it at the same grid resolution and prints the shoelace area and the summed edge
  length against those two constants, with the relative error. It is always slightly small,
  because the traced polygon is inscribed — −0.30835% at 33×33, −0.07271% at 65×65, −0.01880% at
  129×129 — and the error falls roughly with the square of the grid spacing. That is the panel to
  watch while dragging the slider.

The header prints `contourpy.__version__`, `numpy.__version__`, the platform,
`contourpy.max_threads()` and `contourpy._contourpy.__file__`. `max_threads()` is
`std::thread::hardware_concurrency()` as *this* device answers it, which is a thing only a device
can tell you. The `__file__` is where you see Flet's relocation of the extension out of
site-packages, and is the reason not to locate anything relative to it — it is read with
`getattr(..., "__file__", None)` and prints `no __file__` when absent, because on Android a
relocated extension may have no `__file__` at all and writing it plainly would be an
`AttributeError` in `main`, which is a crash screen rather than a line of text. The whole header
sits in its own `try/except` for the same reason.

The recompute runs in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and ends with
an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach a background thread. Its body is wrapped whole, because `run_thread`
never retrieves the worker's future and discards whatever it raised — with no log, no dialog and
no crash — so an uncaught failure would leave the screen exactly as it was. On desktop one full
recompute — all four algorithms, plus the circle check, plus building every canvas shape — took
between 2.6 and 20 ms across the twenty-eight grid-and-algorithm combinations, most of them under
10. The slider still fires from `on_change_end` rather than `on_change`, which is the habit you
want once the grid is large enough for that to matter.

**Every generator is built inside the worker, and that is not tidiness.** `run_thread` submits to
a shared pool, so two quick taps genuinely overlap — and six Python threads calling `lines()` on
one shared `threaded` generator took the interpreter down on every attempt, once with
`libc++abi: terminating due to uncaught exception of type std::runtime_error: Inconsistent zero
total_point_count for chunk -3` and exit code 134, twice with SIGSEGV. A `serial` generator
survived the same test, but nothing upstream promises it will. Building one costs a fraction of a
trace. See [Threading](../../README.md#threading) for the rest.

The app never uses `chunk_count`, so `threaded` here runs on one thread and matches `serial` — by
design, because chunking cuts rings at the chunk boundaries and this app draws whole rings. That is
the whole trade: measured on desktop over a 2049×2049 grid at nine levels, an unchunked `threaded`
generator reported `thread_count == 1` and took 74.6 ms, against `thread_count == 10` and 19.1 ms
at `chunk_count=4`.

`contourpy` and `numpy` are imported inside a `try/except` so a run without them says which one is
missing instead of dying at import, and `requires-python` is `>=3.11` rather than the `>=3.10`
that `flet create` writes: both pins declare `Requires-Python: >=3.11`, and uv resolves for every
version in the range. `uv lock` on this `pyproject.toml` alone, in an empty directory, resolves 54
packages; with `>=3.10` it fails with *No solution found when resolving dependencies for split
(markers: python_full_version == '3.10.\*')*. It runs on the desktop as well as on a device —
contourpy and numpy both publish desktop wheels for CPython 3.11 through 3.14.

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
