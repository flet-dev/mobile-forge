# matplotlib

[`matplotlib`](https://matplotlib.org/) is Python's plotting library: line and bar charts,
scatter plots, histograms, contour and image plots, 3-D axes, colour maps, mathtext, and
export to PNG, SVG or PDF. On mobile it is what you reach for when Flet's own chart
controls stop being enough — a colour-mapped 2-D field, a log axis, error bars, a
publication-quality figure the user can save — all rendered offline on the device. These
wheels are the same matplotlib you have on your desktop: every Python file in them is
byte-for-byte the desktop wheel's, the only thing left out is the macOS GUI backend, and
FreeType is bundled inside `ft2font` exactly as upstream ships it — so a figure lays out
identically on a phone and on a laptop.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "matplotlib",
]

[tool.flet.android]
extract_packages = ["matplotlib"]
```

**The [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
not optional on Android** — without it `import matplotlib` fails outright, before you have
drawn anything. See [Android notes](#android-notes) for the symptom. It does nothing on
iOS, so it is safe to leave in place for a cross-platform build. There is no built-in
default list, so nothing adds it for you.

Everything matplotlib needs comes along on its own — 13 further wheels, none of which needs
configuring. `numpy`, `pillow`, `contourpy` and `kiwisolver` resolve from this index;
`fonttools`, `cycler`, `packaging`, `pyparsing` and `python-dateutil` (with its `six`) are
pure-Python wheels from PyPI; `flet-libjpeg` and `flet-libfreetype` are Pillow's native
dependencies, not matplotlib's; and on Android there is also `flet-libcpp-shared`, the NDK
C++ runtime all 8 of matplotlib's extensions link against. Add `numpy` to your own
dependency list only if your code imports it.

You will also want to point
[`MPLCONFIGDIR`](https://matplotlib.org/stable/install/environment_variables_faq.html#envvar-MPLCONFIGDIR)
somewhere writable before the first import — see [Storage](#storage). Skipping that one
breaks nothing; it just costs you a rebuilt font cache on every launch.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS
(device and both simulator architectures), on Python 3.12, 3.13 and 3.14 — the same
matplotlib version on every one of them.

## Storage

matplotlib wants a writable directory for its configuration and its font cache, and it
picks one **while it is being imported**. Give it one, first thing in your entry point,
before anything pulls matplotlib in:

```python
import os

mpl_dir = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "matplotlib")
os.makedirs(mpl_dir, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", mpl_dir)

import matplotlib.pyplot as plt
```

[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is the right home for it: the cache is cheap to rebuild but pointless to rebuild, and this
directory is app-private and never auto-deleted.
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
also works and is arguably more honest about the contents, at the cost of the OS
occasionally throwing it away.

Set it *above* the import, not after it — and remember that `import flet_charts` imports
matplotlib too, so it counts as "anything". Left unset, matplotlib falls back to
`~/.matplotlib` and tries to create it. On Android that fails: `HOME` is whatever the OS
handed the process, not the app sandbox, so matplotlib logs a warning, makes a throwaway
`tempfile.mkdtemp()` directory in
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
instead, and deletes it again at exit. Nothing breaks — you just rebuild the font cache on
every cold start, and you get a warning in `console.log` telling you to do what this section
says.

Figures you save are ordinary file writes, so
[`savefig`](https://matplotlib.org/stable/api/_as_gen/matplotlib.figure.Figure.savefig.html)
belongs in the same app-storage directories. From Flet 0.86.0 `FLET_APP_STORAGE_DATA` is
also the process working directory on device, so a bare relative filename lands there
anyway; spelling it out costs one line and behaves the same on desktop. If the figure is
only going on screen, you do not need a file at all — render into a `BytesIO` and hand the
bytes straight to [`Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`heatmap-image`](examples/heatmap-image) — renders a contoured heat map to PNG bytes and shows it in an `Image`.
- [`zoomable-series`](examples/zoomable-series) — the same renderer behind a live `MatplotlibChart` you can pan and zoom.

## Threading

matplotlib does not use threads here: none of the 8 extensions references `pthread_create`
or OpenMP on either platform. One figure renders on one core, however many the phone has.

Which means rendering on the handler thread freezes the UI, and a full-page figure is not
fast. Push the work to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads.

