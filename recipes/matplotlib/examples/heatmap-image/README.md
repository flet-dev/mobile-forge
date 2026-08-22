# matplotlib heat map

A radio survey of a 40 × 40 m room: three transmitters, a 240 × 240 grid of received
power, and a slider for the path-loss exponent. Release the slider and
[matplotlib](https://matplotlib.org/) redraws the field —
[`imshow`](https://matplotlib.org/stable/api/_as_gen/matplotlib.axes.Axes.imshow.html) for
the colour map,
[`contour`](https://matplotlib.org/stable/api/_as_gen/matplotlib.axes.Axes.contour.html)
for the level lines, and a
[`colorbar`](https://matplotlib.org/stable/api/figure_api.html#matplotlib.figure.FigureBase.colorbar)
for the scale.

What it demonstrates:

- **The render-to-bytes workflow.** There is no window to draw into on a phone, so the
  figure is rendered by Agg into an in-memory PNG and handed to
  [`Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src), which accepts raw
  bytes directly — no base64, no temporary file. The whole plot is about one 150 KB PNG per
  redraw; that is worth knowing if you plan to redraw continuously rather than on release.
- **A writable config directory, set before the first import.** The block above the imports
  in `main.py` points [`MPLCONFIGDIR`](https://matplotlib.org/stable/install/environment_variables_faq.html#envvar-MPLCONFIGDIR)
  at [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data).
  matplotlib resolves that directory once, while it is being imported, so anything below
  the import line is too late.
- **[`Figure`](https://matplotlib.org/stable/api/_as_gen/matplotlib.figure.Figure.html)
  and [`FigureCanvasAgg`](https://matplotlib.org/stable/api/backend_agg_api.html#matplotlib.backends.backend_agg.FigureCanvasAgg)
  instead of pyplot.** The render runs on a background thread, and pyplot's global figure
  registry is not built for that; it also keeps every figure it creates alive until
  something closes it. Building the figure directly avoids both, and skips the backend
  negotiation pyplot does on first use.
- **Compute off the UI thread.** The redraw runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the slider disabled and a spinner up, ending with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. It is bound to `on_change_end` rather than `on_change`, so dragging the
  slider queues one render, not thirty.
- **Which FreeType you got.** The header line reads it from
  [`ft2font`](https://matplotlib.org/stable/api/ft2font.html). It is matplotlib's own
  bundled copy, statically linked, the same on device as on your desktop — which is why the
  labels lay out identically in both places.

Push the exponent up and the contours pull in towards the markers as each transmitter's
reach collapses; the corners of the room go dark long before the middle does.

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
