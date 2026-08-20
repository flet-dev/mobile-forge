# regex vs re

One screen. Fifteen patterns, each fed to the standard library's `re` and to `regex` in
the same breath, with both answers printed underneath — and then three measurements the
device has to make for itself, because they are the part a laptop cannot tell you.

Nothing is fetched, read from disk or bundled: every pattern and every subject is a
literal in `src/main.py`. The comparison rows run inline at startup: all fifteen through
both engines cost 14.1 ms of CPU on a desktop cp312 run with both pattern caches empty,
and 1.3 ms with them warm — nearly all of it first-time compilation.

## The table

Each row shows a verdict dot, the pattern, what `re` did with it and what `regex` did.
The `regex` half is **checked**, not merely displayed: every case carries the `repr` of
the answer it must produce, the dot is green only when they match, and the header counts
the agreements (`15/15 rows as expected` on a desktop run of flet 0.86.5 with regex
2026.5.9). A row that turns red is either a bumped `regex` that changed behaviour or a
device that disagrees with a laptop, and either is worth knowing.

Nothing is asserted about the `re` half. What `re` raises is a message that varies by
CPython version, so it is reported as observed. Eleven of the fifteen rows come back as
`re.error` (`bad escape \p`, `unknown extension ?V`, `look-behind requires fixed-width
pattern`, …), two as `TypeError` from a keyword `re` has no parameter for (`overlapped`,
`words`), one as `AttributeError` because `re.Match` has no `captures`, and one — the fuzzy
row — as a plain `None`, since `re` reads `{e<=2}` as literal text and simply fails to find
it. That last one is the most instructive failure on the screen: it is the only one that
does not announce itself. Note the class *name* moves with the interpreter: those eleven
print as `re.error` on CPython 3.12 and as `PatternError` from 3.13, which is the same
class under the name it was given in 3.13 — 3.14 is what this example's own venv runs, so
that is what you will see on a desktop.

The fifteen are the five headline features (property classes, fuzzy matching,
overlapping matches, variable-width lookbehind, set operations), `\X` for grapheme
clusters, and a tail of things that are individually small and collectively the reason
people migrate: repeated-group `captures()`, branch resets, POSIX leftmost-longest
alternation, full case folding (`ß` against `SS`), named lists, and recursion into the
whole pattern.

Row 9 is the odd one out and is there on purpose. It repeats row 8's set intersection
**without** the `(?V1)` flag, and it is checked against the *wrong* answer —
`['ΑΒΓ', 'αβγ', 'ABC']` where row 8 gives `['ΑΒΓ']` — because that is what `regex`
really returns. In `V0`, which is the default, `&&` inside a character class is just two
more characters in the set, so an intersection quietly becomes a union. Green on that
row means the trap is still live.

## The measurements

`measure this device` runs three probes in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and
prints their lines. On desktop cp312 the whole button takes about 1.5 seconds.

- **Catastrophic backtracking.** `(a+)+b` against a run of `a` with no `b` to find,
  timed in both engines at growing lengths. On a laptop, `re` roughly quadruples every
  two characters — one run gave 0.36 / 1.43 / 5.78 / 23.74 / 94.12 / 373.72 / 1,563.30
  ms from n=14 to n=26 — while `regex` stayed between 0.005 and 0.018 ms throughout, a
  factor of 58× rising to 86,850×. The ladder stops *before* the rung whose predicted
  cost would break a 1.5 s budget rather than after it, so a slow device simply reports
  fewer rungs. `regex` is not immune to this class of pattern in general,
  only to this one; the guard for a pattern you did not write is `timeout=`.
