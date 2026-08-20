# pyxirr cash flow desk

Four schedules of dated cash flows, each solved for the rate at which it breaks even.
The report gives the XIRR, the XNPV *at* that rate — which should be zero, because that
is the definition — how many times the amounts change sign, and every root the solver
can be made to return. The coloured strip below is the sign of XNPV across the same
window the guess slider covers, so every colour boundary in it is a break-even rate.

What it demonstrates:

- **Irregular dated cash flows, without a `datetime` in sight** —
  [`xirr`](https://anexen.github.io/pyxirr/functions.html#xirr) takes dates and amounts
  as two parallel sequences, and the dates here are plain zero-padded ISO strings that
  the Rust side parses. Padding is not optional: `"2022-3-14"` is rejected.
- **Checking the answer against its own definition** —
  [`xnpv`](https://anexen.github.io/pyxirr/functions.html#xnpv) at the returned rate is
  reported next to it. On the rental flat that residual is about `+4e-04` against
  556,800 moved, which is a root-finder's zero rather than an algebraic one.
- **The two different ways there is no answer** — a schedule with no sign change raises
  [`InvalidPaymentsError`](https://anexen.github.io/pyxirr/functions.html#exceptions)
  (research grant), while a curve that never reaches zero returns `None` without raising
  at all (clawback). Only the first is what `silent=True` suppresses, and a third failure
  this app cannot stage — a malformed date string — raises `ValueError` through it.
- **That `guess` chooses the answer when there is more than one** — the mine site has
  three roots. Drag the slider or press **Random guess** and watch the reported XIRR jump
  between −63.31%, 0.00% and +168.69%. The **roots found** line is not a brute-force
  search: `xnpv` prices the whole window in one broadcast call, and
  [`zero_crossing_points`](https://github.com/Anexen/pyxirr#multiple-irr-problem) on that
  curve brackets each root for `xirr` to be aimed into.
- **Compute off the UI thread** — every solve runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
  with the controls disabled and a spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a
  background thread needs. The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end)
  rather than [`on_change`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change),
  so one drag solves once instead of once per step.

The reported solve time is there to be dismissed: a few microseconds, and the answer still
needs checking. Count the colour boundaries on the strip against the sign changes in the
report and the two numbers come apart — the clawback schedule changes sign twice and has no
root at all, while the mine site changes sign three times and has three. Sign changes only
bound how many rates can break even, which is all the **conventional** row is asserting:
exactly one change, so at most one rate, so nothing for `guess` to choose between.

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
