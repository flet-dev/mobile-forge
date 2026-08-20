# contourpy

[`contourpy`](https://contourpy.readthedocs.io) turns a 2-D grid of values into geometry: the
polylines where the field crosses a level ([`lines()`](https://contourpy.readthedocs.io/en/latest/api/contourpy/ContourGenerator.html#contourpy.ContourGenerator.lines))
and the polygons between two levels ([`filled()`](https://contourpy.readthedocs.io/en/latest/api/contourpy/ContourGenerator.html#contourpy.ContourGenerator.filled)).
It is the engine under `matplotlib.contour` — [`matplotlib`](../matplotlib)'s own Android wheel
declares `Requires-Dist: contourpy>=1.0.1` — and it is worth reaching for directly when you want
the *shapes* rather than a picture: an isoline you will draw on an
[`ft.canvas.Canvas`](https://flet.dev/docs/controls/canvas/), a coverage polygon you will hit-test,
a band you will fill in your own colours. The wheel's own `Summary` line names the job: *Python
library for calculating contours of 2D quadrilateral grids*.

On a phone it is small and self-contained. Each wheel is 24 entries — one C++ extension, seventeen
Python modules, a `.pyi` stub, `py.typed` and four `dist-info` files — with no data file and no
Python dependency beyond numpy. The cp314 extension is 630,560 bytes on Android arm64-v8a and
918,728 on iOS device, and it opens nothing: across all nineteen published slices there is no
`open`, `fopen`, `stat`, `socket`, `connect` or `getenv` among the undefined symbols. The only
stdio in any of them is `printf`/`putchar`, plus `fprintf`/`fwrite` on seven of the ten Android
slices, all of it against a stream somebody else opened — so it touches neither the filesystem nor
the network. What goes in is a numpy array and what comes out is numpy arrays.

**All four contour algorithms are compiled into every slice.** `contourpy/__init__.py` imports
`Mpl2005ContourGenerator`, `Mpl2014ContourGenerator`, `SerialContourGenerator` and
`ThreadedContourGenerator` unconditionally, so a missing one would break `import contourpy`
outright; and each of those four class names is present in the symbol strings of all nineteen
binaries. `threaded` is a real threaded build, not a stub — every slice imports
`std::thread::hardware_concurrency`, `std::thread::join`, `pthread_create`, `std::mutex` and
`std::condition_variable`. Which one to pick is in [Things to know](#things-to-know); how to make
`threaded` actually use more than one core is in [Threading](#threading).

It is also accurate in a way you can check without trusting it. Contour `z = x² + y²` at `z = 1`
and you must get the unit circle. Measured on desktop over `[-1.5, 1.5]²`, the traced polygon's
shoelace area against π, at grids of 17, 33, 65, 129, 257 and 513: −1.141%, −0.308%, −0.073%,
−0.019%, −0.0046%, −0.0012%. Every halving of the grid spacing cuts the error by roughly four —
the error is quadratic in the spacing, and the polygon is always inscribed, so it always reads
slightly small. The [example](examples/contour-map) prints that number live at whatever grid you
choose.

**Measured on device, 2026-08-20**, on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6 with numpy 2.4.6. The geometry is identical on the two platforms,
as it must be: a 65×65 grid at 8 levels gives 7 bands and 21 rings, 2,267 filled vertices and
949 isoline vertices, and all four algorithms — `serial`, `threaded`, `mpl2014`, `mpl2005` — are
compiled into both wheels.

Two things do differ, and both matter if you reach for the `threaded` algorithm or for
introspection:

- **`max_threads()` reports 10 on the iPhone simulator and 4 on the Android emulator.** It
  follows the host's core count, so treat it as a property of the device rather than of the
  wheel, and do not hard-code a chunk count tuned on one of them.
- **`_contourpy.__file__` does not exist on Android.** The example prints whatever the device
  resolves; on iOS that is a real path ending `site-packages/contourpy/_contourpy.fwork`, and on
  Android there is no `__file__` at all. Any code that locates data relative to a native
  extension's `__file__` breaks there.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "contourpy",
    "numpy",
]
```

[`numpy`](../numpy) arrives on its own — `Requires-Dist: numpy>=1.25` is the only non-extra
requirement on the iOS wheels and one of two on the Android ones, and `contourpy/__init__.py`
imports it at module scope. It is listed above anyway because you cannot use this package without
touching numpy yourself: `contour_generator` takes arrays and every result is arrays.

Both entries belong in top-level `[project] dependencies` rather than in the
`[tool.flet.android]` / `[tool.flet.ios]` tables, because `flet build` resolves for the build host
first and PyPI has desktop wheels for every host you would build from. The 1.3.3 release is 72
files — CPython 3.11–3.14 on macOS (`x86_64` and `arm64`), Linux (`manylinux` × x86_64, aarch64,
ppc64le and s390x, `musllinux` × x86_64 and aarch64) and Windows (`win32`, `win_amd64`,
`win_arm64`), the free-threaded `cp313t`/`cp314t` variants, five PyPy 3.11 wheels and the sdist.

**A bare `contourpy` resolves from this index for a mobile target even though PyPI carries the
same version number.** Checked with `pip download --only-binary :all:` with `--index-url
https://pypi.org/simple` and this index only as `--extra-index-url`: an Android arm64-v8a / cp314
target and an iOS device / cp312 target both came back with `contourpy-1.3.3-1-…`, this index's
build 1. None of PyPI's 72 files carries an Android tag, an iOS tag or `py3-none-any`, so there is
no tie for the build tag to break — pip simply finds nothing else that fits the platform. A bare
`numpy` behaves the same way and resolves this index's `numpy-2.4.6-1-…`, which is behind PyPI's
newest (2.5.2 today), so `flet run` on your laptop and `flet build` can land on different numpy
versions unless you pin.

**Raise `requires-python` to `>=3.11` if you pin either package with `==`.** contourpy 1.3.3
declares `Requires-Python: >=3.11` in its `METADATA` and on the index; so does numpy 2.4.6. uv
resolves for *every* version your project claims to support, not just the interpreter in use, so
leaving the `>=3.10` that `flet create` writes fails the build outright with

```
× No solution found when resolving dependencies for split (markers: python_full_version == '3.10.*'):
╰─▶ Because the requested Python version (>=3.10) does not satisfy Python>=3.11 and
    contourpy==1.3.3 depends on Python>=3.11, we can conclude that contourpy==1.3.3 cannot be used.
```

Verified by copying the [example's](examples/contour-map) `pyproject.toml` alone into an empty
directory and running `uv lock` there: `>=3.11` resolves 54 packages, `>=3.10` produces exactly the
message above. Note that this floor is new — the 1.3.1 wheels still on the index carry `>=3.10`.

No
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed and no loader shim: `grep -rn '__file__'` across the wheel's seventeen Python
modules finds nothing at all, so no code path needs a real directory, and the extension carries a
CPython ABI tag in its filename on every slice, which is what Flet's relocation of native modules
keys on. There is no data file. Flet's default
[compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) rewrites the
seventeen modules to `.pyc` in place and deletes the `.py` originals — `compile.packages` is on by
default and serious_python 4.5.1 runs `compileall -b` over site-packages and then removes every
`**.py` — and drops the 7,122-byte `_contourpy.pyi` and the empty `py.typed`, two of the twelve
globs in its `junkFilesDesktop` list, which `junkFilesMobile` extends. Nothing in contourpy reads
any of them at runtime.

Nineteen wheels at build 1: Python 3.12 across all four Android ABIs (arm64-v8a, armeabi-v7a,
x86_64 and the legacy 32-bit `android_24_x86`), 3.13 and 3.14 across three each, and all three iOS
slices (device, arm64 simulator, x86_64 simulator) for each of the three Pythons. No architecture
is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) narrowing is
needed. The wheels are 245,626 to 298,845 bytes; unpacked, 683,351 to 1,061,657.

On Android one more wheel arrives with it; see [Android notes](#android-notes).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`contour-map`](examples/contour-map) — filled bands and isolines drawn on a canvas, the four
  algorithms timed against each other, and a contour that must be a circle measured against π.

## Threading

**`name="threaded"` does nothing until you also chunk the grid, and it fails silently.**
`thread_count` defaults to 0, meaning "use `max_threads()`", but the generator caps it at the
number of chunks — and the default is one chunk. Measured on desktop, nine levels over a
2049×2049 grid, best of three: a `threaded` generator built with no chunking reports
`thread_count == 1` and takes 74.6 ms, against 75.6 ms for `serial`. Add `chunk_count=4` and the
same generator reports `thread_count == 10` and takes 19.1 ms — 4.0× faster than serial.
`chunk_count=2` gives `thread_count == 4` and 24.7 ms, `chunk_count=8` 19.3 ms, `chunk_count=16`
21.5 ms. So chunk at least as many ways as you want threads, and past that it stops paying.

**`max_threads()` is whatever the device reports.** It is
`std::thread::hardware_concurrency()` straight through, 10 on the desktop these numbers come
from; no figure for a phone or a simulator is asserted here, and the
[example](examples/contour-map) prints it in its header so you can read the real one.

**The tracing releases the GIL, but only about half the time.** `PyEval_SaveThread` and
`PyEval_RestoreThread` are imported by all nineteen slices. Measured on desktop with a counter
thread running beside the work and its rate given as a percentage of an idle window: controls
first, `time.sleep(0.5)` (releases) 94.6%, `math.factorial(190000)` (holds) 4.5%. Then nine
`serial` `lines()` calls over a 2049×2049 grid, three runs: 46.7%, 48.9%, 47.5%. Half of that
call is C++ tracing with the GIL dropped and half is building the numpy output arrays with it
held, and no amount of threading changes the second half.

**A busy Python thread is much worse for `threaded` than for `serial`.** The C++ workers have to
take the GIL back to allocate each chunk's output, so a Python thread that never yields starves
them. Same grid, same nine levels, best of three: `serial` 67.1 ms alone, 117.3 ms beside a
pure-Python spin loop, 66.3 ms beside a thread that sleeps; `threaded` with `chunk_count=8`
**14.0 ms alone, 823.0 ms beside the spin loop**, 14.6 ms beside the sleeping one. A Flet UI
thread is mostly the sleeping kind, so this is a warning about your *own* background work rather
than about Flet — but it is a 59× cliff, and it is invisible in a single-threaded benchmark.

**Give every worker its own generator. Sharing a `threaded` one kills the process.** Six Python
threads calling `lines()` on one shared `threaded` generator (`chunk_count=4`, 513×513 grid, ten
rounds of nine levels each) took the interpreter down on **every** run: one aborted with
`libc++abi: terminating due to uncaught exception of type std::runtime_error: Inconsistent zero
total_point_count for chunk -3. This may indicate a bug in ContourPy.` and exit code 134, and two
more died with SIGSEGV and exit code 139. That message string is present in all nineteen shipped
mobile binaries, so it is the same code path on device — and an abort is not a Python exception
and not a Flet crash screen, the app simply disappears. The identical work with one generator per
thread was correct on both runs of it, 540 of 540 comparisons each.

**Chunking is not what makes it unsafe.** A second, deliberately different shape — four threads,
no `chunk_count` at all, ten rounds of nine levels on 129×129 and 65×65 grids — died on all five
runs of it too, four with SIGSEGV and one with SIGTRAP, silently and with no message at all. So an
unchunked `threaded` generator, which is what you get whenever you never touch `chunk_count`, is
no safer to share than a chunked one; the same run at `chunk_count=8` aborted 3 of 3 times with
exit code 134, twice reporting `Inconsistent total_point_count for chunk -6` and once the
`Inconsistent zero` spelling. Both spellings are in all nineteen shipped mobile binaries.

A shared **`serial`** generator survived the same test — 540 of 540 correct with no exception on
8 of 8 runs — which is evidence, not a guarantee: nothing upstream documents a generator as
thread-safe. Build one per call. It costs a fraction of the trace, and the
[example](examples/contour-map) does it that way.

Put anything past a few thousand grid points in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), end the
worker with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
because auto-update does not reach a background thread, and wrap the body in `try/except` because
`run_thread` never retrieves the worker's future and discards whatever it raised — with no log, no
dialog and no crash. Note also that `run_thread` submits to a shared pool, so two quick taps
genuinely overlap: that is the situation the shared-generator abort above needs.

## Android notes

**One extra wheel arrives: `flet-libcpp-shared`.** The extension is C++ and every Android slice
names `libc++_shared.so` in `DT_NEEDED` — the full list is `libm.so`, `libpython3.<minor>.so`,
`libc++_shared.so`, `libdl.so`, `libc.so` on arm64-v8a, x86_64 and the legacy `x86` slice, and the
same minus `libdl.so` on armeabi-v7a. So the `Requires-Dist: flet-libcpp-shared
(>=27.2.12479018)` that every Android wheel carries is load-bearing rather than defensive, and it
is the only non-extra `Requires-Dist` line beyond `numpy>=1.25`. Its sole payload file is
`opt/lib/libc++_shared.so` — measured at 1,292,904 bytes on arm64-v8a, 872,872 on armeabi-v7a and
1,252,080 on x86_64 in the 27.3.13750724 release. Nothing to configure; it resolves on its own.

**Every slice is 16 KB page-aligned**, as Android 15 requires: every `PT_LOAD` segment in all ten
Android extensions reports `p_align 0x4000`. arm64-v8a and x86_64 are `ELF64`; armeabi-v7a and the
legacy `x86` slice are genuine `ELF32`/`ARM` and `ELF32`/`i386` builds.

**The cp313 and cp314 slices carry a `RUNPATH` naming a CI directory.** For example
`/home/runner/work/mobile-forge/mobile-forge/downloads/support/python-android-mobile-forge-3.14/install/android/arm64-v8a/python-3.14.5/lib/pkgconfig/../../lib`.
It points at nothing on a device and Android resolves `libpython3.14.so` out of the app's own
library directory regardless, so no failure has been observed from it — but it is there, and the
cp312 slices have no `RUNPATH` at all. None of the ten has a `SONAME`.

**Two extension filename shapes are in play on Android, split by Python version.** cp313 and cp314
ship the full triplet — `contourpy/_contourpy.cpython-314-aarch64-linux-android.so` — while all
four cp312 ABIs ship the short forge tag `contourpy/_contourpy.cpython-312.so`. (iOS is a third
shape again, `_contourpy.cpython-312-iphoneos.so`, at every Python version.) All of them are
ABI-tagged, which is all the relocation needs — serious_python 4.5.1's Android build matches
`\.(cpython-[^/]+|abi3)\.so$` — so none of the three asks anything of you.

**The Android `METADATA` is 4,038 bytes against 3,986 on iOS**, the difference being the appended
`flet-libcpp-shared` line — 52 bytes, exactly. Neither platform ships upstream's long description:
nothing at all follows `Description-Content-Type: text/markdown` on iOS, and on Android only that
one appended line.

## iOS notes

**Nothing extra to install.** The iOS wheels name `numpy>=1.25` as their only non-extra
requirement, because C++ comes from the OS: `otool -L` on each of the nine iOS slices names only
its own install name, `@rpath/Python.framework/Python`, `/usr/lib/libc++.1.dylib` and
`/usr/lib/libSystem.B.dylib`.

**No `MH_BUNDLE` problem here.** All nine report `filetype DYLIB` under `otool -hv`, so the
conversion some CMake-built extensions need does not arise, and there is exactly one extension per
wheel so there is no interdependent-dylib problem either.

**The same code is much bigger on iOS.** The cp314 extension is 918,728 bytes on device against
630,560 on Android arm64-v8a — 1.46× — and unpacked, one cp314 wheel is 1,054,266 bytes against
766,120. The Python half is all but identical — 120,816 bytes of modules on Android against
120,856 on iOS, the 40-byte gap being the build paths baked into `util/_build_config.py` — so the whole
difference is the binary. Android then adds `libc++_shared.so` on top, which iOS does not need.

**The arm64 simulator slice disagrees with its own wheel tag about the deployment target.**
`LC_BUILD_VERSION` reports `minos 13.0` on the device slice and on the x86_64 simulator slice but
`minos 14.0` on the arm64 simulator slice, at all three Python versions, though every wheel is
tagged `ios_13_0`. Simulator-only, so no consumer impact has been observed, but it is a real
disagreement.

## Things to know

- **Pick `serial` unless you have chunked the grid, and then pick `threaded`.** The four
  algorithms are not four qualities of result — they are one result with different output formats
  and different feature sets. Measured on desktop:

  | algorithm | default `line_type` | default `fill_type` | `corner_mask` | threads | `quad_as_tri` | `z_interp` |
  | --- | --- | --- | --- | --- | --- | --- |
  | `serial` | `Separate` | `OuterOffset` | yes | no | yes | yes |
  | `threaded` | `Separate` | `OuterOffset` | yes | yes | yes | yes |
  | `mpl2014` | `SeparateCode` | `OuterCode` | yes | no | no | no |
  | `mpl2005` | `SeparateCode` | `OuterCode` | **no** | no | no | no |

  `serial` and `threaded` accept all five `LineType`s and all six `FillType`s; `mpl2014` and
  `mpl2005` accept exactly one of each. The two `mpl*` generators exist for bug-for-bug fidelity
  with old matplotlib releases; on a new codebase there is no reason to choose them. On the
  [example's](examples/contour-map) field at a 129×129 grid, seven filled bands plus six line
  levels, best of five: `serial` 0.56 ms, `threaded` 0.57 ms (unchunked, so single-threaded),
  `mpl2005` 0.69 ms, `mpl2014` 1.16 ms.
- **All four trace the same geometry, but not in the same order — so do not diff them vertex by
  vertex.** On that same field they produce identical ring counts and identical vertex counts, and
  their total contour length per level agrees to **4.4e-16**. Yet an element-wise comparison of
  `mpl2005` against `serial` reports differences up to 0.622 in a field one unit across — 0.00781
  for `mpl2014`, 0 for `threaded` — because a closed ring is free to start at a different vertex
  and does. Compare a length, an area or a
  vertex count; the [example](examples/contour-map) compares length and prints the residual.
- **Asking `mpl2005` or `mpl2014` for the output format you want raises rather than converting.**
  `contour_generator(..., name="mpl2014", line_type="Separate")` is
  `ValueError: mpl2014 contour generator does not support line_type LineType.Separate`. Take each
  generator's own default and convert afterwards with
  [`convert_lines`](https://contourpy.readthedocs.io/en/latest/api/contourpy/other.html#contourpy.convert_lines)
  / [`convert_filled`](https://contourpy.readthedocs.io/en/latest/api/contourpy/other.html#contourpy.convert_filled),
  passing `gen.line_type` / `gen.fill_type` as the source. That is what makes an algorithm switch
  a one-line change instead of a rewrite.
- **`mpl2005` silently ignores chunking for contour lines.** On the same field at a 129×129
  grid, level 0.0, it returned the same 2 rings and 223 vertices with `chunk_count=4` as with no
  chunking, while `serial` under that setting returned 6 rings and 227 vertices — chunked output
  is cut at the chunk boundaries. `mpl2005` also refuses `corner_mask=True` outright
  (`ValueError: mpl2005 contour generator does not support corner_mask=True`).
- **Chunking changes the answer's shape, and `dechunk_lines` does not undo it.** Those 6 serial
  rings stayed 6 rings and 227 vertices after
  [`dechunk_lines`](https://contourpy.readthedocs.io/en/latest/api/contourpy/other.html#contourpy.dechunk_lines),
  because dechunking merges the chunk *containers*, not the polylines they cut in half. If you
  need whole rings, do not chunk; if you need threads, you must chunk. That trade is the real cost
  of `threaded`.
- **Your input is copied and upcast to float64 whatever you pass.** `contour_generator` runs
  `np.ma.asarray(z, dtype=np.float64)` and `np.asarray(x, dtype=np.float64)`, so a float32 grid
  buys nothing: for a 2049×2049 field whose three float32 arrays are 50.4 MB, building the
  generator added 105.0 MB under `tracemalloc` — the float64 copies. On a phone that is the number
  to budget against, and the lever is the grid size, not the dtype. Passing 1-D `x` and `y` saves
  you writing `np.meshgrid`, not the memory: `contour_generator` meshgrids them itself.
- **`nan` and `inf` are masked automatically, and a masked array behaves identically.** `z` goes
  through `np.ma.masked_invalid`, so missing data cuts the contours rather than corrupting them.
  Measured on the example's field at 65×65, level 0.0: clean, 2 polylines — both open, running out
  to the domain edge — 113 vertices, total length 1.43991; with a 10×20 block of `nan` across the
  level, 3 polylines, 102 vertices, 1.30261 — no `nan` in the output and no warning raised. The
  same block as a `numpy.ma` mask gave the
  identical three numbers, with `corner_mask=True` and `corner_mask=False` alike; `corner_mask`
  decides whether a quad touching a masked point is dropped whole or only in its nearest
  triangular corner, which a solid rectangular block does not exercise.
- **A level outside the data range is empty, not an error.** `lines(99.0)` returns `[]` and
  `filled(50.0, 99.0)` returns `([], [])`. Check for it and give it a UI state, because an empty
  canvas otherwise looks like a failure.
- **`filled()` gives holes as rings wound the other way, so sum *signed* areas.** On the
  [example's](examples/contour-map) field at 65×65 the +0.4…+0.6 band comes back as one enclosed
  area of three rings whose signed areas are 0.32924, −0.04574 and −0.10336: the real area is
  their sum, 0.18014, never the sum of the absolute values. The same convention is what lets one canvas
  `Path` with several subpaths render the hole correctly under the non-zero fill rule, which is
  how the [example](examples/contour-map) draws its bands.
- **`z` must be 2-D and at least 2×2.** Anything else is a `TypeError` from `contour_generator`
  before the C++ is reached — `Input z must be 2D, not 1D`, or
  `Input z must be at least a (2, 2) shaped array, but has shape (1, 2)`.
- **Three of the `contourpy.util` modules import a package this wheel does not bring.**
  `contourpy.util.mpl_renderer`, `contourpy.util.mpl_util` and `contourpy.util.bokeh_renderer`
  import matplotlib or bokeh at module scope, so on an app that installs only contourpy each
  raises `ModuleNotFoundError` — that is 37,380 bytes of Python you cannot reach. They are not
  broken, though: the two matplotlib ones import cleanly the moment matplotlib is present, and
  [`matplotlib`](../matplotlib) has mobile wheels of its own. What imports with contourpy alone is
  `contourpy.util` itself (which exports only `build_config`), `contourpy.util.data`,
  `contourpy.util.renderer` and `contourpy.util.bokeh_util`.
- **`contourpy.util.build_config()` tells you how the wheel in front of you was built**, which is
  the cheapest way to confirm on device that you are running the forge build and not something
  else. **`import contourpy` does not give you `contourpy.util`** — `__init__.py` never imports
  it, so `contourpy.util.build_config()` after a plain `import contourpy` is
  `AttributeError: module 'contourpy' has no attribute 'util'` (verified on desktop), which inside
  a Flet event handler is a crash screen rather than a message. Write
  `from contourpy.util import build_config`. The Android cp314 slice reports
  `compiler_name="clang"`, `compiler_version="18.0.4"`,
  `linker_id="ld.lld"`, `host_cpu_system="android"`, `cross_build="True"` and a
  `compile_command` naming NDK 27.3.13750724; the iOS cp314 slice reports clang 21.0.0, `ld64`
  and `host_cpu_system="ios"`. Both name `cpp_std="c++17"`, `optimization="3"` and pybind11 3.0.4.
- **Numpy scalars and Flet's wire format: `float64` is fine, narrower is not.** contourpy always
  returns `float64` arrays, and `numpy.float64` subclasses Python `float`, so coordinates handed
  straight to `ft.canvas.Path.LineTo` serialise. Cast them to `float32` or index an `int64` array
  to save memory and msgpack refuses with `TypeError: can not serialize 'numpy.float32' object`.
  `array.tolist()` is the cheap way to be certain, and it is one C-level call.
- **Do not locate anything relative to `contourpy._contourpy.__file__`, and do not assume the
  attribute exists.** Flet moves ABI-tagged extensions out of site-packages on both platforms, so
  that value is not a path you can open — and on Android it may be missing outright rather than
  merely wrong. Read it as `getattr(module, "__file__", None)`: written plainly it is an
  `AttributeError`, and an `AttributeError` raised while your page is being built is a Flet crash
  screen rather than a message. Nothing in contourpy reads it, so this only bites code of yours;
  the [`contour-map`](examples/contour-map) example prints it in its header so you can read the
  real shape off a device.
- **The native code is small because it is stripped.** Upstream's own cp314
  `manylinux_2_26_aarch64.manylinux_2_28_aarch64` wheel — same source, same architecture family —
  ships a 1,036,056-byte extension carrying `.symtab` and `.strtab`; the forge build of the same
  file is 630,560 bytes with neither.

## Build notes (maintainers)

`meta.yaml` is twenty lines: meson/ninja/cmake as build requirements, pybind11 as a host
requirement, `flet-libcpp-shared` added for Android only, and the meson cross-file threaded
through `backend-args`. There is no `patches/` directory and no `source:` key, so forge builds the
PyPI sdist unmodified — confirmed against `contourpy-1.3.3.tar.gz`: sixteen of the wheel's
seventeen Python modules are byte-identical to the sdist's, and the seventeenth is
`util/_build_config.py`, which meson generates during the build. What is left for here is why that
is the whole recipe, and the bump checklist.

**Nothing about the algorithm set is a forge choice.** `src/meson.build` lists all fourteen `.cpp`
files unconditionally — `mpl2005.cpp`, `mpl2005_original.cpp`, `mpl2014.cpp`, `serial.cpp`,
`threaded.cpp` and the rest — with no meson option gating any of them and no thread feature flag
anywhere in the tree. So "all four algorithms are compiled in" is structural, not something a
build flag could quietly drop, and `-Dsomething=false` is not a size lever that exists.

**The root `meson.build` sets `werror=true`.** A new compiler warning from a new NDK or a new
Xcode is a hard build failure, and that is the likeliest way a bump or a toolchain bump breaks
this recipe. It is also worth knowing before reaching for `-Dwerror=false` as a fix: upstream set
it deliberately, so a warning is worth reading first.

What to re-verify on a bump — a green build establishes almost none of what the sections above
claim, and none of it is asserted by `tests/`:

- **`Requires-Python`.** It moved from `>=3.10` (1.3.1, still on the index) to `>=3.11` (1.3.3),
  and [Install](#install) tells app authors to set `requires-python = ">=3.11"` on the strength of
  it. Read it off the built wheel's `METADATA`, not off upstream's docs.
- **The `Requires-Dist` set.** `numpy>=1.25` plus, on Android only, `flet-libcpp-shared`. A new
  hard dependency would change the install snippet; a widened numpy floor would change what the
  example can pin.
- **The four class names.** `strings` on each new slice must still find `Mpl2005ContourGenerator`,
  `Mpl2014ContourGenerator`, `SerialContourGenerator` and `ThreadedContourGenerator`, and the
  binary must still import `std::thread::hardware_concurrency` and `pthread_create` — that pair is
  what makes the [Threading](#threading) section true rather than aspirational.
- **The Android linkage.** `DT_NEEDED` must still name `libc++_shared.so` on all four ABIs, or the
  `flet-libcpp-shared` requirement is dead weight and [Android notes](#android-notes) is wrong.
  Re-check 16 KB `PT_LOAD` alignment at the same time, and that iOS is still `MH_DYLIB`.
- **The extension filenames.** They must keep a CPython ABI tag; an untagged `NAME.so` gets no
  `.soref`, is not relocated into `jniLibs`, and becomes a silent `ModuleNotFoundError` on device.
  Three spellings are already in play — `_contourpy.cpython-312.so`,
  `_contourpy.cpython-314-aarch64-linux-android.so` and `_contourpy.cpython-314-iphoneos.so` — so
  a check must match the `.cpython-` prefix, not an exact suffix.
- **That `__file__` is still absent from the package.** `grep -rn '__file__'` across the wheel's
  `.py` files hits nothing on 1.3.3. The moment it hits something, this recipe may acquire an
  `extract_packages` requirement and [Install](#install) is wrong.
- **The wheel shape.** Still 24 entries, still no data file. A new data file would put the
  no-`extract_packages` claim back in question, and a package data directory would need checking
  against Android's zipped site-packages.
- **The measurements.** Every timing, percentage and byte count above is measured, most on desktop
  CPython 3.12.13 with numpy 2.4.6. Re-measure rather than scaling: the ratios transfer, the
  absolute times do not. The `libc++_shared.so` payload sizes move with the `flet-libcpp-shared`
  recipe rather than this one.
- **The shared-generator abort.** It is upstream C++ state, not a build artefact, so a contourpy
  release can fix or move it without the build noticing — and the advice in
  [Threading](#threading) rests on it.

`tests/test_contourpy.py` covers two things today: that `lines()` on a 5×5 paraboloid returns at
least one segment, and that a default generator initialises. Both are presence checks, and the
second is misnamed — its docstring calls `serial` "the recipe's reason for existing", which is
true of the extension but not of that algorithm in particular. Worth adding, in rough order of
value: a `mpl2014` generator converted through `convert_lines` and asserted equal in *length* to
`serial`'s, which would catch a build that lost an algorithm or a release that changed one;
`filled()` over a band with a hole, asserting the signed areas sum correctly, which pins the
`OuterOffset` winding convention that consumers draw with; and a `threaded` generator with
`chunk_count=4` asserting `thread_count > 1`, which is the only on-device evidence that
`hardware_concurrency()` returns something useful on a phone. Per the repo's test convention,
assert relationships rather than version numbers — and do not try to test the shared-generator
abort, since it takes the test process down with it.