- **A CPU-busy sibling thread.** The same `findall` over a 13,800-character corpus with
  200 matches, run alone and then run again with a second thread burning CPU, three
  ways: `re`, `regex` at its default, and `regex` with `concurrent=False`. `regex`
  releases the GIL for a `str` subject unless told not to, and reacquiring it costs a
  scheduler handoff each time, so the middle row is the one that collapses. On an idle
  laptop with 1,000 matches the collapse is about 2,500×; the busier laptop these lines
  were captured on gave 34×, 332× and 678× across consecutive runs, against 0.5–2.1× for
  the other two rows. **The multiplier is noisy; on an otherwise idle device the ordering
  is not** — a run on a machine at load average 44 inverted even the `alone` column, so
  read the three rows only when nothing else is competing. `regex` reacquires the GIL
  around roughly every match, which is why the cost scales with the switch interval; see
  [Threading](../../README.md#threading) for that evidence in full.
- **Unicode tables.** All 1,112,064 code points — everything but the surrogate range —
  are offered to both `regex`'s `\p{L}` and the runtime's `unicodedata.category()`. On CPython 3.12
  (`unicodedata` 15.0.0) 9,568 come back as letters that `unicodedata` calls unassigned,
  including U+088F, U+0C5C and U+0CDC; on CPython 3.14 (`unicodedata` 16.0.0) 4,644 do.
  **Zero go the other way**, which is the signature of one table being ahead rather than
  two tables disagreeing: `regex` compiles in its own, at Unicode 17.0.0 for this
  release. The scan takes 300–450 ms on a laptop, and printing its own elapsed time is
  how you find out what it costs on a phone.

## The playground

Two fields, a `(?V1)` checkbox and a `findall` button. **`regex` runs the pattern;
`re` only compiles it**, and the asymmetry is the point rather than a shortcut.

A Flet `on_click` handler runs directly on the event loop, and `re` has no timeout, so
a match it has started cannot be bounded. Typing `(a+)+b` — the very pattern the
measurement above teaches — with 30 `a`s into an unguarded version of this handler
froze the session for **56.9 s, during which the loop ticked zero times**, on desktop
cp312. A `run_thread` worker is no escape either: `re` holds the GIL for the whole
match, and with one running in a sibling thread the main thread got **0 wakeups in
17.8 s** against an idle rate of ~143/s. Nor does capping the subject help —
`((a+)+)+b` reaches 283 ms at 14 characters and `(((a+)+)+)+b` 66 ms at 10, so the
length that would be safe is shorter than any usable input.

`regex.findall` is called with `timeout=1.0`, which is a genuine per-call CPU budget:
raising the number of expensive restart positions from 1 to 8 left CPU at exactly
1.00 s every time, so the budget is spent on the call rather than refreshed per match
attempt. Note it is CPU time, not wall, so the wall-clock cost is whatever share of a
core the app is getting: those 1.00 s of CPU took 3.8–4.8 s on one loaded run here and
21.9 s on a heavily loaded one. `concurrent=False` for the reason the middle measurement
gives.

Compiling is safe to do on the event loop, which is why the `re` column still says
something useful: the worst adversarial pattern tried — 150 nested groups, 200
capture groups, a 2,000-branch alternation, a 1,500-character class — compiled in
147 ms or less in either engine. And compiling is the informative half anyway: twelve of
the fifteen patterns above are refused by `re` at compile time — one more than the eleven
`re.error` rows in the table, because row 14's `\L<words>` never reaches `re`'s compiler
there, `re.findall` having rejected the `words=` keyword first.

The fields set `autocorrect=False`, `enable_suggestions=False` and
`capitalization=NONE`, without which a phone keyboard helpfully rewrites your pattern
as you type it.

## Shape

The header prints `regex.__version__`, the Python version, the platform and machine, the
row count, and the extension's `__file__`. That last one is read with
`getattr(regex._regex, "__file__", None)` and falls back to `no __file__`: Flet
relocates ABI-tagged extensions out of site-packages on both platforms, and on Android
the moved module may have no `__file__` at all — written plainly that would be an
`AttributeError` raised while building the page, which is a crash screen rather than a
line of text.

Every probe is wrapped. The comparison rows each catch `Exception` and print the
exception class and message into the row, so a device-only failure names itself instead
of taking the screen down; the measurement worker does the same, because
`page.run_thread` never retrieves its worker's future and an exception there would
otherwise be entirely silent. The worker ends with an explicit `page.update()`, since
auto-update does not reach a background thread.

Setting `run.disabled = True` is **not** what stops a second tap, and it was measured
not to: dispatching two `click` events back to back against a real `Session` started
two workers, because `disabled` only reaches the client after the handler returns and
the patch round-trips, and a tap already in flight arrives anyway. Two workers
measuring thread contention would be measuring each other. The guard is therefore a
`threading.Event` checked at the top of the handler; with it, the same double
dispatch starts one worker.

`requires-python` is the `>=3.10` that `flet create` writes, because both pins tolerate
it: regex 2026.5.9 and flet 0.86.5 both declare `Requires-Python: >=3.10`, and regex
ships PyPI wheels from cp310 up. `uv lock` on this `pyproject.toml` alone, in an empty
directory, resolves 56 packages.

## Try it

The app runs on the desktop too — `regex` is in `[project] dependencies` and PyPI has a
wheel for every desktop host — so `uv run flet run` shows the same fifteen rows with
your development machine's numbers underneath.

[Build](https://flet.dev/docs/publish/) it, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
