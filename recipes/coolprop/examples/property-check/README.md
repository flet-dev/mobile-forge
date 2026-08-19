# CoolProp property check

A one-screen engineering-property calculator that proves its own arithmetic before you
trust it. Nine well-known states are computed by [CoolProp](https://coolprop.org/) on the
device and printed next to the published values they should reproduce, with the relative
error and a pass mark on every row. Everything is offline: the fluid data, the humid-air
model and the incompressible library are all inside the wheel's own extension, and the app
bundles no asset at all.

What it demonstrates:

- **Answers you can check.** Water's triple and critical points, its boiling point at
  1 atm and its density at 25 °C and 1 atm, nitrogen's normal boiling point, R134a's
  saturation pressure at 25 °C, CO₂'s triple-point pressure, and the saturation humidity
  ratio of moist air from
  [`HAPropsSI`](https://coolprop.org/fluid_properties/HumidAir.html) — each against ITS-90,
  IAPWS-95, NIST or ASHRAE, each row naming its source **and the state it belongs to** —
  a published density quoted at one pressure does not check a call made at another. All
  nine agree to 3e-5 relative or better; the app passes a row at 1e-4.
- **The out-of-range request that answers anyway.** Three deliberately invalid calls side
  by side. `HAPropsSI` at 100 K refuses and quotes its valid range; a saturation pressure
  above the critical point refuses and quotes the critical temperature; and
  `PropsSI("D", "T", 100000, "P", 101325, "Water")` returns a number, with no exception, at
  fifty times the `T_max` CoolProp reports for water on the line above it. That third row
  is the reason this example exists.
- **What a call actually costs on the device.** A
  [`Slider`](https://flet.dev/docs/controls/slider/) picks a point on the saturation dome
  for a fluid chosen with a
  [`SegmentedButton`](https://flet.dev/docs/controls/segmentedbutton/), and each move
  re-runs a 200-point sweep twice — once through
  [`PropsSI`](https://coolprop.org/coolprop/HighLevelAPI.html), which rebuilds its backend
  every call, and once through one reused
  [`AbstractState`](https://coolprop.org/coolprop/LowLevelAPI.html). Both microsecond
  figures are measured here and printed, because nothing off-device predicts them.
- **The import paid off the first frame.** `import CoolProp` parses the whole fluid
  database the extension carries, so it runs inside
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
  behind a spinner, ending with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. The footer prints what it cost in milliseconds and in resident memory.
- **Failing to text instead of to a crash screen.** Every section is built through one
  `render()` helper that catches whatever the section raises and draws the exception class
  and message in its place, so a device-only failure is legible on the screen rather than
  ending the session.

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
