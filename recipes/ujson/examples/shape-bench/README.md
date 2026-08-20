# ujson vs json, on this device

One screen that answers the only question worth asking about a drop-in replacement for a
standard library module that is *already written in C*: on the phone in your hand, is it
faster, and does it change anything? Pick a document size and the app builds five payload
shapes — API records, floats, booleans, URLs, accented text — serialises and parses each one
with both libraries, and prints the per-call cost side by side. Underneath, eight drop-in
questions — five of which come back different from the stdlib and three the same — every cell
computed by a call made on the device rather than quoted.

What it demonstrates:

- **That the answer depends on the shape of your data, which is why there are five of them.**
  On desktop (CPython 3.12, arm64 Mac, 1,000 items per shape) the same code gives `dumps`
  2.93× on `floats`, 1.47× on `records`, 1.05× on `text` and **0.62× on `flags`**, the
  booleans —
  ujson losing to the stdlib on the cheapest possible values. A benchmark that picked one
  document could have told you either story. The verdict line under the table names the best
  and worst shape of the run, so the shape-dependence is the headline rather than a footnote.
- **The size column, and the one thing that makes ujson's output bigger.** ujson escapes `/`
  by default, so the `URLs` row comes out **+12.07%** against `json.dumps` compact on desktop
  while the other four stay within 0.02% of it. The `json` side is called with
  `separators=(",", ":")` precisely so that column means something: ujson has no spacing to
  remove, and against `json.dumps` defaults the difference would just be spaces.
- **A cross-check, so a wrong answer is visible rather than merely plausible.** Every shape is
  round-tripped both ways — `ujson.loads(ujson.dumps(doc))` against
  `json.loads(json.dumps(doc))`, and each library parsing the other's text — and the line
  under the table reads `identical objects, both directions, all shapes` or names the shapes
  that disagreed.
- **Eight drop-in questions, each one a real call.** What `dumps` returns, what happens to
  `"a/b"`, `float("nan")`, a 23-digit integer, a tuple dict key, a 25-digit `Decimal`, a
  `loads(..., object_hook=…)` call — and, last, what an existing `except json.JSONDecodeError`
  clause would do with ujson's decode error. That final row is the one to read first: it
  prints *misses it*, because `ujson.JSONDecodeError` subclasses `ValueError` directly. Every
  call sits inside a broad `except Exception`, because these raise plain `TypeError`,
  `ValueError` and `OverflowError` rather than anything library-shaped, and an unhandled
  exception in a Flet handler crashes the session.
- **Where the native module came from, on this device.** The header carries
  `ujson.__version__`, the Python version, `page.platform.value` and the basename of the
  module's origin, read through `__file__` first and `__spec__.origin` second — because Flet
  relocates native extensions out of site-packages and which attribute survives varies by
  platform. The second header line reports whether this runtime's `json` has its `_json` C
  accelerator, since a pure-Python stdlib would inflate every `json` column below for a reason
  that has nothing to do with ujson.
- **Compute off the UI thread, done the way Flet 0.86 requires.** The sweep runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. Its body is wrapped in `try/except` because `run_thread` discards whatever a worker
  raises, and it clears the table on the way out so the last run's timings cannot sit under
  this run's error. The re-entry guard is tested and set in the handler rather than in the
  worker, where it would not have taken effect before Flet pushed the control states. Note
  that the thread buys nothing but a handler that returns immediately: ujson holds the GIL for
  the whole call, as the [recipe README](../../README.md#threading) measures.
- **Restraint about what an example should probe.** ujson's encoder gives up at 1,024 nested
  containers, but demonstrating that on device means 1,024 frames of C stack on a worker
  thread — a worse thing to learn from an example than from a sentence, so it is documented in
  the [recipe README](../../README.md) and not called here. Only one shape is in memory at a
  time, too: each document is built inside the measurement and dropped on return. The
  5,000-item records document is 4.1 MB of Python objects on its own, but the cross-check
  holds five parsed trees and both serialised strings at once, which takes the peak for that
  one measurement to 32 MB of tracked allocations, and grows the process RSS by about 30 MB —
  all three desktop figures, CPython 3.14. Measure the RSS with `tracemalloc` off, by the way:
  its own per-allocation bookkeeping roughly doubles the number. That is the largest thing
  this app asks a phone for; the 1,000-item default peaks at 6.3 MB tracked and 6 MB of RSS.
- **A missing wheel reads as a message, not a crash.** The import sits in `try/except
  ImportError`, so an app built without the dependency shows what failed and what to add
  instead of dying on the first line.

Every document is generated from integer arithmetic with no randomness — no `random`, and no
`math.sin`, whose last bits are not guaranteed to match across platforms — so the same size
produces the same bytes on every install, and two devices can be compared directly. Nothing
is downloaded, nothing is written to disk and no asset is bundled.

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

It also runs on the desktop, where ujson installs from PyPI:

```bash
uv run flet run
```

`pyproject.toml` pins both `flet` and `ujson`, which is the combination that was verified.
`requires-python` stays at `>=3.10` — the floor both pins declare — so every split uv
resolves for is satisfiable, checked the way a consumer meets it, by copying that
`pyproject.toml` alone into an empty directory and running `uv lock` there.
