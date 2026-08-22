# matplotlib zoomable series

Five years of daily readings — 1826 points, plus a smoothed overlay whose window you pick —
in a live [matplotlib](https://matplotlib.org/) figure. Turn on pan to drag, or zoom to
rubber-band a region, and the date axis relabels itself from years down to individual days
as you go in.

The figure is a
[`MatplotlibChart`](https://flet.dev/docs/controls/charts/matplotlibchart/) from
[`flet-charts`](https://pypi.org/project/flet-charts/): a real Flet control that streams
frames out of matplotlib's Agg renderer and feeds gestures back into it. That package is
pure Python and installs from PyPI on device like any other dependency — the Flutter half
it carries is compiled into the app by `flet build`. Nothing extra to configure.

What it demonstrates:

- **A live figure instead of a snapshot.** The chart keeps the figure interactive rather
  than shipping a rendered picture of it, which is what you want when the interesting
  detail is only visible zoomed in.
- **Why the figure has to come from pyplot.** Importing `flet_charts` registers a
  matplotlib [backend](https://matplotlib.org/stable/users/explain/figure/backends.html),
  and the control streams through the canvas and manager that backend attaches. Only
  pyplot's factory functions attach them: a bare `Figure()` has `canvas.manager is None`
  and the chart never draws.
- **Pushing an update.** Mutating a `Line2D` changes nothing on screen by itself — the
  redraw is `figure.canvas.draw()`. Switching the smoothing window recomputes the overlay
  and calls it.
- **A writable config directory, set before the first import.**
  [`MPLCONFIGDIR`](https://matplotlib.org/stable/install/environment_variables_faq.html#envvar-MPLCONFIGDIR)
  is pointed at [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  before anything imports matplotlib — and `import flet_charts` is one of the things that
  imports matplotlib, so it has to come first too.

Recomputing a moving average over 1826 points is instant, so this example does the work
inline. The *drawing* is not free, though: `figure.canvas.draw()` runs on the UI thread,
and a figure with far more artists than this one will show it. Build the expensive parts of
a figure in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
and leave only the `draw()` on the handler.

The three buttons above the chart are this app's own, driving the control's `home()`,
`pan()` and `zoom()` methods. `flet-charts` also ships a ready-made
[`MatplotlibChartWithToolbar`](https://flet.dev/docs/controls/charts/matplotlibchartwithtoolbar/),
which adds back/forward through the zoom history and an export that opens the platform's
save sheet — but it lays its eight controls out in a single non-scrolling `Row`, so on a
phone-width screen the row overflows its width. Prefer the plain control and your own
buttons on mobile.

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