**Use [`Figure`](https://matplotlib.org/stable/api/_as_gen/matplotlib.figure.Figure.html)
and [`FigureCanvasAgg`](https://matplotlib.org/stable/api/backend_agg_api.html#matplotlib.backends.backend_agg.FigureCanvasAgg)
rather than pyplot when you do.** [`pyplot`](https://matplotlib.org/stable/api/pyplot_summary.html)
keeps a process-global registry of open figures and a notion of "the current figure";
neither is safe to touch from two threads, and upstream's own guidance is to avoid it for
embedded and server use. Figures you build directly are independent objects that move
between threads freely. The exception is
[`MatplotlibChart`](https://flet.dev/docs/controls/charts/matplotlibchart/), which needs the
canvas and manager that only pyplot attaches — see [Things to know](#things-to-know).

## Android notes

**Without `extract_packages`, matplotlib does not import at all.** Flet 0.86 ships
site-packages inside a stored `sitepackages.zip` and imports from it with `zipimport`, but
matplotlib finds its bundled data by joining a path onto its own `__file__`:
`get_data_path()` is literally `Path(__file__).with_name("mpl-data")`. Inside the zip that
is a path *through* a file, so the read fails while `matplotlib/__init__.py` is still
executing:

```
NotADirectoryError: [Errno 20] Not a directory:
  '/data/user/0/<applicationId>/files/.../sitepackages.zip/matplotlib/mpl-data/matplotlibrc'
```

(`FileNotFoundError` on the same path is the other form this takes.) It is not one unlucky
file either — ten modules that actually run on mobile resolve something under `mpl-data`
the same way: `matplotlibrc` at import, the bundled fonts, the style sheets, the AFM
metrics for PDF output, `cmr10.ttf` for tick labels, `cmsy10.ttf` for mathtext, the sample
data. The whole package has to be on disk, which is exactly what the `extract_packages`
entry does.

The other Android-specific detail is `HOME`: it points outside the app sandbox, which is
what sends matplotlib's config directory to a temp directory it recreates every launch —
see [Storage](#storage). On iOS `HOME` is inside the app's sandbox, so the same default
resolves somewhere the app can actually use. Neither is one of Flet's storage directories,
so set `MPLCONFIGDIR` on both platforms and stop thinking about it.

## Things to know

- **There is no GUI, and `plt.show()` does nothing.** matplotlib picks a backend the first
  time you use pyplot, by trying `macosx`, `qtagg`, `gtk4agg`, `gtk3agg`, `tkagg` and
  `wxagg` in turn and falling back to `agg`. On device every one of those fails —
  `matplotlib.backends._macosx` is the one extension deliberately absent from these wheels,
  and Flet's Python bundle contains no `tkinter` and no Qt, GTK or wx bindings — so
  `matplotlib.get_backend()` returns `agg`. (`_tkagg` *does* ship, and is the one extension
  in the wheel you cannot import: its initialiser pulls symbols out of `_tkinter`, so it
  raises `ImportError: initialization failed`. Nothing on device reaches it.) Calling
  [`show()`](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.show.html) then
  warns `FigureCanvasAgg is non-interactive, and thus cannot be shown` and returns
  immediately. The workflow that does work is: render, then display. Either encode the
  figure to bytes and put it in an
  [`Image`](https://flet.dev/docs/controls/image/#flet.Image.src), or use
  `MatplotlibChart` (next bullet). Setting `MPLBACKEND=Agg` alongside `MPLCONFIGDIR` costs
  nothing and skips those six failed imports; it does not change the outcome, and if you
  use `flet-charts` it is overridden anyway.
- **`MatplotlibChart` works on device, and it is a real Flet control.** The
  [`flet-charts`](https://pypi.org/project/flet-charts/) package ships
  [`MatplotlibChart`](https://flet.dev/docs/controls/charts/matplotlibchart/) and
  [`MatplotlibChartWithToolbar`](https://flet.dev/docs/controls/charts/matplotlibchartwithtoolbar/),
  which stream frames out of Agg into a Flutter widget and feed touch gestures back in, so
  you get pan, zoom and a save-to-file export instead of a static picture. It needs no
  recipe: the wheel is `py3-none-any` and installs from PyPI, and the Flutter half it
  carries is compiled into your app by `flet build`. Two things to know. It pins Flet to
  its own version exactly — `flet-charts` and `flet` share a version number and each release
  requires the matching one — so bump them together. And **the figure must come from
  pyplot** — importing `flet_charts` calls
  `matplotlib.use()` to install its own backend, and the control talks to the canvas and
  manager that backend attaches; a bare `Figure()` has `canvas.manager is None` and never
  draws.
- **Animations are limited to GIF.** `FuncAnimation` itself works, but of matplotlib's
  writers only
  [`PillowWriter`](https://matplotlib.org/stable/api/_as_gen/matplotlib.animation.PillowWriter.html)
  (GIF) and `HTMLWriter` are available: the ffmpeg writers need an `ffmpeg` binary on
  `PATH`, which no phone has, and `matplotlib.animation.writers.list()` drops them from the
  list accordingly. `MatplotlibChart` is the better answer for animation on screen — it
  redraws a live figure rather than materialising frames.
- **`text.usetex` and the `pgf` backend are unusable**, for the same reason: both shell out
  to a LaTeX installation. Mathtext is the substitute and it is fully functional — the STIX
  and Computer Modern fonts it needs are in `mpl-data/fonts`, so `$\sqrt{\alpha^2}$` in a
  label renders on device with nothing extra installed.
- **Everything else in matplotlib is here.** Compared file-by-file against the desktop PyPI
  wheel of the same version, the Android and iOS wheels contain the same 594 files and the
  desktop wheel has exactly one more: `matplotlib/backends/_macosx`, the macOS GUI backend.
  All 288 Python files are byte-identical, and so is every file under `mpl-data`. Android
  and iOS are identical to each other. `mpl_toolkits` — `mplot3d`, `axes_grid1` — is in the
  wheel, and `savefig` supports png, svg, svgz, pdf, ps, eps, raw, rgba, and jpeg/tiff/webp
  through Pillow.
- **Size, and the 2 MB you can delete.** The wheels are 8.0–8.3 MB and unpack to 19.7–20.9
  MB depending on architecture (Android arm64-v8a: 8.2 MB and 20.2 MB; iOS arm64: 8.1 MB
  and 20.9 MB). Nearly half of that is fonts: `mpl-data` is 9.0 MB unpacked, 8.3 MB of it
  the bundled DejaVu, STIX and Computer Modern faces, and you cannot drop those without
  breaking text rendering. What you *can* drop is matplotlib's own test suite, 2.0 MB on
  every architecture, which Flet's default
  [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) leaves alone
  because it strips headers, static archives and `__pycache__`, not tests:

  ```toml
  [tool.flet.cleanup]
  package_files = ["matplotlib/tests", "mpl_toolkits/*/tests"]
  ```

  The 0.5 MB of `mpl-data/sample_data` goes the same way if you never call
  `cbook.get_sample_data`.
- **Style sheets and `rcParams` work normally**, including the 26 bundled styles
  [`plt.style.available`](https://matplotlib.org/stable/api/style_api.html) lists, because
  `mpl-data/stylelib` is extracted along with the rest of the package. A `matplotlibrc` of
  your own is found through `MPLCONFIGDIR`, so put it in the directory you set in
  [Storage](#storage).

## Build notes (maintainers)

The recipe is upstream's meson-python build with nothing compiled out and nothing vendored,
so `meta.yaml` is the standard cross-file handoff plus the settings its own comments
justify, and the one patch explains itself in its preamble. What has no home in either file:

**The `extract_packages` entry in `meta.yaml` reaches the recipe-tester and nothing else.**
Forge's build ignores it; the tester's `stage_recipe.sh` turns it into
`[tool.flet.android].extract_packages` for the test app. It cannot reach a consumer — no
wheel can add a `pyproject.toml` entry to somebody's app. That asymmetry is why
[Install](#install) leads with the entry rather than mentioning it in passing: this recipe
going green on device is not evidence that an app which depends on it will even import
matplotlib.

**Verification here means launching an iOS app, not building one.** The failure the patch
exists to prevent kills the app in dyld before `Py_Initialize()`, which means no Python runs,
`console.log` is 0 bytes, and the crash report never mentions matplotlib. Nothing in
`unzip -l`, `otool`, the test suite or a green Android matrix can see it. Re-run a real iOS
device-or-simulator launch after every bump.

What to re-verify on a bump, in rough order of how quietly it can go wrong:

- **That the patch still applies to `src/_enums.h` and still does its job.** Upstream
  vendors that pybind11 enum helper, so it moves without warning; the check that matters is
  not "did the patch apply" but "does the built iOS app launch". If upstream ever fixes the
  static initializer itself, the patch goes away and so does the paragraph above.
- **The file-by-file comparison against the desktop wheel.** "594 files, one fewer than
  desktop, 288 Python files byte-identical, `_macosx` the only omission" comes from diffing
  the built wheels against the PyPI desktop wheel of the same version. It is what backs the
  claim that nothing is compiled out and that Android and iOS are identical, and every
  number in it moves on a bump. The extension count in [Threading](#threading) and the
  `pthread_create`/OpenMP claim come from the same pass.
- **`get_data_path()` still being `__file__`-relative, and still the reason for
  `extract_packages`.** The whole [Install](#install) snippet rests on it. The count of ten
  modules reading under `mpl-data` is a `grep` for `_get_data_path` outside `tests/`, minus
  the GUI, TeX and sphinx modules that never load on a phone; upstream moving to
  `importlib.resources` would retire the entry and rewrite
  [Android notes](#android-notes).
- **The backend fallback list.** `pyplot.switch_backend` hardcodes the candidates tried
  before `agg`; upstream reorders it occasionally, and a new candidate that *did* import on
  device would silently change what `get_backend()` returns. Re-assert `agg` on device
  rather than re-reading the list.
- **`flet-charts` compatibility.** It pins `flet` to its own version exactly, so it is
  really the Flet bump that constrains it, not this one. The `zoomable-series` example is
  the thing that catches a break — its pins are the record of a combination that ran.
- **The sizes, and FreeType.** Wheel and unpacked figures per architecture, the 9.0 MB
  `mpl-data`, and the 2.0 MB of tests the cleanup snippet removes are measured, not
  estimated. FreeType is downloaded and statically linked by matplotlib's own build (nothing
  passes `system-freetype`), which is what the "identical to desktop" claim in the intro
  rests on; a release that changes that pin changes the sizes and the text rendering
  together.
