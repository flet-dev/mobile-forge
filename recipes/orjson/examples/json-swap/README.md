# orjson vs json

One screen that answers "what actually changes if I swap `import json` for `import orjson`?"
on the device in front of you. A slider picks the document size — 1 to 2,000 records of a
deterministic, API-shaped payload. Let it go and the app serialises and parses that document
with both libraries, fills a table with the per-call cost and the ratio, and states what the
swap is worth in absolute terms. Below that, a second table walks eight cases where the swap
is not transparent, every cell computed on the device rather than quoted.

What it demonstrates:

- **The speedup, and how little it is worth at phone sizes.** The table shows `dumps` and
  `loads` in **microseconds** for both libraries with the ratio beside them, and the verdict
  line says how much each call saved against a 16.7 ms frame at 60 Hz. At the low end of the
  slider that reads as a saving of a few microseconds — which is why compact output and type
  coverage, not speed, are the reasons to put orjson on a phone.
- **Two independent cross-checks, so a wrong answer is visible rather than merely
  plausible.** `orjson.loads(orjson.dumps(doc))` must equal `json.loads(json.dumps(doc))`,
  printed as `identical objects` or `DIFFERENT OBJECTS`; and `orjson.dumps(doc)` must be
  byte-for-byte `json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()`,
  printed as `identical bytes` or `DIFFERENT BYTES`. The second is what makes the size row
  meaningful: it proves the smaller output is spacing and `\uXXXX` escaping rather than a
  different encoding.
- **The size difference, both columns shown.** The `output B` row prints the bytes each
  library produced and the percentage between them, so the "about 12% smaller" claim is
  something you can divide yourself rather than take on trust.
- **The eight cases, each one a real call.** `{1: "a"}`, the same dict with
  `OPT_NON_STR_KEYS`, `float("nan")` out and `"NaN"` back in, a `datetime`, `2**64` out and a
  23-digit integer back in, and `"café"` — with what each library did, or the exception it
  raised, in its own column. The most dangerous row is the 23-digit integer: `json` returns
  it exactly and orjson returns `1.2345678901234568e+22`, a float, with no error anywhere.
  Every one of those calls sits inside a broad `except Exception`, because they raise plain
  `TypeError`/`ValueError` rather than anything library-shaped, and an unhandled exception in
  a Flet handler crashes the session.
- **The `bytes`-versus-`str` difference as a computed value, not prose.** The second header
  line reads `orjson.dumps() returns bytes, json.dumps() returns str` because it asks
  `type(...).__name__` of both, so it cannot go stale. It ends with whether this runtime's
  `json` has its C speedups (`_json` in `sys.modules`), because a pure-Python fallback would
  inflate every `json` column below for a reason that has nothing to do with orjson.
- **Where the native module came from, on this device.** The first header line carries
  `orjson.__version__`, the Python version, `page.platform.value` and the basename of the
  native module's origin. That last field is read through `__file__` first and
  `__spec__.origin` second, because Flet relocates native extensions out of site-packages and
  which attribute survives varies by platform and by package — on Android it can be missing
  altogether.
- **Compute off the UI thread** — the run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. Its body is wrapped in `try/except` because `run_thread` discards anything a worker
  raises, and it clears the table on the way out so the last run's timings cannot sit under
  this run's error. The slider's `disabled` flag is tested and set in the handler rather than
  in the worker, where it would not have taken effect before Flet pushed the control states.
  The thread buys nothing but a handler that returns immediately: orjson holds the GIL for the
  whole of a call, so no other Python in the app runs while one is in flight.

The document is generated in code from the slider position with no randomness, so the same
position produces the same bytes on every install and two devices can be compared directly.
Nothing is downloaded, nothing is written to disk and no asset is bundled. `src/swap.py`
owns the document, the timing harness and the eight cases; `src/main.py` is the screen.

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
