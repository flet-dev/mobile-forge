# regex vs re

Fifteen patterns, each fed to the standard library's `re` and to
[`regex`](https://github.com/mrabarnett/mrab-regex) in the same breath, with both answers
printed underneath — and then three measurements the device has to make for itself, because
they are the part a laptop cannot tell you. Nothing is fetched, read from disk or bundled:
every pattern and every subject is a literal in `src/patterns.py`.

What it demonstrates:

- **What `re` cannot answer.** The five headline features (property classes, fuzzy matching,
  overlapping matches, variable-width lookbehind, set operations),
  [`\X`](https://github.com/mrabarnett/mrab-regex#matching-a-single-grapheme-x) for grapheme
  clusters, and a tail of smaller wins: repeated-group `captures()`, branch resets, POSIX
  leftmost-longest alternation, full case folding (`ß` against `SS`), named lists, and
  recursion into the whole pattern. Eleven of the fifteen come back from `re` as a compile
  error, two as a `TypeError` from a keyword it has no parameter for, one as an
  `AttributeError`, and one — the fuzzy row — as a plain `None`, which is the most instructive
  failure on the screen because it is the only one that does not announce itself. That class
  name moves with the interpreter: those eleven print as `re.error` on CPython 3.12 and as
  `PatternError` from 3.13.
- **A checked table rather than a described one.** Every case carries the `repr` of the answer
  `regex` must produce, the dot is green only when they match, and the header counts the
  agreements. Nothing is asserted about the `re` half, whose message varies by CPython version.
  **Row 9 is checked against the answer that looks wrong** — it repeats row 8's set
  intersection *without* `(?V1)` and expects `['ΑΒΓ', 'αβγ', 'ABC']` where row 8 gives
  `['ΑΒΓ']`, because in `V0` a `&&` inside a character class is just two more characters in the
  set. Green on that row means the trap is still live.
- **Three numbers only a device can give you.** `measure this device` runs them in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread): the
  `(a+)+b` blowup ladder, which `re` climbs exponentially and `regex` does not (the ladder
  stops *before* the rung whose predicted cost would break its 1.5 s budget, so a slow device
  reports fewer rungs rather than freezing); the same `findall` run alone and then beside a
  CPU-burning sibling thread, three ways, where the `regex` default collapses because it
  released the GIL and pays a scheduler handoff to get it back; and a sweep of all 1,112,064
  code points through both `\p{L}` and `unicodedata.category()`, which on CPython 3.12 finds
  9,568 letters the runtime calls unassigned and zero the other way round.
- **Handing an untrusted pattern to the right engine.** The playground compiles the typed
  pattern with `re` and *runs* it only with `regex`, at `timeout=1.0, concurrent=False`.
  Compiling is safe on the event loop — the worst adversarial pattern tried here compiled in
  147 ms — but running is not: typing `(a+)+b` with 30 `a`s into an unguarded `re` handler
  froze a desktop session for **56.9 s, during which the loop ticked zero times**. A
  `run_thread` worker is no escape, since `re` holds the GIL for the whole match.

The header prints the extension's `__file__`, read as `getattr(regex._regex, "__file__", None)`
with a fallback, because Flet relocates ABI-tagged extensions out of site-packages and on
Android the moved module may have no `__file__` at all. Run it on a phone as well as a laptop:
the table will agree, and the three measurements under it will not.

## Try it

The app runs on the desktop too, so `uv run flet run` shows the same fifteen rows with your
development machine's numbers underneath. [Build](https://flet.dev/docs/publish/) it, then
install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
