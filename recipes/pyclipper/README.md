# pyclipper

[`pyclipper`](https://github.com/fonttools/pyclipper) is a Cython wrapper around Angus Johnson's
[Clipper](https://sourceforge.net/projects/polyclipping/) — polygon boolean operations
(intersection, union, difference, XOR) and polygon offsetting, growing a shape outwards or
shrinking it inwards, on **integer** coordinates. The wheel's `Summary` line names the version it
wraps; today that is Clipper 6.4.2.

On a phone it is the cheapest way to do real polygon algebra. The wheel is one compiled extension
beside a two-file Python package, and it opens no file, reads no environment variable and reaches
no network — so there is no permission to request, no data file to bundle and no first-run
download. That makes it the tool for growing a detected text box before cropping it, merging
overlapping footprints into one outline, computing a hatch or an inset for a CAD/CAM or
3D-printing path, and clipping a route to a boundary. It also takes self-intersecting input
straight, with no repair step, so there is no second geometry library to ship for one. What it
will not tolerate is a *float*: read [Coordinates and precision](#coordinates-and-precision)
before writing any of this.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pyclipper",
]
```

Keep the entry in top-level `[project] dependencies` rather than in the `[tool.flet.android]` or
`[tool.flet.ios]` tables. `flet build` resolves for the build host first, and PyPI publishes
desktop wheels for every host you would build from, so the top-level entry is the one that gets
you a working `flet run` and the mobile wheels from the same line.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`boolean-canvas`](examples/boolean-canvas) — the four boolean ops, the float-coordinate trap
  and a mitre offset, each drawn and checked against arithmetic done on paper.

## Usage in a Flet app

```python
import flet as ft
import pyclipper
from flet import canvas

# scale_to_clipper is what stops AddPath truncating these floats to whole units
engine = pyclipper.Pyclipper()
engine.AddPath(pyclipper.scale_to_clipper(outline), pyclipper.PT_SUBJECT, True)
engine.AddPath(pyclipper.scale_to_clipper(window), pyclipper.PT_CLIP, True)
rings = pyclipper.scale_from_clipper(engine.Execute(pyclipper.CT_INTERSECTION))

shapes = []
for ring in rings:
    elements = [canvas.Path.MoveTo(*ring[0])]
    elements += [canvas.Path.LineTo(x, y) for x, y in ring[1:]]
    elements.append(canvas.Path.Close())
    shapes.append(canvas.Path(elements, ft.Paint(style=ft.PaintingStyle.STROKE)))

view = canvas.Canvas(shapes=shapes, width=280, height=180)
```

[`Execute`](https://github.com/fonttools/pyclipper#how-to-use) returns a flat list of rings, so
one [`canvas.Path`](https://flet.dev/docs/controls/canvas/) per ring is the whole conversion into
a Flet control. A hole comes back as another ring in that same flat list, wound the other way,
not as a child of anything — which is what makes summing areas a trap, and one of the several
[Things to know](#things-to-know) worth reading before you rely on a result.

Build a fresh `Pyclipper` for every call. It costs nothing next to the clip itself, and it is
what keeps two overlapping taps from sharing one object. `PyclipperOffset` has the same shape:
`AddPath(path, pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)`, then `Execute(delta)`.

### Coordinates and precision

**Clipper works in 64-bit integers, and pyclipper does not round for you.** A float reaching
`AddPath` is truncated toward zero (`-1.5` becomes `-1`, not `-2`), silently, and you get a wrong polygon rather than an
exception. Go through the helpers in both directions:

```python
scaled = pyclipper.scale_to_clipper(path)      # float path -> integer path
result = pyclipper.scale_from_clipper(rings)   # and back again
```

The default scale factor is 2\*\*31. That leaves a usable coordinate magnitude of about 2.1e9 at a
precision of 2\*\*−31 ≈ 4.66e−10, and it is exact for dyadic values, so a coordinate like `0.25`
survives the round trip unchanged. It is the right starting point; derive a different factor from
your real extent (2\*\*62 ÷ your largest absolute coordinate, backed off an order of magnitude for
offsetting headroom) rather than guessing at one.

**The ceiling is ±(2\*\*62 − 1) — 4,611,686,018,427,387,903 — and crossing it kills the process,
not the call.** It is Clipper's `hiRange`, it is enforced in C++ with no Python exception in
front of it, and `scale_to_clipper` will hand you a value past it without complaining. Two
assertions before the first `AddPath` cost nothing next to a clip and turn both failures into
something you can catch:

```python
assert all(isinstance(v, int) for point in path for v in point)
assert max(abs(v) for path in scaled for v in path) <= 2**62 - 1
```

That ceiling is the same on every mobile slice. `armeabi-v7a` is a 32-bit ABI, but Clipper's
`use_int32` switch is left off, so coordinates are 64-bit signed integers there too — a 32-bit
Android device does not get a smaller coordinate space, and does not need a different factor.

### Threading

**The solve releases the GIL; feeding the polygons in and converting the answer back do not.**
Upstream puts `with nogil` on `Pyclipper.GetBounds`, `Execute` and `Execute2`, on
`PyclipperOffset.Execute` and `Execute2`, and on the free functions (`Area`, `Orientation`,
`PointInPolygon`, `Simplify*`, `Clean*`, `Minkowski*`, `Reverse*`) — but **not** on `AddPath` or
`AddPaths` of either class.

That split is visible in measurement. On desktop cp314 a counter thread ran beside repeated
calls, its rate reported as a percentage of an idle window measured immediately before. Against
controls of about 2% (`math.factorial`, which holds the GIL) and about 100% (`time.sleep`, which
releases it), `Execute` on a disjoint pair — empty solution, so the conversion back is free —
scored around 100%, and so did a one-path `PyclipperOffset.Execute`. But `Execute` returning a
133,628-vertex solution scored 37–64%, and `AddPath` of a 400,000-vertex path scored 22–29%. The
conversion at each end is where the GIL goes.

So moving a big clip into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) frees the UI
for less of the wall time than you would expect. On the same machine, two overlapping n-gons ran
end to end in roughly 0.1 ms at 1,000 vertices, 1 ms at 10,000, 14 ms at 100,000 and 79 ms at
500,000 — and in that last case `AddPath` alone was 39 of the 79 ms, holding the GIL throughout.
Below about 10,000 vertices the whole clip is around a millisecond and a thread is pure
overhead. Cut the vertex count first — `CleanPolygon` / `SimplifyPolygon`, or decimate — and
reach for a thread second.

**Give every thread its own object.** Four 150,000-vertex clips on four threads, each building
its own `Pyclipper`, ran 1.2–1.4× faster than the same four in sequence, and every result
matched the serial one exactly.

**Sharing one `Pyclipper` across threads segfaults — it is a data race, not just a busy
object.** Nothing in Clipper guards `AddPath`, so one thread adding a path while another solves
is unsynchronised access to the same edge list: six threads × 25 rounds of `AddPath`-then-
`Execute` on one shared object killed the interpreter on **every** run (SIGSEGV, exit 139, 8
runs across two variants), while the identical calls run serially, or with a `threading.Lock`
held across the whole add-and-solve, completed cleanly. A segfault is not a Python exception and
not a Flet crash screen; the app disappears.

Threads that only call `Execute` on an already-populated object hit Clipper's re-entrancy guard
instead and raise rather than corrupt: six threads calling `Execute` in a loop produced mostly
`ClipperException: Execution of clipper did not succeed!` with the remainder correct and none
wrong, repeatably. That benign half is not something to rely on landing in. Build a fresh
`Pyclipper` per call — it costs nothing next to the clip — or hold a lock around every use of a
shared one.

In Flet the exception half is invisible if you let it escape: `page.run_thread` never retrieves
the worker's future, so nothing is logged and nothing crashes — the clip simply does not happen.
Wrap the worker body in `try/except` and render the message, and end it with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads. And note `page.run_thread` submits to a shared pool, so two
quick taps genuinely overlap: that is the situation the segfault above needs. Nothing in the
package starts a thread of its own, so every thread involved is one you made.

### App size

Expect approximately 0.33 MB unpacked per Android ABI and 0.39 MB per iOS slice — one extension
and two small Python files, with no test suite or data directory worth naming in
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup).

Android carries one thing on top: the C++ runtime, `libc++_shared.so`, approximately 0.87 MB on
`armeabi-v7a` and 1.25–1.3 MB on the 64-bit ABIs. It arrives once per ABI and is shared with
every other C++ package in the app, so it is not pyclipper's cost twice over.

At this size, narrowing
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) or using
an app bundle or split APKs is a decision to make for the application as a whole — dropping an
ABI saves the C++ runtime, not the wheel. These figures describe the package payload, not the
amount added to the final APK or IPA; packaging and compression determine that.

### Other considerations

A desktop `flet run` installs PyPI's own wheel. It is built from the same sdist, with the same
vendored Clipper sources and the same Python layer, so upstream's documentation applies without
translation and anything you prototype on your laptop transfers.

What does not transfer is the metadata. The Android wheel's `METADATA` drops upstream's long
description while the iOS wheel's keeps it, so
`importlib.metadata.metadata("pyclipper")["Description"]` answers differently by platform.
Nothing in pyclipper reads it; code of yours might.

Leave Flet's [package compilation](https://flet.dev/docs/publish/#compilation-and-cleanup)
enabled. Nothing in pyclipper reads its own source, so compiling to `.pyc` is safe here.

## Things to know

- **Coordinates are integers, and a float is silently truncated toward zero — no exception, no
  warning, a wrong polygon.** There is no rounding step anywhere; Cython converts each
  coordinate to Clipper's 64-bit `cInt` the way `int()` does. Measured on desktop: the unit
  square (0,0)–(1,1) intersected with the square (0.5,0.25)–(1.5,1.25), true area 0.375, came
  back as `[[[1,1],[0,1],[0,0],[1,0]]]` — area 1.0, 2.67× too large, with nothing said. The same
  test through `scale_to_clipper` / `scale_from_clipper` returns area exactly 0.375. If you scale
  yourself, `round()` rather than truncate. NaN and infinity are the well-behaved cases: they
  raise `ValueError: cannot convert float NaN to integer` and
  `OverflowError: cannot convert float infinity to integer`.
- **A coordinate beyond ±(2\*\*62 − 1) aborts the process, and `try/except` cannot catch it.**
  The limit is Clipper's `hiRange`, 4,611,686,018,427,387,903. `x = 0x3FFFFFFFFFFFFFFF` is
  accepted and echoed straight back by `GetBounds`, while `0x4000000000000000` and its negative
  both end the interpreter with `libc++abi: terminating due to uncaught exception of type
  ClipperLib::clipperException: Coordinate outside allowed range` and exit code 134 — SIGABRT,
  not a Python exception and not a Flet crash screen. Upstream declares `except +` on no C++
  method, which is why the throw reaches `std::terminate`, and that exact message string is
  present in every shipped mobile binary. `PyclipperOffset.Execute(1e19)` on a 100×100 square
  aborts identically. Range-check in Python, where an `if` is catchable, before the first
  `AddPath`.
- **`scale_to_clipper` can hand you a fatal value without complaining.** It raises only when the
  product exceeds 2\*\*63 — `scale_to_clipper([(1e10, 0)])` at the default scale gives
  `OverflowError: Python int too large to convert to C long` — so the band between 2\*\*62 and
  2\*\*63 is produced silently and aborts one call later: `scale_to_clipper([(5e18, 0)], 1)`
  returns 5,000,000,000,000,000,000, larger than `hiRange`, with no error.
- **The default scale factor costs nothing in speed.** Clipper switches to 128-bit arithmetic
  above `loRange` (0x3FFFFFFF = 1,073,741,823), and that is not a cliff: a 20,000-vertex pair
  swept from radius 1e9 to 1e18 stayed between 1.7 and 2.0 ms and returned the same 17,868
  output vertices throughout. Truncation at that factor is exact for dyadic values — `(0.5,
  0.25)` and `(1.5, 2.75)` round-trip unchanged, while `0.1 × 2**31 = 214748364.8` becomes
  `214748364`.
- **`Execute` returns a flat list of rings with no hole information.** A 100×100 square with a
  50×50 hole, clipped against a bounding box, comes back as two paths whose `pyclipper.Area`
  values are `[10000.0, -2500.0]`: the negative one is the hole, and the signed sum, 7500.0, is
  the true area. Sum the *signed* areas, never the absolute ones. `Execute2` returns the same
  result as a `PyPolyNode` tree instead, whose root child has `IsHole=False` (area 10000.0) with
  one child `IsHole=True` (area −2500.0); `PolyTreeToPaths`, `ClosedPathsFromPolyTree` and
  `OpenPathsFromPolyTree` unpack it.
- **The four constant families all start at 0 and overlap numerically**, so a constant from the
  wrong family gives a plausible wrong answer rather than an error:
  `CT_INTERSECTION == PT_SUBJECT == PFT_EVENODD == JT_SQUARE == ET_CLOSEDPOLYGON == 0` and
  `CT_UNION == PT_CLIP == PFT_NONZERO == JT_ROUND == ET_CLOSEDLINE == 1`. Measured on a
  subject/clip pair, `Execute(pyclipper.PT_SUBJECT)` returned the intersection and
  `Execute(pyclipper.PT_CLIP)` returned the union (area 17,500.0), neither with a complaint. Note
  too that `if poly_type:` is `False` for `PT_SUBJECT`. When you get a union where you asked for
  an intersection, look at the constant you passed before you look at the geometry.
- **`PFT_NONZERO` fills a hole whose ring winds the same way as its outer boundary.** A 100×100
  counter-clockwise square with a 50×50 counter-clockwise hole, both added as `PT_SUBJECT` and
  unioned: with `PFT_EVENODD` — pyclipper's default, and what `Execute` uses when you pass only a
  clip type — 2 paths, signed areas `[10000.0, -2500.0]`, net 7500.0; with `PFT_NONZERO`, 1 path
  of area 10000.0, hole gone. Wind the hole the other way and both rules agree at 7500.0.
  `Orientation(path)` tells you which way a ring goes and `ReversePath` turns it around.
- **Open paths need `Execute2`, and only as the subject.** `AddPath(line, PT_CLIP, False)` aborts
  the process with `AddPath: Open paths must be subject.`, and adding an open subject and then
  calling `Execute` aborts with `Error: PolyTree struct is needed for open path clipping.` — both
  exit code 134, both message strings present in every shipped mobile binary. The same
  input through `Execute2` works: a horizontal line clipped by a 100×100 square gives
  `OpenPathsFromPolyTree(tree) == [[[100,50],[0,50]]]`. Line clipping *is* compiled in, which is
  why the one Clipper throw message that appears in none of them is "Open paths have been
  disabled."
- **A degenerate ring raises — and truncation is a common way to make one.** `AddPath([])` and
  `AddPath([[0,0],[10,10]])` both raise `ClipperException: The path is invalid for clipping`, and
  so does a float square spanning x = −0.5…0.5, because truncation collapses both x values to 0.
  This one *is* a Python exception, so catch it and render the message. Prefer `AddPath` in a loop
  over `AddPaths` when you need to know which ring was dropped: `AddPaths` raises only when
  *every* path is invalid (`All paths are invalid for clipping`), and a partly bad batch is
  accepted quietly — a two-path batch with one empty path returned `True` and reported the good
  path's bounds.
- **An offset that erodes a shape out of existence returns an empty list, not an error.** A
  100×100 square offset by −50 and by −60 both returned 0 paths; −10 returned one path spanning
  x 10…90, area 6400.0. Check `if not solution:` after every negative delta and give it a UI
  state. `PyclipperOffset` fixes input orientation itself, so there is no winding trap on this
  side: the same square given clockwise and counter-clockwise, offset by +10 with `JT_MITER`,
  both returned x-range (−10, 110) and area 14400.0.
- **`ArcTolerance` is in your coordinate units, so `JT_ROUND` after scaling explodes.** A square
  offset with `JT_ROUND` at the default `ArcTolerance` of 0.25 returns 16 output vertices at side
  100, about 14,000 at side 1e8, and about 73,000 at side 2\*\*31 — 8 ms for one offset of one
  rectangle. Multiplying `ArcTolerance` by the same factor the coordinates grew by brings that
  last case back to 20 vertices and microseconds. `JT_MITER` is unaffected — 4 output vertices at
  every size. A round-joined offset that returns tens of thousands of vertices is this, not your
  geometry.
- **Cost tracks intersections, not vertices, so self-intersecting input blows up
  superlinearly.** A convex ring clipped against a box went from 0.1 to 0.9 ms as it grew from
  1,000 to 12,000 vertices. Random star-shaped self-intersecting rings over the same range went
  from 4 ms to 3.2 *seconds*, the output growing from 24,000 vertices to 3.3 million: a 12×
  increase in input cost more than 700× the time. `SimplifyPolygon` / `CleanPolygon` first if
  your input might look like that.
- **A `Pyclipper` keeps its paths after `Execute`,** so one object can answer more than one
  question: after adding two overlapping squares, `Execute(CT_INTERSECTION)` returned the same
  result twice and a third call with `CT_UNION` returned the correct 8-vertex union. `Clear`
  starts over. (This is about *sequential* reuse — see [Threading](#threading) for why two threads
  cannot share one object.)
- **There is no way to read the Clipper version at runtime.** `pyclipper.__version__` is the
  wrapper's version, and nothing the package exports names a Clipper version. `strings` finds no
  `6.4.2` in any mobile binary: it exists only as `METADATA` text and a compile-time `#define`.
  Quote it from the wheel metadata rather than trying to print it. Note also that there is no
  `SCALING_FACTOR` in this release.
- **`pyclipper.SILENT = False` does not enable the tracing; `pyclipper._pyclipper.SILENT = False`
  does.** `pyclipper/__init__.py` is `from ._pyclipper import *`, so assigning to the re-exported
  copy changes nothing the extension reads. Setting the real one prints a line to stdout — on
  device, the app's console log — each time a `Clipper` or `ClipperOffset` instance is created or
  deleted. That is the whole trace; `AddPath` and `Execute` say nothing, so it is rarely worth it.
- **Do not locate anything relative to `pyclipper._pyclipper.__file__`, and do not assume the
  attribute exists.** Flet moves ABI-tagged extensions out of site-packages on both platforms, so
  that value is not a path you can open — and on Android it may be missing outright rather than
  merely wrong. Measured under the same Flet version on other recipes' extensions:
  [`pydantic-core`](../pydantic-core)'s `_pydantic_core` reports no `__file__` at all on Android
  while [`pyyaml`](../pyyaml)'s `_yaml` reports the bare `jniLibs` filename `libyaml-_yaml.so`,
  and both report a `.fwork` path on iOS. So read it as `getattr(module, "__file__", None)`;
  written plainly it is an `AttributeError`, and an `AttributeError` raised while building your
  page is a Flet crash screen rather than a message. This only bites code of yours;
  the [`boolean-canvas`](examples/boolean-canvas) example prints it in its header line so you can
  read the real shape off a device.

## Build notes (maintainers)

### Recipe shape

**The recipe is minimal because the sdist is self-contained.** Clipper is two vendored files in
pyclipper's own sdist (`src/clipper.cpp`, `src/clipper.hpp`) compiled straight into the
extension — nearly every dynamic symbol a built slice defines is `ClipperLib::*`, and no
`ClipperLib` symbol is left undefined on any of them. So there is no `flet-lib*` recipe to build,
nothing to pin, and no `requirements.host` beyond the C++ runtime. There is no `patches/`
directory and no `source:` key either: forge builds the PyPI sdist unmodified.

The one thing in `meta.yaml` that needs justifying, the Android-only `flet-libcpp-shared` host
requirement, carries its own comment there. It is load-bearing rather than defensive: the
extension is C++, every Android slice names `libc++_shared.so` in `DT_NEEDED`, and that is the
only `Requires-Dist` line the Android wheels carry. iOS gets C++ from the OS
(`/usr/lib/libc++.1.dylib`), so the iOS wheels carry no `Requires-Dist` at all.

Options that were therefore not needed, and should not be added on a bump without a reason:
`extract_packages` (the extension is ABI-tagged and sits beside a real `__init__.py`; note the
filename shape differs by Python version, full triplet on cp313/cp314 and the short forge tag on
cp312, and both are ABI-tagged, which is all the relocation needs), `excluded_arches` (every
Android ABI and every iOS slice builds), a PEP 517 shim, and any `source.url` override. There is
no `MH_BUNDLE` conversion to do either: the iOS extensions are already `MH_DYLIB`, and with one
extension per wheel there is no interdependent-dylib problem.

### Upgrade hazards

A green build establishes almost none of what the consumer sections claim, and none of it is
asserted by `tests/`.

- **The Clipper version.** Read it off the built wheel's `METADATA` `Summary` line and off
  `CLIPPER_VERSION` in the unpacked sdist's `src/clipper.hpp`. Today both say 6.4.2 while the
  `.pyx` module docstring still says 6.2.1, so the docstring is not a source. There is no runtime
  way to check it, so a Clipper bump inside a pyclipper release would otherwise go unnoticed.
- **`hiRange`, `use_int32` and `use_lines`.** `grep -n 'hiRange\|use_int32\|use_lines'
  src/clipper.hpp`. Today `hiRange` is `0x3FFFFFFFFFFFFFFFLL`, `use_int32` is commented out and
  `use_lines` is defined — the first two set the ±(2\*\*62 − 1) limit that
  [Coordinates and precision](#coordinates-and-precision) states as a number and as an assertion,
  and the third is why open-path clipping works.
- **`except +`.** `grep -c 'except +' src/pyclipper/_pyclipper.pyx` is 0 today, which is the whole
  reason an out-of-range coordinate is a process abort rather than a Python exception. If upstream
  ever adds it, the two abort bullets become wrong in the reader's favour and should be rewritten,
  not deleted.
- **The `nogil` set.** `grep -n 'with nogil' src/pyclipper/_pyclipper.pyx` — 17 blocks today,
  covering both `Execute`s, both `Execute2`s and `GetBounds` but neither `AddPath` nor `AddPaths`.
  The whole of [Threading](#threading) rests on that split; a release that decorated `AddPath`
  would change the advice rather than just the numbers.
- **The behavioural gotchas.** Float truncation, the overlapping constant families, the
  `PFT_NONZERO` hole fill, the open-path aborts, the empty-list erosion and the `ArcTolerance`
  blowup all live in upstream's Python and Cython layers, so a pyclipper bump can move any of them
  without the build noticing.
- **A known, unexplained discrepancy.** `LC_BUILD_VERSION` reports `minos 13.0` on the iOS device
  and x86_64 simulator slices but `minos 14.0` on the arm64 simulator slice, though every wheel is
  tagged `ios_13_0`. Simulator-only so far; if it ever reaches the device slice it stops being
  cosmetic.

### Re-verification checklist

- **The Android linkage.** `DT_NEEDED` must still name `libc++_shared.so` on all three ABIs, or
  the `flet-libcpp-shared` requirement is dead weight. Re-check 16 KB `PT_LOAD` alignment at the
  same time, and that iOS is still `MH_DYLIB` with no `Requires-Dist`.
- **The wheel shape.** Still one extension beside a real `__init__.py`, still ABI-tagged, still no
  data file and no `.pyi` stub. Either of the last two would put the no-`extract_packages`
  decision back in question — a `.pyi` in particular is deleted by serious_python's junk-file
  globs.
- **The measurements.** Every timing, percentage and size figure in the consumer sections is
  measured, most on desktop cp314. Re-measure rather than scaling: the ratios transfer, the
  absolute times do not. The `libc++_shared.so` payload sizes move with the `flet-libcpp-shared`
  recipe rather than this one.

### Coverage gaps

`tests/test_pyclipper.py` covers intersection, offset and the scale round trip — presence,
essentially. It does not exercise hole handling, open paths, float truncation, threading or the
`ArcTolerance` blowup, so treat every one of those as an inspection-backed or example-backed
claim.

Worth adding, in rough order of value: a float path fed straight into `AddPath` and asserted to
give the *wrong* area, since that is the claim an app author is most likely to hit and it would
turn red the day upstream starts rounding or raising; an `Execute` over a shape with a hole
asserting that the flat solution's signed areas sum correctly, which pins the `PFT_EVENODD`
default; and an open path through `Execute2` + `OpenPathsFromPolyTree`, which would catch a build
that lost `use_lines`. Do not try to test the out-of-range abort — it takes the test process down
with it.
