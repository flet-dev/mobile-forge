# ruamel.yaml.clib YAML speed

One generated inventory document, loaded and re-emitted twice: once through the compiled
reader and emitter this wheel installs, once through the pure-Python ones that ship inside
`ruamel.yaml`. The table holds both timings and the ratio between them. Underneath, a small
commented config is re-emitted by both loaders, which is where the speed shows its price.

What it demonstrates:

- **Proving the accelerator is really there.** `ruamel.yaml` wraps its
  `import _ruamel_yaml` in a bare `except`, so an app whose wheel never arrived starts,
  runs and answers correctly — just slowly. The banner compares
  [`YAML(typ="safe")`](https://yaml.dev/doc/ruamel.yaml/api/)`.Parser` against
  `ruamel.yaml.parser.Parser` and names the class it found. Uninstall the accelerator and
  the banner turns red and the ratio column collapses to `1.0x`; both were checked by
  running the app against an environment without it.
- **Only some loaders are accelerated.** The C parser serves `typ="safe"`, `typ="unsafe"` and
  `typ="base"`; `typ="full"` is a dump-only mode whose `load` raises. Plain `YAML()` is the
  round-trip loader and has no compiled counterpart, so its timing is printed beside the
  table as the number that no wheel will improve.
- **What `typ="safe"` throws away.** The three panels are the same config on disk, after
  `YAML()`, and after `YAML(typ="safe")`. The round-trip loader keeps the comments and the
  key order and still renormalises the sequence indent; the safe loader returns plain dicts
  and lists, so its output has sorted keys, a flow sequence and no comments at all.
- **The fast path is not doing less work.** Each run compares the two results for equality
  and says so under the table, because a parser that skipped something would also look fast.
- **Compute off the UI thread.** Every measurement runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind
  a [`ProgressRing`](https://flet.dev/docs/controls/progressring/) with the button disabled,
  and the worker catches its own exceptions and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. It earns the spinner: a full run at the largest size took three seconds on
  desktop, most of it the pure-Python leg, and a phone is slower.

Each figure is the best of three runs, and the largest document is about 160 KB — big enough
that the ratio is stable and small enough to build in memory. Change the record count with
the [segmented button](https://flet.dev/docs/controls/segmentedbutton/) and the ratio barely
moves, which is the useful result: the C path is a constant factor, not a fixed saving.

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
