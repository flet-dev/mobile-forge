# pyclipper

[`pyclipper`](https://github.com/fonttools/pyclipper) is a Cython wrapper around Angus
Johnson's Clipper — polygon boolean operations (intersection, union, difference, XOR) and
polygon offsetting (grow a shape outwards, shrink it inwards) on **integer** coordinates. The
wheel's own `Summary` line names what it wraps: *Cython wrapper for the C++ translation of the
Angus Johnson's Clipper library (ver. 6.4.2)*.

On a phone it is the cheapest way to do real polygon algebra. Each wheel is eight entries —
one extension, `pyclipper/__init__.py`, `pyclipper/_version.py` and five `dist-info` files —
with no data file, no `.pyi` stub, and no Python dependency on either platform. The cp314
extension is 321,432 bytes on Android arm64-v8a and 381,984 on iOS device, and the symbols it
leaves undefined are CPython's API, libc/libm and the C++ runtime — there is no `open`, `stat`,
`fopen`, `socket`, `connect` or `getenv` among them on any of the eighteen slices, so it touches
neither the filesystem nor the network. That makes it the right tool for growing a detected text
box before cropping it (`rapidocr` 3.9.2 declares `pyclipper>=1.2.0` for exactly that), merging
overlapping footprints into one outline, computing a hatch or an inset for a CAD/CAM or
3D-printing path, and clipping a route to a boundary.

It is also unfussy about self-intersecting input, with no repair step standing in the way. The
bow-tie `[[0,0],[100,100],[100,0],[0,100]]`, whose signed area is `-0.0` because the two lobes
cancel, clips against a bounding box to the correct two triangles of area 2500.0 each, and
`SimplifyPolygon` on the same ring returns those two triangles directly. What it will not
tolerate is a *float*; see [Things to know](#things-to-know), which is the section to read before
writing any of this.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pyclipper",
]
```

Nothing else to configure. No
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed and no loader shim: the package `__init__` is a real `.py` file and the
extension next to it carries a CPython ABI tag on every slice, which is what Flet's relocation
of native modules requires. There is no data file and no `.pyi` stub for Flet's default
[compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) to remove,
and nothing in the package reads its own source.

The entry belongs in top-level `[project] dependencies` rather than in the `[tool.flet.android]`
/ `[tool.flet.ios]` tables, because `flet build` resolves for the build host first and PyPI has
desktop wheels for every host you would build from: the 1.4.0 release is 36 files — CPython
3.10–3.14 on macOS (`universal2` and `x86_64`), Linux (`manylinux` x86_64 and aarch64) and
Windows (`win32`, `win_amd64`), plus four free-threaded `cp314t` wheels (macOS and Windows only,
no Linux), one PyPy 3.11 `manylinux` wheel and the sdist — all with `requires_dist: None`.

Eighteen mobile wheels, all at the same build number, cover Python 3.12, 3.13 and 3.14 × three
Android ABIs (arm64-v8a, armeabi-v7a, x86_64) and three iOS slices (device, arm64 simulator,
x86_64 simulator). No architecture is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) narrowing
is needed. There is no legacy 32-bit `android_24_x86` slice — unlike
[`shapely`](../shapely), whose index does carry `shapely-2.1.2-1-cp312-cp312-android_24_x86.whl`.

On Android one more wheel arrives with it; see [Android notes](#android-notes).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`boolean-canvas`](examples/boolean-canvas) — the four boolean ops, the float-coordinate trap
  and a mitre offset, each drawn and checked against arithmetic done on paper.

## Threading

**The solve releases the GIL; feeding the polygons in and converting the answer back do not.**
Every mobile slice imports `PyEval_SaveThread` and `PyEval_RestoreThread`, and upstream's
`.pyx` puts `with nogil` on `Pyclipper.GetBounds`, `Execute` and `Execute2`, on
`PyclipperOffset.Execute` and `Execute2`, and on the free functions (`Area`, `Orientation`,
`PointInPolygon`, `Simplify*`, `Clean*`, `Minkowski*`, `Reverse*`) — but **not** on `AddPath` or
`AddPaths` of either class.

That split is visible in measurement. On desktop cp314, a counter thread ran beside repeated
calls and its rate is given as a percentage of an idle window measured immediately before, three
runs each. Controls: `math.factorial(190000)`, which holds the GIL, 2.2 / 2.3 / 2.2%;
`time.sleep(0.5)`, which releases it, 101.8 / 105.5 / 93.3%. Then `Execute` on a disjoint
64,000-vertex pair, so the solution is empty and the conversion back is free: 100.5 / 99.9 /
104.0%. `Execute` returning a 133,628-vertex solution: 36.6 / 63.8 / 63.0%. `AddPath` of a
400,000-vertex path: 21.8 / 29.2 / 25.8%. A one-path `PyclipperOffset.Execute`: 124.8 / 106.1 /
98.2%.

So moving a big clip into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) frees the UI
for less of the wall time than you would expect. On the same machine, two overlapping n-gons,
best of three, as AddPath ms / Execute ms / total ms / output vertices: 1,000 → 0.04 / 0.08 /
0.12 / 896; 10,000 → 0.46 / 0.68 / 1.14 / 6,794; 100,000 → 5.95 / 7.60 / 13.55 / 66,356;
500,000 → 38.71 / 40.73 / 79.44 / 329,790. At half a million vertices `AddPath` alone is 38.71
of the 79.44 ms, and it holds the GIL throughout. Below about 10,000 vertices the whole clip is
around a millisecond and a thread is pure overhead. Cut the vertex count first —
`CleanPolygon` / `SimplifyPolygon`, or decimate — and reach for a thread second.

**Give every thread its own object.** Four 150,000-vertex clips on four threads, each building
its own `Pyclipper`, ran 1.19 / 1.40 / 1.31× faster than the same four in sequence over three
runs, and all twelve results matched the serial ones exactly.

**Sharing one `Pyclipper` across threads segfaults — it is a data race, not just a busy
object.** Nothing in Clipper guards `AddPath`, so one thread adding a path while another solves
is unsynchronised access to the same edge list: six threads × 25 rounds of `AddPath`-then-
`Execute` on one shared object killed the interpreter on **every** run (SIGSEGV, exit 139, 3/3
and 5/5 across two variants), while the identical calls run serially, or with a
`threading.Lock` held across the whole add-and-solve, completed cleanly. A segfault is not a
Python exception and not a Flet crash screen; the app disappears. Threads that only call
`Execute` on an already-populated object hit Clipper's re-entrancy guard instead and raise
rather than corrupt — six threads × 20 `Execute` calls gave 100
`ClipperException: Execution of clipper did not succeed!` out of 120, with 20 correct results
and no wrong ones, identically in four consecutive runs, and six threads × 40 calls each asking
for a *different* clip type gave 237–239 right answers, 0 wrong ones and 1–3 exceptions per run.
That benign half is not something to rely on landing in. Build a fresh `Pyclipper` per call — it
costs nothing next to the clip — or hold a lock around every use of a shared one.

In Flet the exception half is invisible if you let it escape: `page.run_thread` never retrieves
the worker's future, so nothing is logged and nothing crashes — the clip simply does not happen.
Wrap the worker body in `try/except` and render the message, and end it with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads. And note `page.run_thread` submits to a shared pool, so two
quick taps genuinely overlap: that is the situation the segfault above needs.

Nothing in the package starts a thread of its own: `pthread_create` is not among the undefined
symbols of any Android slice.

## Android notes

**One extra wheel arrives: `flet-libcpp-shared`.** The extension is C++, and every Android slice
names `libc++_shared.so` in `DT_NEEDED` — the full list on cp312, cp313 and cp314 alike is
`libm.so`, `libpython3.<minor>.so`, `libc++_shared.so`, `libdl.so`, `libc.so`, with no `SONAME`,
`RPATH` or `RUNPATH`. So the `Requires-Dist: flet-libcpp-shared (>=27.2.12479018)` that every
Android wheel carries is load-bearing rather than defensive, and it is the *only* `Requires-Dist`
line there. Its only payload file is `opt/lib/libc++_shared.so` — 1,292,904 bytes on arm64-v8a,
872,872 on armeabi-v7a, 1,252,080 on x86_64, unchanged between the 27.2.12479018 and
27.3.13750724 releases. Nothing to configure; it resolves on its own.

**Every slice is 16 KB page-aligned**, as Android 15 requires: every `PT_LOAD` segment in all
nine Android extensions reports `p_align 0x4000`.

**The 32-bit ABI is not a 32-bit coordinate space.** The armeabi-v7a extension is a 32-bit ELF
(class 1, `e_machine 0x28`) yet still defines
`_ZN10ClipperLib7Clipper20ProcessIntersectionsEx`, whose trailing `x` is Itanium-ABI
`long long`. Clipper's `use_int32` switch is left commented out upstream, so coordinates are
64-bit signed integers and the ±(2\*\*62 − 1) limit below is identical on every mobile slice.

**The extension filename shape differs by Python version, not by platform.** cp313 and cp314
Android ship the full triplet — `pyclipper/_pyclipper.cpython-314-aarch64-linux-android.so` —
while all three cp312 Android ABIs ship the short forge tag
`pyclipper/_pyclipper.cpython-312.so` (319,576 bytes on arm64-v8a, still 16 KB aligned, still
exporting `PyInit__pyclipper`). Both are ABI-tagged, which is all the relocation needs, so
neither shape asks anything of you.

**The Android `METADATA` loses upstream's long description.** It is 1,801 bytes — headers plus
the appended `Requires-Dist` line — against 8,577 bytes on iOS, which still carries upstream's
full README. So `importlib.metadata.metadata("pyclipper")["Description"]` differs by platform.
Nothing in pyclipper reads it; code of yours might.

## iOS notes

**Nothing extra to install.** The iOS wheels carry no `Requires-Dist` line at all, because C++
comes from the OS: `otool -L` on each of the nine iOS slices lists only its own install name,
`@rpath/Python.framework/Python`, `/usr/lib/libc++.1.dylib` and `/usr/lib/libSystem.B.dylib`.

**No `MH_BUNDLE` problem here.** All nine are already `MH_DYLIB` (`otool -hv` →
`filetype DYLIB`), so the conversion some CMake-built extensions need does not arise. Nor is
there an interdependent-dylib problem: there is exactly one extension per wheel and it depends
on no sibling.

**The binary is bigger on iOS and the installed footprint is smaller.** The cp314 extension is
381,984 bytes on device against 321,432 on Android arm64-v8a — but Android then adds
`libc++_shared.so` on top, which is
1,292,904 bytes on that ABI. Unpacked, one cp314 wheel is 393,123 bytes on iOS device against
325,805 on Android arm64-v8a.

**The arm64 simulator slice disagrees with its own wheel tag about the deployment target.**
`LC_BUILD_VERSION` reports `minos 13.0` on the device slice and on the x86_64 simulator slice
but `minos 14.0` on the arm64 simulator slice, at all three Python versions, though every wheel
is tagged `ios_13_0`. Simulator-only, so no consumer impact has been observed, but it is a real
disagreement.

## Things to know

- **Coordinates are integers, and a float is silently truncated toward zero — no exception, no
  warning, a wrong polygon.** There is no rounding step anywhere: `_to_clipper_point` in
  upstream's `.pyx` is one line, `return IntPoint(py_point[0], py_point[1])`, and Cython converts
  each coordinate to Clipper's 64-bit `cInt` the way `int()` does — toward zero. Measured on
  desktop: the unit square (0,0)–(1,1) intersected with the square (0.5,0.25)–(1.5,1.25), true
  area 0.375, came back as `[[[1,1],[0,1],[0,0],[1,0]]]` — area 1.0, 2.67× too large, with
  nothing said. Probing `AddPath` directly with a 10-wide square whose corner is the value and
  reading `GetBounds` back: 0.4→0, 0.5→0, 0.6→0, 1.5→1, 2.5→2, −0.9→0, −1.5→−1. Fix it with
  `pyclipper.scale_to_clipper(path)` before `AddPath` and `pyclipper.scale_from_clipper(...)`
  after `Execute`: the same test through the helpers returns
  `[[[1.0,1.0],[0.5,1.0],[0.5,0.25],[1.0,0.25]]]`, area exactly 0.375. If you scale yourself,
  `round()` rather than truncate, and treat any float reaching `AddPath` as a bug —
  `assert all(isinstance(v, int) for pt in path for v in pt)` costs nothing next to a clip. NaN
  and infinity are the well-behaved cases: they raise `ValueError: cannot convert float NaN to
  integer` and `OverflowError: cannot convert float infinity to integer`.
- **A coordinate beyond ±(2\*\*62 − 1) aborts the process, and `try/except` cannot catch it.**
  The limit is Clipper's `hiRange`, 4,611,686,018,427,387,903. `x = 0x3FFFFFFFFFFFFFFF` is
  accepted and echoed straight back by `GetBounds`, while `0x4000000000000000` and its negative
  both end the interpreter with `libc++abi: terminating due to uncaught exception of type
  ClipperLib::clipperException: Coordinate outside allowed range` and exit code 134 — SIGABRT,
  not a Python exception and not a Flet crash screen. Upstream declares `except +` on no C++
  method, which is why the throw reaches `std::terminate`, and that exact message string is
  present in all eighteen shipped mobile binaries. `PyclipperOffset.Execute(1e19)` on a 100×100 square
  aborts identically. Range-check in Python, where an `if` is catchable, before the first
  `AddPath`.
- **`scale_to_clipper` can hand you a fatal value without complaining.** It raises only when the
  product exceeds 2\*\*63 — `scale_to_clipper([(1e10, 0)])` at the default scale gives
  `OverflowError: Python int too large to convert to C long` — so the band between 2\*\*62 and
  2\*\*63 is produced silently and aborts one call later: `scale_to_clipper([(5e18, 0)], 1)`
  returns 5,000,000,000,000,000,000, larger than `hiRange`, with no error. Assert
  `max(abs(v) for path in scaled for v in path) <= 2**62 - 1` before the first `AddPath`.
- **The default scale factor of 2\*\*31 is the right starting point, and it costs nothing in
  speed.** It leaves a usable coordinate magnitude of 2\*\*31 = 2,147,483,648 with a precision of
  2\*\*−31 ≈ 4.66e−10, and the truncation is exact for dyadic values — `(0.5, 0.25)` and
  `(1.5, 2.75)` round-trip unchanged, while `0.1 × 2**31 = 214748364.8` becomes `214748364`.
  Clipper switches to 128-bit arithmetic above `loRange` (0x3FFFFFFF = 1,073,741,823), and that
  is not a cliff: a 20,000-vertex pair swept from radius 1e9 to 1e18, `Execute` best of five, ran
  1.79, 1.81 (`loRange` exactly), 1.70, 1.69 (2\*\*31), 1.88 and 1.98 ms while returning the same
  17,868 output vertices throughout. If your data needs a different factor, derive it from the
  real extent (2\*\*62 ÷ your largest absolute coordinate, then back off an order of magnitude
  for offsetting headroom) rather than guessing.
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
  offset with `JT_ROUND` at the default `ArcTolerance` of 0.25, best of five: side 100, delta 10
  → 16 output vertices, 0.002 ms; side 1e8, delta 1e7 → 13,996 vertices, 1.53 ms; side 2\*\*31,
  delta 2\*\*28 → 72,568 vertices, 8.19 ms. Multiplying `ArcTolerance` by the same factor the
  coordinates grew by — 0.25 × 2\*\*31/100 — brings the last case back to 20 vertices and
  0.003 ms. `JT_MITER` is unaffected — 4
  output vertices and 0.001 ms at every size. A round-joined offset that returns tens of
  thousands of vertices is this, not your geometry.
- **Cost tracks intersections, not vertices, so self-intersecting input blows up
  superlinearly.** A convex ring clipped against a box went 0.1 → 0.3 → 0.9 ms from 1,000 to
  4,000 to 12,000 vertices; random star-shaped self-intersecting rings at the same counts went
  4.4 ms (122 paths, 24,486 output vertices) → 105.6 ms (501 paths, 361,703) → 3,201.8 ms (1,465
  paths, 3,275,825). A 12× increase in input cost 728× the time. `SimplifyPolygon` /
  `CleanPolygon` first if your input might look like that.
- **A `Pyclipper` keeps its paths after `Execute`,** so one object can answer more than one
  question: after adding two overlapping squares, `Execute(CT_INTERSECTION)` returned the same
  result twice and a third call with `CT_UNION` returned the correct 8-vertex union. `Clear`
  starts over. (This is about *sequential* reuse — see [Threading](#threading) for why two threads
  cannot share one object.)
- **There is no way to read the Clipper version at runtime.** `pyclipper.__version__` is the
  wrapper's version, and `dir(pyclipper)` — 46 names in total, of which 5 are types, 18 are
  constants, 18 are functions, one is `SILENT` and four are leaked imports — exports no Clipper
  version constant. `strings` finds no `6.4.2` in any of the eighteen mobile binaries: it exists only as
  `METADATA` text and a compile-time `#define`. Quote it from the wheel metadata rather than
  trying to print it. Note also that there is no `SCALING_FACTOR` in this release.
- **`pyclipper.SILENT = False` does not enable the tracing; `pyclipper._pyclipper.SILENT = False`
  does.** `pyclipper/__init__.py` is `from ._pyclipper import *`, so assigning to the re-exported
  copy changes nothing the extension reads. Setting the real one makes `log_action` print
  `Creating a Clipper instance` / `Deleting the Clipper instance`, and
  `Creating an ClipperOffset instance` / `Deleting the ClipperOffset instance` for the offsetter,
  to stdout — on device, the app's console log. Construction and destruction is the whole trace;
  `AddPath` and `Execute` say nothing, so it is rarely worth it.
- **Do not locate anything relative to `pyclipper._pyclipper.__file__`, and do not assume the
  attribute exists.** Flet moves ABI-tagged extensions out of site-packages on both platforms, so
  that value is not a path you can open — and on Android it may be missing outright rather than
  merely wrong. Measured under the same Flet version on other recipes' extensions:
  [`pydantic-core`](../pydantic-core)'s `_pydantic_core` reports no `__file__` at all on Android
  while [`pyyaml`](../pyyaml)'s `_yaml` reports the bare `jniLibs` filename `libyaml-_yaml.so`,
  and both report a `.fwork` path on iOS. So read it as `getattr(module, "__file__", None)`; written plainly it is
  an `AttributeError`, and an `AttributeError` raised while building your page is a Flet crash
  screen rather than a message. Nothing in pyclipper reads it, so this only bites code of yours;
  the [`boolean-canvas`](examples/boolean-canvas) example prints it in its header line so you can
  read the real shape off a device.

## Build notes (maintainers)

`meta.yaml` is seventeen lines, and the one thing in it that needs justifying — the Android-only
`flet-libcpp-shared` host requirement — carries its own comment. There is no `patches/` directory
and no `source:` key, so forge builds the PyPI sdist unmodified. What is left for here is why
that is the whole recipe, and the bump checklist.

**The recipe is minimal because the sdist is self-contained.** Clipper is two vendored files in
pyclipper's own sdist (`src/clipper.cpp`, `src/clipper.hpp`) compiled into the extension: every
Android slice defines 194 `ClipperLib` symbols out of 197 defined dynamic symbols and leaves no
`ClipperLib` symbol undefined, and 168 of the 170 symbols the iOS device slice exports are
`ClipperLib::*` (the other two being `PyInit__pyclipper` and Cython's
`__pyx_module_is_main_pyclipper___pyclipper`). So there is no `flet-lib*` recipe to build,
nothing to pin, and no `requirements.host` beyond the C++ runtime. Options that were therefore
not needed and should not be added on a bump without a reason: `extract_packages` (the extension
is ABI-tagged and sits beside a real `__init__.py`), `excluded_arches` (all three Android ABIs and
all three iOS slices build), a PEP 517 shim, and any `source.url` override.

What to re-verify on a bump — a green build establishes almost none of what the sections above
claim, and none of it is asserted by `tests/`:

- **The Clipper version.** Read it off the built wheel's `METADATA` `Summary` line and off
  `CLIPPER_VERSION` in the unpacked sdist's `src/clipper.hpp`. Today both say 6.4.2 while the
  `.pyx` module docstring still says 6.2.1, so the docstring is not a source. There is no runtime
  way to check it, so a Clipper bump inside a pyclipper release would otherwise go unnoticed.
- **`hiRange`, `use_int32` and `use_lines`.** `grep -n 'hiRange\|use_int32\|use_lines'
  src/clipper.hpp`. Today `hiRange` is `0x3FFFFFFFFFFFFFFFLL`, `use_int32` is commented out and
  `use_lines` is defined — the first two set the ±(2\*\*62 − 1) limit that
  [Things to know](#things-to-know) states as a number, and the third is why open-path clipping
  works and its "disabled" message is absent from the binaries.
- **`except +`.** `grep -c 'except +' src/pyclipper/_pyclipper.pyx` is 0 today, which is the whole
  reason an out-of-range coordinate is a process abort rather than a Python exception. If upstream
  ever adds it, the two abort bullets become wrong in the reader's favour and should be rewritten,
  not deleted.
- **The `nogil` set.** `grep -n 'with nogil' src/pyclipper/_pyclipper.pyx` — 17 blocks today,
  covering both `Execute`s, both `Execute2`s and `GetBounds` but neither `AddPath` nor `AddPaths`.
  The whole of [Threading](#threading) rests on that split; a release that decorated `AddPath`
  would change the advice rather than just the numbers.
- **The Android linkage.** `DT_NEEDED` must still name `libc++_shared.so` on all three ABIs, or
  the `flet-libcpp-shared` requirement is dead weight and [Android notes](#android-notes) is
  wrong. Re-check 16 KB `PT_LOAD` alignment at the same time, and that iOS is still `MH_DYLIB`
  with no `Requires-Dist`.
- **The wheel shape.** Still eight entries with no data file and no `.pyi` stub, and the extension
  still ABI-tagged next to a real `__init__.py`. A new data file or a stub would put the
  no-`extract_packages` claim back in question — a `.pyi` in particular is deleted by
  serious_python's junk-file globs.
- **The measurements.** Every timing, percentage and byte count above is measured, most on desktop
  cp314. Re-measure rather than scaling: the ratios transfer, the absolute times do not. The
  `libc++_shared.so` payload sizes move with the `flet-libcpp-shared` recipe rather than this one.
- **The behavioural gotchas.** Float truncation, the overlapping constant families, the
  `PFT_NONZERO` hole fill, the open-path aborts, the empty-list erosion and the `ArcTolerance`
  blowup all live in upstream's Python and Cython layers, so a pyclipper bump can move any of them
  without the build noticing.

`tests/test_pyclipper.py` covers intersection, offset and the scale round trip — presence,
essentially. Worth adding, in rough order of value: a float path fed straight into `AddPath` and
asserted to give the *wrong* area, since that is the claim an app author is most likely to hit and
it would turn red the day upstream starts rounding or raising; an `Execute` over a shape with a
hole asserting that the flat solution's signed areas sum correctly, which pins the `PFT_EVENODD`
default; and an open path through `Execute2` + `OpenPathsFromPolyTree`, which would catch a build
that lost `use_lines`. Per the repo's test convention, assert relationships rather than version
numbers — and do not try to test the out-of-range abort, since it takes the test process down with
it.
