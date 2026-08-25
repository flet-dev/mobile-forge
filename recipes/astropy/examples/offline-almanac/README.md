# offline-almanac

A one-screen almanac that computes real astronomy with the network switched off. It reports
where the Sun, the Moon and M31 are for a date you pick with the slider, and prints five
self-checks whose answers are known in advance. Drag the slider out to roughly **+12
months** and the banner turns red: that is where the Earth-orientation table bundled with
the wheels runs out, and astropy starts silently reusing its last value.

`src/almanac.py` holds the astronomy and returns plain strings and numbers; `src/main.py` is
the UI and the threading. No function in `almanac.py` touches a control, so everything on
screen can be reproduced from a REPL.

What it demonstrates:

- **The import-time preamble.** Before `import astropy`, `almanac.py` creates two directories
  under [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  and [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
  and points `ASTROPY_CONFIG_DIR` / `ASTROPY_CACHE_DIR` at them. astropy resolves its config
  directory while the import is still running, so getting this wrong crashes before any
  astronomy happens. The `os.makedirs` is the half that matters — astropy 8 ignores a
  directory that does not exist yet.
- **Both network kill switches.** `iers.conf.auto_download = False` and
  `astropy.utils.data.conf.allow_internet = False` are set at import, and the header prints
  both so the screen states its own configuration. Every value below them is computed from
  files that shipped inside the wheels.
- **What "offline" costs, made visible.** The banner distinguishes *measured* Earth
  orientation from *predicted*, counts down the days of table left, and once the date runs
  past the end says plainly what freezes and how much sky error it is worth. The `UT1-UTC`
  line stops changing at the same moment, so the claim is visible rather than asserted. The
  leap-second table's own expiry is printed next to `TAI-UTC`, and is read *after* the first
  conversion on purpose — read at startup it still reports pyerfa's compiled-in 2017 date.
- **Five self-checks against outside references.** 1 pc in light-years, recomputed in the app
  from the exact defining values of the
  [astronomical unit and the light-year](https://docs.astropy.org/en/stable/units/standard_units.html)
  rather than looked up; the 2016 leap second parsed as `23:59:60` and converted to TAI; four
  ICRS→galactic transforms against published galactic coordinates, with the pass threshold
  set to the precision those coordinates are quoted at; an exact
  [FITS](https://docs.astropy.org/en/stable/io/fits/) round trip through app storage; and a
  deliberate `1 m + 1 s`, caught and shown rather than allowed to crash the session.
- **The Android `extract_packages` entry.** `pyproject.toml` lists **both** `astropy` and
  `astropy_iers_data`. Drop the second one and the app still launches, the self-checks still
  pass, and only the `UT1-UTC` line and the alt/az turn into a `NotADirectoryError` — which
  is exactly why it is worth demonstrating.
- **Recomputation off the UI thread.** The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) rather
  than per pixel, the work runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), and
  each worker ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that auto-update
  does not do for you. The guards are in `main.py`, not in the astronomy: `run_thread` drops
  the worker's future, so an unguarded raise would leave a panel reading "running…" forever
  with nothing logged anywhere.

Four astropy APIs are named on screen as deliberately *not* attempted, because each is a
download with nothing bundled behind it: `EarthLocation.of_site`, `get_site_names`,
`SkyCoord.from_name` and `EarthLocation.of_address`. The observing site is a hard-coded
`EarthLocation` instead, and the Sun and Moon come from ERFA's built-in ephemeris.

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
