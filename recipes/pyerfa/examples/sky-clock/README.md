# pyerfa sky clock

The device clock, read once and then spread across the five time scales astronomy actually
uses — UTC, UT1, TAI, TT and TDB — with the offset from UTC beside each one. Below that, five
bright stars taken from catalogue coordinates all the way to the altitude and azimuth they
occupy over the site you pick. Nothing is fetched: no ephemeris, no almanac, no clock server.

What it demonstrates:

- **That the calendar is a lookup table, not arithmetic.** TAI is UTC plus 37 seconds today
  only because [`erfa.dat`](https://pyerfa.readthedocs.io/en/latest/api/erfa.dat.html) finds
  that in a leap-second table compiled into `erfa/ufunc.abi3.so` — 42 entries ending at
  2017‑01‑01. TT then adds a fixed 32.184 s, and
  [`erfa.dtdb`](https://pyerfa.readthedocs.io/en/latest/api/erfa.dtdb.html) adds a
  millisecond-scale periodic term, which is why TDB and TT differ in the last digit. That term
  also has a piece that depends on where you are standing, so the site is passed in — but it
  spans under 4 µs across these five cities, and the time table stops at milliseconds. Expect
  the top half of the screen not to move when you change the site; the bottom half is where
  the site matters.
- **The one number an offline library cannot have.** UT1 is the Earth's actual rotation, and
  the difference from UTC is measured, not derived. The slider is that guess, and the `moved`
  column reports how far each star travels when you change it — a rotation about the celestial
  pole, so at the slider's own limit Polaris moves 0.15" while everything else moves 10" to
  13.5", scaling with cos(dec) rather than with the star.
- **The full catalogue-to-observed chain, vectorised.**
  [`apco13`](https://pyerfa.readthedocs.io/en/latest/api/erfa.apco13.html) builds the
  Earth-rotation and aberration context once, then
  [`atciq`](https://pyerfa.readthedocs.io/en/latest/api/erfa.atciq.html) applies proper motion,
  parallax, light deflection and annual aberration, and
  [`atioq`](https://pyerfa.readthedocs.io/en/latest/api/erfa.atioq.html) adds diurnal
  aberration and refraction. Every star goes through as one numpy array.
- **Compute off the UI thread** — each rebuild runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button disabled and a spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  drag rebuilds the sky once rather than once per pixel travelled.

The interesting reading is the gap between the two halves of the screen. UTC, TAI, TT and TDB
are exact to the millisecond from a table and a constant, and the slider does not touch them;
UT1 and every star position carry an error you cannot remove without an IERS bulletin, and the
slider shows you its whole range. Stars below the horizon sort to the bottom with a negative
altitude, which is how you know the geometry is real and not a lookup.

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
