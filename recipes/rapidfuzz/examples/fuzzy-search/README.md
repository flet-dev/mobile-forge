# rapidfuzz fuzzy search

A search box over 4,000 strings that exist only in code, where every answer on screen is computed
a second way before it is shown. Type a misspelling, hit Enter, and the app ranks the corpus with
[`process.extract`](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html#rapidfuzz.process.extract),
then checks that ranking against a hand-written Python loop and against
[`process.cdist`](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html#rapidfuzz.process.cdist)
plus `numpy.argmax`.

The corpus is the full 20 × 20 × 10 cross product of three word lists — `North Haven Junction`,
`Stone Bridge Bay`, and 3,998 more — shuffled with a fixed seed, so every device searches the
same list. Nothing is downloaded, nothing is bundled and nothing is written to disk. It is
deliberately Title Cased, because the default query is lowercase.

What it demonstrates:

- **The six scorers disagreeing about the same query.** The table scores the query against the
  whole corpus once per scorer and shows which string each one thinks is the best match. The
  default query `junctn havn nrth` — misspelled *and* reordered — has `token_sort_ratio` and
  `token_set_ratio` finding `North Haven Junction` at 88.9 and `WRatio` finding it at 84.4, while
  `ratio` returns `Stone Haven Point`, `partial_ratio` returns `New Haven Point` and
  `Levenshtein.normalized_similarity` returns `Queens Haven Green`. No error, no warning; three
  of six scorers simply answer a different question. Try `stone brige` for the reverse case,
  where `ratio` and `Levenshtein` are right and `WRatio` — `process.extract`'s own default —
  returns `Stone Thorpe Springs` with its whole top 8 tied at 85.5.
- **What the processor is for.** The last column of the table rescores the same pair with no
  `processor=`, so the cost of a lowercase query against Title Cased data is a number on the
  screen rather than a rule to trust (88.9 → 72.2 for the default query). The line at the bottom
  is the pure case: `fuzz.ratio('CAFE', 'cafe')` is `0.0`, and `100.0` with
  [`processor=default_process`](https://rapidfuzz.github.io/RapidFuzz/Usage/utils.html#rapidfuzz.utils.default_process).
- **What `process.extract` is worth, honestly.** It is timed against `python_top`, a loop that
  does exactly what extract does — process the query once, each choice once — and the app prints
  both times, the ratio, and whether the two produced the *same top 8*. Measured on desktop that
  ratio ranges from 4.9× with `ratio` down to 1.6–1.7× with `token_set_ratio` and `WRatio`,
  because what extract removes is Python call overhead and the heavier the scorer the less of the
  total that is. A loop handed a pre-processed corpus would not be the same workload, which is why
  this one is not.
- **A third, independent answer.** `process.cdist([query], CORPUS, …)` returns a `(1, 4000)`
  `float32` array — 16,000 bytes, printed — and its `argmax` is compared by name with
  `extract`'s top hit, with an **AGREE / DISAGREE** verdict. This is also the reason `numpy` is
  in the dependency list: `cdist` and `cpdist` `import numpy` inside their own bodies, and a bare
  `rapidfuzz` does not install it, so an app that skips the dependency raises
  `ModuleNotFoundError` from a handler rather than failing at build time.
- **Whether the compiled modules actually loaded.** The header line says `COMPILED` or
  `PURE-PYTHON` from `not fuzz.ratio.__module__.endswith("_py")`, and prints the module names
  behind `fuzz.ratio` and `process.extract` next to it. That check exists because rapidfuzz falls
  back to a pure-Python implementation *silently* when a native module will not load — same API,
  same answers, tens of times slower — so a working screen is not by itself evidence that the
  wheel is doing its job. On an **Android** x86_64 emulator whose CPU reports AVX2, expect
  `rapidfuzz.fuzz_cpp_avx2` there rather than `rapidfuzz.fuzz_cpp` — that slice ships the AVX2
  modules and a phone does not, so it is genuinely a different binary; the iOS x86_64 simulator
  reads the same as a device. The `_py` check stays correct on all of them.
- **Where the extension really lives on the device.** The second header line prints
  `__spec__.origin` for whichever module `fuzz.ratio` came from, which is where you see Flet's
  relocation of native modules — into `jniLibs` on Android, into a framework in the bundle on
  iOS — instead of guessing at it.

The work runs in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread),
dispatched from the field's `on_submit` and the Dropdown's
[`on_select`](https://flet.dev/docs/controls/dropdown/) so one gesture means one run. That keeps
the handler from blocking, not the interpreter: `process.extract` holds the GIL while it runs, so
the thread buys responsiveness here only because one search over 4,000 names costs about 4 ms. On
a corpus large enough to matter it would stall the UI from the worker thread just as surely as
from the handler — the recipe README's [Threading](../../README.md#threading) section measures
that, and names `process.cdist` as the one call that does release the GIL. Disabling the inputs
is not on its own enough of a guard — it only queues the new state for the client, and
`run_thread` submits to a shared pool — so the handler reads `disabled` back before dispatching.

`on_submit` rather than `on_change` is a choice this screen makes, not a limit of the library: at
this corpus size `process.extract` fits inside a frame budget, so searching per keystroke from
`on_change` is fine provided the work still goes off the UI thread and the disable-the-inputs
guard is replaced by a stale-run guard that discards a result whose query is no longer the one in
the field. `extract_iter(..., score_cutoff=…)` is the cheaper per-keystroke call; the recipe
README's [Things to know](../../README.md#things-to-know) has the figures. This example keeps the
submit gesture so that one run means one comparable set of numbers on screen.
The worker body is wrapped in `try/except`, blanks every computed row before reporting a failure
in the field's `error`, and ends in an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because `run_thread`
discards whatever a worker raises and auto-update does not reach background threads. The broad
`except` is not decoration: rapidfuzz signals bad input with plain builtin `TypeError`s, and an
unhandled exception in a Flet handler produces a crash screen.

The table sits inside a horizontally scrolling `ft.Row`. Four columns of place names do not fit a
phone, and a non-scrolling `Row` wider than the viewport paints Flutter's *OVERFLOWED* stripes
instead of scrolling.

`requires-python` is `>=3.11`, not the `>=3.10` that `flet create` writes: `numpy==2.4.6` is the
newest numpy on Flet's mobile index and its own floor is `>=3.11`, so `>=3.10` makes the lowest
split unsatisfiable and `flet build` fails outright. Checked the way a consumer meets it, by
copying this `pyproject.toml` alone into an empty directory and running `uv lock` there.

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
