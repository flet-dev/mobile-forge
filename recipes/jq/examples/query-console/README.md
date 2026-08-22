# jq query console

One screen with a JSON document, an editable jq program and its output. Six presets load a
program into the field; **Run** runs whatever is in the field. Each preset ships with a
hand-written Python function that computes the same answer, so the line under the output
reports both timings and whether the two agree — the app's numbers are checkable rather
than merely printed.

The document is generated in the app rather than bundled as a file, so the same build
produces the same 242,202 bytes on every device: 120 stations, 2,880 nested readings, plus
an `api_token` per station and a `-99` sentinel standing in for a missing temperature.

What it demonstrates:

- **The header line is the sharpest fact on the page.** It prints
  `builtins | length`, computed by the jq that is actually loaded. On a laptop, where pip
  resolves the PyPI wheel, that is **226**; a desktop replica of the mobile pairing —
  jq.py 1.11.0 linked to libjq 1.7.1 — reports **218**, and which of the two a phone agrees
  with is the first thing to read off the screen. The mobile wheel links `flet-libjq` 1.7.1
  while upstream's own wheels bundle jq 1.8.1, and the nine builtins on the desktop side of
  that gap are `trim/0`, `ltrim/0`, `rtrim/0`, `trimstr/1`, `toboolean/0`, `skip/2`,
  `add/1`, `have_decnum/0` and `have_literal_numbers/0`. `pow10/0` goes the other way, but
  gains nothing — it is a stub that errors on both sides. Type `trim` into the field and a
  phone should answer `jq: error: trim/0 is not defined`, which is what the replica answers.
  Type `2 | exp10` for the one difference that is not about versions at all: `100` on iOS and
  on the replica, `Error: exp10/0 not found at build time` on Android, where libjq was built
  without it.
- **Five transforms that are one string here and a dozen lines in Python.** Measured on an
  Apple M4 desktop, macOS 26.6, CPython 3.12.13, against jq.py 1.11.0 linked to libjq
  1.7.1 — the same pairing the mobile wheel ships, built the same way:

  | preset | jq lines | Python lines | jq ms | Python ms |
  | --- | --- | --- | --- | --- |
  | means | 5 | 12 | 2.98 | 1.05 |
  | sentinels | 4 | 13 | 14.40 | 2.43 |
  | tag index | 4 | 10 | 2.09 | 0.88 |
  | redact | 8 | 15 | 3.11 | 0.92 |
  | @csv | 5 | 17 | 1.99 | 0.97 |

  The Python column starts from the same JSON *text*, so both sides pay a parse. On that
  footing **jq is 2.1× to 5.9× slower**, which is the honest trade: you are buying the
  expression, not the speed. Working from an already-parsed Python object the twins are
  faster still — 0.01 to 1.54 ms — because they skip the parse that jq cannot skip, and
  those are the figures the app shows, since it hands the twin the document it already has.
- **The two that are genuinely awkward to hand-write.** `sentinels` is
  `paths(numbers) as $p | select(getpath($p) == -99)` — every number anywhere in the tree
  that equals the sentinel, reported by dotted path, without the query knowing the
  document's shape. `redact` is `walk(...)` with `with_entries` masking any key matching
  `token|secret|password` at any depth. Both twins are recursive walkers that must be
  taught the shape; the jq versions are not.
- **What a bad query does.** The `bad query` preset is `.stations[] | mean_temperature`.
  jq raises `ValueError`, the app catches it and prints the message in red:

  ```
  jq: error: mean_temperature/0 is not defined at <top-level>, line 1:
  .stations[] | mean_temperature
  jq: 1 compile error
  ```

  Compile errors and run-time errors are both plain `ValueError` — there is no `jq.Error`
  class to catch — and an unhandled exception in a Flet handler ends the session with a
  crash screen, which is why the whole run sits in one `try`.
- **Two places where jq and Python disagree, both handled in the twins rather than hidden.**
  jq's `add` is a plain left fold, while CPython's `sum` has used compensated (Neumaier)
  summation over floats since 3.12 — on one station's 19 readings that is 409.40000000000003
  against 409.4, and a mean of 21.547368421052635 against 21.54736842105263. The `means`
  twin uses `functools.reduce` so the comparison stays about the transform. And jq keeps a
  number's literal spelling: a maximum of `36.0` comes out of `@csv` as `36.0`, so the
  `@csv` twin renders cells with `json.dumps` rather than `str`.
- **Degrading instead of crashing.** The import of `jq` is guarded. Without the wheel the
  header turns red and names what the import raised, and every preset that has a twin still
  runs it, so the screen shows a real answer rather than nothing.

All the figures above are **desktop** measurements. The point of running the app is to
replace them with the device's own.

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

It also runs on the desktop with `uv run flet run`, which is the fastest way to try a query.
Remember that the desktop resolves upstream's PyPI wheel — a newer jq and a different build
of it — so the header says 226 builtins there whatever a phone says, and the timings it
prints are a preview of the app rather than of the device.
