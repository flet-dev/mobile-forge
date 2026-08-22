# contourpy

[`contourpy`](https://contourpy.readthedocs.io) turns a 2-D grid of values into geometry: the
polylines where the field crosses a level
([`lines()`](https://contourpy.readthedocs.io/en/latest/api/contourpy/ContourGenerator.html#contourpy.ContourGenerator.lines))
and the polygons between two levels
([`filled()`](https://contourpy.readthedocs.io/en/latest/api/contourpy/ContourGenerator.html#contourpy.ContourGenerator.filled)).
It is the engine under `matplotlib.contour`, and worth reaching for directly when you want the
*shapes* rather than a picture: an isoline you will draw on an
[`ft.canvas.Canvas`](https://flet.dev/docs/controls/canvas/), a coverage polygon you will
hit-test, a band you will fill in your own colours. What goes in is a numpy array and what comes
out is numpy arrays — it opens no file and reaches no network.

It is also accurate in a way you can check. Contour `z = x² + y²` at `z = 1` and you must get the
unit circle: over `[-1.5, 1.5]²` the traced polygon's shoelace area against π reads −1.141% at a
17×17 grid and −0.0012% at 513×513, quadratic in the grid spacing and always slightly small
because the polygon is inscribed. The [example](examples/contour-map) prints that number live at
whatever grid you choose.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "contourpy",
    "numpy",
]
```

[`numpy`](../numpy) is in the snippet because you type it yourself:
[`contour_generator`](https://contourpy.readthedocs.io/en/latest/api/contourpy/contour_generator.html#contourpy.contour_generator)
takes arrays and every result is arrays.

**Raise `requires-python` to `>=3.11` if you pin either package with `==`.** Both declare
`Requires-Python: >=3.11` on this index, and uv resolves for *every* version your project claims
to support, not just the interpreter in use, so leaving the `>=3.10` that `flet create` writes
fails the build outright with `No solution found when resolving dependencies for split (markers:
python_full_version == '3.10.*')`. Check it the way a consumer meets it — copy the
[example's](examples/contour-map) `pyproject.toml` alone into an empty directory and `uv lock`
there, because a run that reused an existing lock proves nothing.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`contour-map`](examples/contour-map) — filled bands and isolines drawn on a canvas, the four
  algorithms timed against each other, and a contour that must be a circle measured against π.

## Usage in a Flet app

Build a generator over the grid, ask it for a level, and turn each returned ring into a subpath of
an [`ft.canvas.Path`](https://flet.dev/docs/controls/canvas/path):

```python
import contourpy
import flet as ft
import numpy as np
from flet import canvas

SIZE = 300  # canvas pixels

axis = np.linspace(0.0, 1.0, 65)
x, y = np.meshgrid(axis, axis)
z = np.exp(-((x - 0.4) ** 2 + (y - 0.5) ** 2) / 0.05)

gen = contourpy.contour_generator(x=x, y=y, z=z)   # name="serial" by default
rings = gen.lines(0.5)                             # list of (N, 2) float64 arrays

elements = []
for ring in rings:
    points = (ring * SIZE).tolist()   # field units to pixels, and to Python floats
    elements.append(canvas.Path.MoveTo(*points[0]))
    elements.extend(canvas.Path.LineTo(px, py) for px, py in points[1:])

stroke = ft.Paint(color=ft.Colors.ON_SURFACE, style=ft.PaintingStyle.STROKE, stroke_width=1.0)
plot = canvas.Canvas(shapes=[canvas.Path(elements, stroke)], width=SIZE, height=SIZE)
```

`gen.filled(lower, upper)` gives the band between two levels instead, as a `(points, offsets)`
pair in [`FillType`](https://contourpy.readthedocs.io/en/latest/api/contourpy/enums.html#contourpy.FillType)`.OuterOffset`:
each enclosed area's outer boundary followed by its holes, wound the opposite way. Emit every
slice as its own subpath, end each with `canvas.Path.Close()`, and set
`style=ft.PaintingStyle.FILL` — the non-zero fill rule then cuts the holes out for free. The
`.tolist()` is not cosmetic: Flet's msgpack layer will not serialise a numpy scalar narrower than
Python `float`.

### Choosing an algorithm

Four algorithms are compiled into every mobile wheel — `contourpy/__init__.py` imports all four
classes unconditionally, so a missing one would break `import contourpy` outright. They are not
four qualities of result; they are one result with different output formats and feature sets:

| algorithm | default `line_type` | default `fill_type` | `corner_mask` | threads | `quad_as_tri` | `z_interp` |
| --- | --- | --- | --- | --- | --- | --- |
| `serial` | `Separate` | `OuterOffset` | yes | no | yes | yes |
| `threaded` | `Separate` | `OuterOffset` | yes | yes | yes | yes |
| `mpl2014` | `SeparateCode` | `OuterCode` | yes | no | no | no |
| `mpl2005` | `SeparateCode` | `OuterCode` | **no** | no | no | no |

**Pick `serial` unless you have chunked the grid, and then pick `threaded`.** `serial` and
`threaded` accept all five
[`LineType`](https://contourpy.readthedocs.io/en/latest/api/contourpy/enums.html#contourpy.LineType)s
and all six `FillType`s; `mpl2014` and `mpl2005` accept exactly one of each and exist only for
bug-for-bug fidelity with old matplotlib releases. On a 129×129 grid with seven bands plus six line
levels, all four land within about a factor of two of each other: `serial` and an unchunked
`threaded` are indistinguishable, `mpl2005` is a little slower and `mpl2014` is the slowest at
roughly twice `serial`. Those are desktop ratios and the absolute times move with the host, so
time the call on the device if the difference would matter to you.

### Threading

**`name="threaded"` does nothing until you also chunk the grid, and it fails silently.**
[`thread_count`](https://contourpy.readthedocs.io/en/latest/api/contourpy/ContourGenerator.html#contourpy.ContourGenerator.thread_count)
defaults to 0, meaning "use
[`max_threads()`](https://contourpy.readthedocs.io/en/latest/api/contourpy/other.html#contourpy.max_threads)",
but the generator caps it at the number of chunks — and the default is one chunk. Desktop, nine
levels over a 2049×2049 grid, best of three: an unchunked `threaded` generator reports
`thread_count == 1` and takes 74.6 ms against `serial`'s 75.6 ms, while
[`chunk_count=4`](https://contourpy.readthedocs.io/en/latest/user_guide/calculate/chunks.html)
reports 10 threads and 19.1 ms, 4.0× faster. `chunk_count=2` gives 4 threads and 24.7 ms, `=8`
19.3 ms, `=16` 21.5 ms. Chunk at least as many ways as you want threads; past that it stops
paying.

**`max_threads()` is whatever the device reports** — `std::thread::hardware_concurrency()`
straight through, 10 on that desktop, 10 on an iPhone 16 simulator and 4 on an Android 14
emulator. It follows the host's core count, so never hard-code a chunk count tuned on one device;
the [example](examples/contour-map) prints the real one in its header.

**The tracing releases the GIL, but only about half the time.** Measured with a counter thread
running beside the work, its rate as a percentage of an idle window and against controls that
release (`time.sleep`, 94.6%) and hold (`math.factorial`, 4.5%): nine `serial` `lines()` calls
over 2049×2049 scored 46.7%, 48.9% and 47.5% over three runs. Half of that call is C++ tracing
with the GIL dropped and half is building the numpy output arrays with it held; no amount of
threading changes the second half.

**A busy Python thread is much worse for `threaded` than for `serial`.** The C++ workers take the
GIL back to allocate each chunk's output, so a Python thread that never yields starves them. Same
grid and levels, best of three: `serial` 67.1 ms alone, 117.3 ms beside a pure-Python spin loop,
66.3 ms beside a thread that sleeps; `threaded` at `chunk_count=8` **14.0 ms alone, 823.0 ms
beside the spin loop**, 14.6 ms beside the sleeping one. A Flet UI thread is the sleeping kind, so
this is a warning about your *own* background work rather than about Flet — but it is a 59× cliff
and invisible in a single-threaded benchmark.

**Give every worker its own generator. Sharing a `threaded` one kills the process.** Six Python
threads calling `lines()` on one shared `threaded` generator (`chunk_count=4`, 513×513, ten rounds
of nine levels each) took the interpreter down on **every** run: once aborting with `libc++abi:
terminating due to uncaught exception of type std::runtime_error: Inconsistent zero
total_point_count for chunk -3.` and exit code 134, twice with SIGSEGV. That string is present in
every shipped mobile binary, so it is the same code path on device — and an abort is neither a
Python exception nor a Flet crash screen: the app simply disappears. One generator per thread was
correct 540 of 540 comparisons on both runs of it.

**Chunking is not what makes it unsafe.** Four threads with no `chunk_count` at all, ten rounds of
nine levels on 129×129 and 65×65 grids, died on all five runs too — four with SIGSEGV, one with
SIGTRAP, silently and with no message. So the unchunked generator you get by never touching
`chunk_count` is no safer to share than a chunked one. A shared **`serial`** generator survived
the same test, 540 of 540 on 8 of 8 runs, which is evidence and not a guarantee: nothing upstream
documents a generator as thread-safe. Build one per call; it costs a fraction of the trace.

Put anything past a few thousand grid points in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), end the
worker with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
because auto-update does not reach a background thread, and wrap the body in `try/except` because
`run_thread` never retrieves the worker's future and discards whatever it raised — no log, no
dialog, no crash. `run_thread` also submits to a shared pool, so two quick taps genuinely overlap:
that is the situation the abort above needs.

### Grid size and memory

**Your input is copied and upcast to `float64` whatever you pass.** `contour_generator` runs
`np.ma.asarray(z, dtype=np.float64)` and `np.asarray(x, dtype=np.float64)`, so a `float32` grid
buys nothing: for a 2049×2049 field whose three `float32` arrays are 50.4 MB, building the
generator added 105.0 MB under `tracemalloc`. **The lever is the grid size, not the dtype.**
Passing 1-D `x` and `y` saves you writing `np.meshgrid`, not the memory — `contour_generator`
meshgrids them itself.

The output is the second cost, and the one the UI pays on every update: every vertex becomes a
`Path` element that crosses the Flet transport, and a 65×65 grid at eight levels traces on the
order of three thousand of them. Trace at the resolution the picture needs, not the one the data
has.

### App size

Approximately 0.25–0.30 MB compressed per architecture and 0.68–1.1 MB unpacked, almost all of it
the single C++ extension — so [`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup)
has nothing meaningful to remove. The same source is larger on iOS, about 0.92 MB of extension
against about 0.63 MB on Android arm64-v8a, so an iOS build does not track an Android measurement.
On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These figures are the package payload, not the amount added
to the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's wheel while a build pulls this index's, and the two can differ in
version even where the API does not. That bites hardest through numpy: this index's numpy sits
behind PyPI's newest, so `flet run` on your laptop and `flet build` can land on different numpy
versions unless you pin. PyPI also publishes free-threaded `cp313t`/`cp314t` builds and this index
does not, so a no-GIL experiment on the desktop does not carry to a device.

The arithmetic itself carries. On an arm64-v8a Android 14 emulator and an iPhone 16 simulator,
both CPython 3.14.6, a 65×65 grid at eight levels gives 7 bands and 21 rings, 2,267 filled
vertices and 949 isoline vertices, identically on both, with all four algorithms present in both
wheels. What to validate on a device is therefore the environment rather than the geometry: what
`max_threads()` answers, and whether any of your code reads a native module's `__file__`.

## Things to know

- **All four algorithms trace the same geometry, but not in the same order — so do not diff them
  vertex by vertex.** On the example's field they give identical ring counts and identical vertex
  counts, and their total contour length per level agrees to **4.4e-16**. An element-wise
  comparison of `mpl2005` against `serial` nonetheless reports differences up to 0.622 in a field
  one unit across — 0.00781 for `mpl2014`, 0 for `threaded` — because a closed ring is free to
  start at a different vertex and does. Compare a length, an area or a vertex count.
- **Asking `mpl2005` or `mpl2014` for the output format you want raises rather than converting.**
  `contour_generator(..., name="mpl2014", line_type="Separate")` is `ValueError: mpl2014 contour
  generator does not support line_type LineType.Separate`. Take each generator's own default and
  convert afterwards with
  [`convert_lines`](https://contourpy.readthedocs.io/en/latest/api/contourpy/other.html#contourpy.convert_lines)
  / [`convert_filled`](https://contourpy.readthedocs.io/en/latest/api/contourpy/other.html#contourpy.convert_filled),
  passing `gen.line_type` / `gen.fill_type` as the source. That is what makes an algorithm switch
  a one-line change instead of a rewrite.
- **`mpl2005` silently ignores chunking for contour lines.** At 129×129, level 0.0, it returned
  the same 2 rings and 223 vertices with `chunk_count=4` as with none, while `serial` under that
  setting returned 6 rings and 227 vertices — chunked output is cut at the chunk boundaries. It
  also refuses
  [`corner_mask`](https://contourpy.readthedocs.io/en/latest/api/contourpy/ContourGenerator.html#contourpy.ContourGenerator.corner_mask)`=True`
  outright (`ValueError: mpl2005 contour generator does not support corner_mask=True`).
- **Chunking changes the answer's shape, and `dechunk_lines` does not undo it.** Those 6 serial
  rings stayed 6 rings and 227 vertices after
  [`dechunk_lines`](https://contourpy.readthedocs.io/en/latest/api/contourpy/other.html#contourpy.dechunk_lines),
  because dechunking merges the chunk *containers*, not the polylines they cut in half. Whole
  rings mean no chunking; threads mean chunking. That trade is the real cost of `threaded`.
- **`nan` and `inf` are masked automatically, and a masked array behaves identically.** `z` goes
  through `np.ma.masked_invalid`, so missing data cuts the contours rather than corrupting them.
  On the example's field at 65×65, level 0.0: clean, 2 open polylines, 113 vertices, total length
  1.43991; with a 10×20 block of `nan` across the level, 3 polylines, 102 vertices, 1.30261 — no
  `nan` in the output and no warning raised. The same block as a `numpy.ma` mask gave identical
  numbers under `corner_mask=True` and `False` alike; `corner_mask` decides whether a quad
  touching a masked point is dropped whole or only in its nearest triangular corner, which a solid
  rectangular block does not exercise.
- **A level outside the data range is empty, not an error.** `lines(99.0)` returns `[]` and
  `filled(50.0, 99.0)` returns `([], [])`. Check for it and give it a UI state, because an empty
  canvas otherwise looks like a failure.
- **`filled()` gives holes as rings wound the other way, so sum *signed* areas.** On the example's
  field at 65×65 the +0.4…+0.6 band comes back as one enclosed area of three rings whose signed
  areas are 0.32924, −0.04574 and −0.10336: the real area is their sum, 0.18014, never the sum of
  the absolute values.
- **`z` must be 2-D and at least 2×2.** Anything else is a `TypeError` from `contour_generator`
  before the C++ is reached — `Input z must be 2D, not 1D`, or `Input z must be at least a (2, 2)
  shaped array, but has shape (1, 2)`.
- **Three of the `contourpy.util` modules import a package this wheel does not bring.**
  [`util.mpl_renderer`](https://contourpy.readthedocs.io/en/latest/api/util.html),
  `util.mpl_util` and `util.bokeh_renderer` import matplotlib or bokeh at module scope, so an app
  that installs only contourpy gets a `ModuleNotFoundError` from each — about 37 KB of Python you
  cannot reach. The two matplotlib ones import cleanly the moment [`matplotlib`](../matplotlib),
  which has mobile wheels of its own, is present. What works with contourpy alone is
  `contourpy.util` itself, `util.data`, `util.renderer` and `util.bokeh_util`.
- **`import contourpy` does not give you `contourpy.util`.** `__init__.py` never imports it, so
  `contourpy.util.build_config()` after a plain import is `AttributeError: module 'contourpy' has
  no attribute 'util'`, which inside a Flet event handler is a crash screen rather than a message.
  Write `from contourpy.util import build_config`. It reports the compiler, linker and cross-build
  flag of the wheel in front of you, and is the cheapest on-device confirmation that you are
  running the forge build and not something else.
- **Numpy scalars and Flet's wire format: `float64` is fine, narrower is not.** contourpy always
  returns `float64` arrays, and `numpy.float64` subclasses Python `float`, so coordinates handed
  straight to `ft.canvas.Path.LineTo` serialise. Cast them to `float32` or index an `int64` array
  to save memory and msgpack refuses with `TypeError: can not serialize 'numpy.float32' object`.
  `array.tolist()` is one C-level call and removes the doubt.
- **Do not locate anything relative to `contourpy._contourpy.__file__`, and do not assume the
  attribute exists.** Flet moves ABI-tagged extensions out of site-packages on both platforms, so
  that value is not a path you can open — on iOS a real path ending in `.fwork`, on Android no
  `__file__` at all. Read it as `getattr(module, "__file__", None)`: written plainly it is an
  `AttributeError`, and an `AttributeError` raised while your page is being built is a Flet crash
  screen rather than a message. Nothing in contourpy reads it, so this only bites code of yours;
  the [example](examples/contour-map) prints it in its header so you can read the real shape off a
  device.

## Build notes (maintainers)

### Recipe shape

No `patches/` directory and no `source:` key, so forge builds the PyPI sdist unmodified: sixteen
of the wheel's seventeen Python modules are byte-identical to the sdist's, the seventeenth being
the `util/_build_config.py` that meson generates. What follows is what `meta.yaml` cannot say for
itself.

**`flet-libcpp-shared` is a host requirement on Android only** because the two platforms source
the C++ runtime differently. Every Android slice names `libc++_shared.so` in `DT_NEEDED`, so the
`Requires-Dist` it produces is load-bearing rather than defensive; on iOS `otool -L` finds
`/usr/lib/libc++.1.dylib`, so C++ comes from the OS and a host requirement there would add a
dependency for nothing.

**The meson cross-file goes through `backend-args`** because meson-python forwards only
`-Csetup-args=…` to meson: `--cross-file` and forge's `{MESON_CROSS_FILE}` have to be two separate
entries to arrive as two argv words. Nothing else in the recipe communicates the cross target.

**The algorithm set is not a forge choice.** `src/meson.build` lists all fourteen `.cpp` files
unconditionally, with no meson option gating any of them and no thread feature flag anywhere in
the tree — so "all four algorithms are compiled in" is structural, and `-Dsomething=false` is not
a size lever that exists. The extension is small because it is stripped: upstream's own cp314
`manylinux_2_28_aarch64` wheel ships a 1,036,056-byte extension carrying `.symtab` and `.strtab`
against the forge build's 630,560 with neither. iOS slices are already `MH_DYLIB` and there is one
extension per wheel, so neither the `MH_BUNDLE` conversion nor the interdependent-dylib problem
arises.

Two harmless oddities, recorded so nobody re-investigates them: the cp313 and cp314 Android slices
carry a `RUNPATH` naming a CI directory that resolves to nothing on a device, and
`LC_BUILD_VERSION` reports `minos 14.0` on the arm64 *simulator* slice against 13.0 on the others,
though every wheel is tagged `ios_13_0`.

### Upgrade hazards

**The root `meson.build` sets `werror=true`**, so a new warning from a new NDK or a new Xcode is a
hard build failure — the likeliest way a bump or a toolchain bump breaks this recipe. Upstream set
it deliberately, so read the warning before reaching for `-Dwerror=false`.

**The `Requires-Python` floor moves.** It went from `>=3.10` to `>=3.11` within the 1.3 series,
and older wheels carrying the lower floor are still on the index. [Install](#install) tells app
authors to set `>=3.11` on the strength of the current one.

**The shared-generator abort is upstream C++ state, not a build artefact**, so a contourpy release
can fix or move it without the build noticing — and [Threading](#threading) rests on it entirely.

### Re-verification checklist

A green build establishes almost none of what the sections above claim, and `tests/` asserts none
of it.

- **`Requires-Python`** — off the built wheel's `METADATA`, not upstream's docs; reconcile with
  [Install](#install).
- **The `Requires-Dist` set** — `numpy>=1.25` plus, on Android only, `flet-libcpp-shared`. A new
  hard dependency changes the install snippet; a widened numpy floor changes what the example can
  pin.
- **The four class names** — `strings` on each new slice must still find the four
  `*ContourGenerator` classes, and the binary must still import
  `std::thread::hardware_concurrency`, `pthread_create` and `PyEval_SaveThread`. That set is what
  makes [Threading](#threading) true rather than aspirational.
- **The Android linkage** — `DT_NEEDED` must still name `libc++_shared.so` on all four ABIs, or
  the host requirement is dead weight. Re-check 16 KB `PT_LOAD` alignment (`p_align 0x4000`) and
  that iOS is still `MH_DYLIB`.
- **The extension filenames** — they must keep a CPython ABI tag; an untagged `NAME.so` gets no
  `.soref`, is never relocated into `jniLibs`, and becomes a silent `ModuleNotFoundError` on
  device. Three spellings are in play (`.cpython-312.so`,
  `.cpython-314-aarch64-linux-android.so`, `.cpython-314-iphoneos.so`), so match the `.cpython-`
  prefix, not an exact suffix.
- **That `__file__` is still absent** — `grep -rn '__file__'` across the wheel's `.py` files must
  keep hitting nothing, or the recipe may acquire an
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) requirement and
  [Install](#install) is wrong.
- **The wheel shape** — one extension, seventeen Python modules, no data file. A new data file
  reopens the `extract_packages` question against Android's zipped site-packages.
- **The measurements** — every timing, percentage and byte count above is measured, most on
  desktop CPython 3.12.13. Re-measure rather than scale: ratios transfer, absolute times do not.

### Coverage gaps

`tests/test_contourpy.py` covers two things: that `lines()` on a 5×5 paraboloid returns at least
one segment, and that a default generator initialises. Both are presence checks, and the second is
misnamed — its docstring calls `serial` "the recipe's reason for existing", true of the extension
but not of that algorithm. Nothing on device exercises the algorithm set, the winding convention
or threading at all.

Worth adding, in rough order of value: an `mpl2014` generator converted through `convert_lines`
and asserted equal in *length* to `serial`'s, which catches a build that lost an algorithm; a
`filled()` band with a hole whose signed areas must sum correctly, which pins the winding
convention consumers draw with; and a `threaded` generator at `chunk_count=4` asserting
`thread_count > 1`, the only on-device evidence that `hardware_concurrency()` returns something
useful on a phone. Assert relationships rather than version numbers — and do not try to test the
shared-generator abort, since it takes the test process down with it.
