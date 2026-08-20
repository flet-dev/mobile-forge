# kiwisolver layout solver

Three columns in a frame, described to
[kiwisolver](https://kiwisolver.readthedocs.io/en/latest/) as constraints rather than
arithmetic: start on the margin, keep a gutter between neighbours, close against the far
margin, never collapse. The solver decides the rest, and the boxes are drawn at exactly the
coordinates it returns. Drag the frame width and everything re-solves; flip a rule on and it
re-solves again with that rule in force.

What it demonstrates:

- **A layout written as relationships** — the app never computes a width. The required
  constraints leave two degrees of freedom, and
  [weak equal-width preferences](https://kiwisolver.readthedocs.io/en/latest/basis/basic_systems.html#managing-constraints-strength)
  take up the slack. Solved values go straight onto
  [`ft.Container.left`](https://flet.dev/docs/controls/container/) and `width` inside an
  [`ft.Stack`](https://flet.dev/docs/controls/stack/), so one solver unit is one Flet pixel.
- **Strength, doing something you can see** — *Sidebar is exactly 48* is required, so the weak
  equal-width preference gives way and the caption counts how many preferences yielded.
  *Content is twice the aside* is strong, so it outranks them but still bends when a required
  minimum needs the room: at the bottom of the slider that ratio falls to 1.6, because the
  aside has hit its required floor of 32.
- **A constraint added at runtime** —
  [`addConstraint`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.Solver.addConstraint)
  and
  [`removeConstraint`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.Solver.removeConstraint)
  on a solver that stays alive between events; each switch mutates the same tableau in a few
  microseconds. The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end), not
  `on_change`, so one drag re-solves once.
- **What an impossible system does** — turn on *Sidebar is exactly 48* and then *No column
  under 72* and the second is refused with
  [`UnsatisfiableConstraint`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.UnsatisfiableConstraint),
  proved from the two required constraints rather than found by trying values. The app puts
  the switch back, prints what the solver objected to, and rebuilds the tableau from scratch:
  a refusal does not undo itself, and in the opposite order the refused pin would otherwise
  stay in force and leave a 48-wide sidebar under its own required 72.
- **Building versus editing** — the benchmark button builds a 100-column system from scratch
  and then makes one edit to it, in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, ending in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs.

Press that button and the two numbers are more than an order of magnitude apart. Building the
tableau is badly super-linear, while editing a live one is cheap — which is the whole reason
to keep a solver around instead of recomputing a layout from scratch on every frame.

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
