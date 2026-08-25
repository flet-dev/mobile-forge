# pyproj control points

One screen of coordinate maths that checks its own answers. Every projected coordinate is
differenced against arithmetic written in `src/coordinates.py`, so what you read on the
device is a residual in millimetres rather than a claim. `src/main.py` is the Flet layer
and nothing else.

It carries no data file. The mobile wheels ship no `proj.db`, and this app plants an empty
one in [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
instead of a 9 MB asset — which is enough for everything on screen except the one row that
is there to fail.

What it demonstrates:

- **What works with no PROJ database at all** —
  [`Geod`](https://pyproj4.github.io/pyproj/stable/api/geod.html) distances checked against
  a Vincenty inverse implemented in the app, and `Geod.fwd` walking back the azimuth
  `Geod.inv` returned to see how far it misses.
- **Projections from `+proj=` strings off an empty `proj.db`** — Web Mercator differenced
  against its closed form, UTM 33N and the British National Grid against a transverse
  Mercator series written in the app. A round trip is deliberately *not* the check: a
  string with the wrong zone, ellipsoid or unit inverts as cleanly as the right one and
  still reads 0.0000 mm. The round trips are printed on their own line, where all they
  measure is whether the National Grid's `+towgs84` Helmert reverses — it does, to a
  millimetre.
- **The [`always_xy`](https://pyproj4.github.io/pyproj/stable/api/transformer.html) trap,
  shown rather than described** — a latitude-first CRS transformed twice from the same
  argument pair, so the swap is visible on screen.
- **Where the missing database actually bites** — `CRS.from_epsg(4326)` is left unguarded,
  and prints a CRS name on a desktop and a `CRSError` on a phone.
- **A vectorised round trip on a [`ft.Slider`](https://flet.dev/docs/controls/slider/)**
  — up to 200,000 points through `array('d')` buffers with no numpy, run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread).

Nothing here reaches the network. The app pins `PROJ_NETWORK=OFF` before importing pyproj
and prints the switch back to you, and no other download path is touched.

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

A desktop run (`uv run flet run`) differs in two rows, over and above the timings that move
on every run: the desktop wheel bundles its own `proj.db`, which takes precedence over the
empty one, so the data directory points into site-packages and `CRS.from_epsg(4326)`
succeeds. Every coordinate is identical.
