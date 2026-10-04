# vl-convert chart gallery

Three [Vega-Lite](https://vega.github.io/vega-lite/) charts, converted to PNG on the device
and shown in an [`ft.Image`](https://flet.dev/docs/controls/image/). Pick one with the
segmented button; the caption reports the size of the PNG and how long the conversion took.

What it demonstrates:

- **A spec in, a PNG out.**
  [`vl_convert.vegalite_to_png`](https://github.com/vega/vl-convert#readme) takes a Python
  dict and returns PNG bytes, which `ft.Image.src` accepts directly. No WebView, no network.
- **Vega doing the computing.** *Bars* colours bars with a conditional encoding, *Lines*
  draws a legend for three series, and *Fit* lays a LOESS curve over scattered points. The
  curve is computed by Vega's `loess` transform, in JavaScript, inside the app.
- **The first conversion is the slow one.** It boots the JavaScript runtime, and the caption
  shows it. Switching charts afterwards reuses the warm runtime.
- **Caches in app storage.** `charts.py` points vl-convert's bytecode cache and Google Fonts
  cache at [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
  before importing it, so the next launch skips recompiling Vega.
- **Off the UI thread.** Conversion runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, and the handler ends with an explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

`flet run` works on a desktop too, using PyPI's desktop wheel of the same version.
