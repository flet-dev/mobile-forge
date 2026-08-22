# regex

[`regex`](https://github.com/mrabarnett/mrab-regex) is a drop-in replacement for the standard
library's [`re`](https://docs.python.org/3/library/re.html) with a much larger pattern
language. Every `re` pattern is a `regex` pattern; the reason to add a compiled extension to a
phone app is the set of things `re` answers with an exception. The five that come up most in
mobile text handling are Unicode property classes (`\p{Greek}`, `\p{Lu}`),
[fuzzy matching](https://github.com/mrabarnett/mrab-regex#approximate-fuzzy-matching-hg-issue-12-hg-issue-41-hg-issue-109)
with an explicit error budget (`{e<=2}`),
[overlapping matches](https://github.com/mrabarnett/mrab-regex#overlapped-argument-for-regexfindall-and-regexfinditer),
[variable-width lookbehind](https://github.com/mrabarnett/mrab-regex#variable-length-lookbehind),
and [set operations](https://github.com/mrabarnett/mrab-regex#set-operators) inside a character
class (`--`, `&&`).
[`\X`](https://github.com/mrabarnett/mrab-regex#matching-a-single-grapheme-x) — one match per
user-perceived character, so an emoji family or a flag counts as one — is the sixth, and on a
phone it is arguably the first.

Two things about this package are not obvious from its documentation and shape the code you
write against it. **It releases the GIL while matching a `str`, by default**, which costs
nothing while your app is single-threaded and turns into a several-hundred-fold *slowdown* the
moment a second thread is busy — see [Threading](#threading). And **its Unicode tables are its
own**, compiled into the extension and ahead of the interpreter's, which is why `\p{L}` and
`str.isalpha()` disagree about thousands of characters — see
[Unicode tables](#unicode-tables).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "regex",
]
```

Keep the entry in top-level `[project] dependencies` rather than a `[tool.flet.android]` or
`[tool.flet.ios]` table: only that keeps the package importable under `flet run` on your
desktop, and the desktop half is where you will do most of the pattern writing.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`vs-re`](examples/vs-re) — fifteen patterns run through both engines side by side, plus
  three measurements taken on the device itself.

## Usage in a Flet app

Import it, call it, put the answer in a control:

```python
import regex

hits = regex.findall(r"(?V1)\p{L}+", subject, concurrent=False, timeout=1.0)
view = ft.Text(", ".join(hits))
```

Three keywords in one line, and each of them is there for a reason:

- **`(?V1)`** turns on the newer pattern semantics. Without it a `--` or `&&` inside a
  character class silently means something else rather than raising — see
  [Things to know](#things-to-know). It costs nothing on a pattern that uses neither, so
  writing it habitually is cheaper than remembering when it matters.
- **`concurrent=False`** stops the GIL release. The default is on for any `str` subject, and
  it is a several-hundred-fold *slowdown* rather than a speed-up as soon as a second thread
  is running — see [Threading](#threading).
- **`timeout=`** is the only guard against a pattern you did not write. `re` has no
  equivalent, and a runaway match on the Flet event loop is an app frozen until the user
  kills it — see [Things to know](#things-to-know).

Results are plain Python: `findall` gives `list[str]` (or a list of tuples once the pattern has
groups), `match` and `search` give a match object whose `group()` is a `str`. Nothing needs
converting before it goes into [`ft.Text`](https://flet.dev/docs/controls/text/), a
[`ft.ListView`](https://flet.dev/docs/controls/listview/) of them, or back into a
[`ft.TextField`](https://flet.dev/docs/controls/textfield/).

### Threading

**`regex` releases the GIL while matching, and unless you stop it that is a trap rather than a
gift.** `re` holds the GIL for the whole of a match; `regex` does not. The switch is the
`concurrent` keyword, taken by every matching function (`search`, `match`, `findall`,
`finditer`, `split`, `sub` and their variants, plus `scanner` on a compiled pattern) and
[documented upstream](https://github.com/mrabarnett/mrab-regex#multithreading) only as a way to
*force* release. Its default is not "off": `_regex.c` sets `state->is_multithreaded` to
`PyUnicode_Check(string) || PyBytes_Check(string)` when `concurrent` is left alone, so every
ordinary `str` subject gets GIL release without asking.

The cost is that the engine *reacquires* the GIL constantly — around allocation, around
deallocation, and around every cancel check — and each reacquisition waits out a scheduler
handoff when another thread wants the GIL too. Measured on a desktop CPython 3.12 on an
Apple-Silicon laptop, with a 69,000-character corpus and `\w+@\w+\.\w+` (1,000 matches),
against one CPU-busy sibling thread:

| call | alone | with a busy thread | slowdown |
| --- | --- | --- | --- |
| `re.findall` | 0.76 ms | 0.81 ms | 1.1× |
| `regex.findall` (default) | 1.86 ms | 4,649 ms | 2,494× |
| `regex.findall(..., concurrent=True)` | 1.89 ms | 4,690 ms | 2,488× |
| `regex.findall(..., concurrent=False)` | 1.86 ms | 2.26 ms | 1.2× |

The same shape on cp313 and cp314: 1,962× / 1.8× and 1,570× / 1.1×. **The magnitude is
scheduler-dependent and moves a lot with machine load** — repeating the measurement on a
heavily loaded laptop gave 19× to 42× instead of thousands — so treat the multiplier as
indicative and the direction as solid. What pins the mechanism is its proportionality to the
GIL switch interval: 500 matches beside a busy thread took 3,066 ms at the default
`sys.setswitchinterval(0.005)`, 432 ms at 0.001 and 65 ms at 0.0002, i.e. roughly one GIL round
trip per match. None of these are device numbers; taking them on the device is what the
[`vs-re`](examples/vs-re) example is for.

**In a Flet app that second thread is not hypothetical.**
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) submits to a
shared `ThreadPoolExecutor`, so two taps in quick succession genuinely overlap, and a scan that
took a millisecond in testing becomes seconds. Pass `concurrent=False` on anything you call
from a `run_thread` worker, or on a
[`Pattern`](https://docs.python.org/3/library/re.html#re-objects) you reuse across the app.
There is no module-level default to set — `concurrent` is per call.

**`concurrent=True` buys nothing over the default**, since the default is already on for `str`
and `bytes`. It is only meaningful for a subject that is neither — a `memoryview` or an
`array`, which `regex` accepts through the buffer protocol and where it cannot prove the data
is immutable, and which do not release at the default.

Scanning a few kilobytes costs well under a millisecond and belongs on the UI thread; the case
for a background thread is a large subject, or a pattern you did not write. Whatever you do
move, wrap the worker body in `try/except` — `run_thread` never retrieves the worker's future,
so an exception there is silent — and end it with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach a background thread.

**Nothing in the package starts a thread of its own.** `pthread_create` is not among the
undefined symbols of any slice, and the locks it does take — a `threading.RLock` around its own
pattern cache, a `PyThread` lock for the match states behind `finditer` and `splititer` — are
its own bookkeeping.

### Unicode tables

**`regex` compiles its own Unicode tables into the extension, and they are ahead of the
interpreter's.** That is what makes `\p{L}`, `\p{Greek}` and `\X` work without touching
[`unicodedata`](https://docs.python.org/3/library/unicodedata.html) — and it is also why they
disagree with it. Offering all 1,112,064 code points to both: on CPython 3.12, whose
`unicodedata` is 15.0.0, there are **9,568 code points that `\p{L}` matches and
`unicodedata.category()` calls `Cn`**, unassigned; on CPython 3.14 (`unicodedata` 16.0.0) there
are 4,644. **Zero go the other way**, which is the signature of one table simply being ahead of
the other rather than two tables disagreeing. U+088F, U+0C5C and U+0CDC are in both lists.
`\p{L}` against `str.isalpha()` gives exactly the same figures.

So pick one authority per field and stay with it. `\p{L}` if you mean "a letter in the newest
Unicode release"; `str.isalpha()` or `unicodedata` if you mean "a letter this interpreter
agrees is one". Validating input with one and rendering with the other is how a character gets
accepted and then displayed as a box.

**There is no way to read the table version at runtime.** `RE_UNICODE_VERSION` in the sdist's
`src/_regex_unicode.h` is `"17.0.0"` for this release and upstream's
[README](https://github.com/mrabarnett/mrab-regex#unicode) says the same in prose, but the
constant is defined and never used: it reaches neither the module nor the binary, and `strings`
finds no `17.0.0` in any shipped slice. What you *can* read at runtime is
`unicodedata.unidata_version`, which tells you the other half of the gap — and the gap itself
moves with the interpreter, so the divergence you measure under `flet run` on cp312 is not the
one your cp314 device build has.

### App size

Approximately 271–297 KB compressed and 1.12–1.26 MB unpacked per slice, of which the
extension alone is 658–801 KB. It is large because the Unicode tables are in it: 105 of the 112
exported dynamic symbols are `re_get_*` property lookups (`re_get_script`,
`re_get_grapheme_cluster_break`, `re_get_east_asian_width` and so on). That is the same data
that makes `\p{...}` work without `unicodedata`, so it is not removable.

What *is* removable is the test suite. **`regex/tests/test_regex.py` is 225,809 bytes — 55.5%
of the 406,601 bytes of Python in the wheel — and nothing imports it.** Flet compiles
site-packages to bytecode and deletes the sources by default
([`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup) is `True`), and
compiling *grows* this package: a real cp314 APK of the [example](examples/vs-re) carried
590,272 bytes of `regex` bytecode in `sitepackages.zip`, 338,794 of it that one file. Name it
in the cleanup globs, which serious_python applies to site-packages after compiling:

```toml
[tool.flet.cleanup]
package_files = ["**test_regex.pyc"]
```

**There is no slash after the leading wildcard, and that is not a typo.** serious_python matches
each glob with Dart's `Glob` against the absolute entry path, and a wildcard followed by `/`
insists on a literal separator there, so `**/regex/tests/test_regex.pyc` would miss a top-level
`regex/`. Unslashed, it spans separators the same way serious_python's own built-in `"**.py"`
entry matches `regex/_main.py`. **The glob has not been verified against a real build here**, so
check it by opening the artifact:

```bash
unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip
unzip -l /tmp/sp.zip | grep test_regex
```

At this size `regex` is never itself the reason to reach for an app bundle, split APKs or a
narrower [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures);
every Android ABI is published, so those levers stay available for whatever else the app
carries.

### Other considerations

A desktop `flet run` uses PyPI's own wheel. The C source and the Unicode tables are the same
ones, so behaviour matches — what differs is the interpreter under it, and therefore every
`\p{...}`-versus-`unicodedata` count under [Unicode tables](#unicode-tables).

**The extension touches neither the filesystem nor the network**, so there is nothing to place
in app storage and nothing for the sandbox to refuse. Under a `sys.addaudithook`, a battery of
compiles, matches, substitutions, a `timeout=` expiry and a `purge()` raised **zero** `open`,
`os.*`, `socket.*`, `import` or `exec` audit events; the module's one C-level import resolves
from `sys.modules`. What is worth validating on a device is therefore about text and time
rather than permissions: `\X` against the emoji you actually ship, the `timeout=` path, and the
shape of `regex._regex.__file__`, which the [example](examples/vs-re) prints in its header for
that reason.

## Things to know

- **Set operations need `(?V1)`, and without it you get a different answer rather than an
  error.** This is the sharpest edge in the package. `regex.DEFAULT_VERSION` is `V0`, which is
  `re`-compatible, and in `V0` a `--` or `&&` inside a character class is just more characters
  in the set. Measured on desktop: `[\p{Greek}&&\p{Lu}]+` over `"ΑΒΓ αβγ ABC"` returns `['ΑΒΓ']`
  with `(?V1)` — the intersection, uppercase Greek — and `['ΑΒΓ', 'αβγ', 'ABC']` without it,
  because the class degenerates to the *union* of Greek, `&` and uppercase.
  `[\p{L}--[aeiou]]+` over `"beautiful day"` is worse: `['b', 't', 'f', 'l', 'd', 'y']` with the
  flag and `[]` without, because the `]` after `[aeiou` closes the class and the trailing `]`
  becomes a literal that never matches. Both cases are silent. Write `(?V1)` at the head of any
  pattern using set operations, or set `regex.DEFAULT_VERSION = regex.VERSION1` once at startup
  and accept that it is process-global mutable state your dependencies also see.
- **`regex.error` is not `re.error`, and a `regex` pattern is not an `re.Pattern`.**
  `regex.error is re.error` is `False` and neither is a subclass of the other, so an
  `except re.error:` around code you have just migrated catches nothing.
  `isinstance(regex.compile("a"), re.Pattern)` is `False` too, so anything validating its
  arguments that way rejects a `regex` pattern. Catch `Exception`, or import both error classes.
  Note also that the stdlib class *name* moves with the interpreter — the same exception prints
  as `re.error` on CPython 3.12 and as
  [`PatternError`](https://docs.python.org/3/library/re.html#re.PatternError) from 3.13 — so a
  message you match on changes under you between mobile Python legs.
- **`timeout=` is CPU time, not wall time — and it is the *process's* CPU, which another thread
  can spend for you.** `_regex.c` converts the float with
  `(Py_ssize_t)(value * CLOCKS_PER_SEC)` and compares against `clock()`, processor time for the
  whole process on both platforms, all threads included. Two consequences pull in opposite
  directions. A scan suspended because the user backgrounded the app does not expire while
  suspended, so on a throttling phone it expires later in wall-clock terms than you sized it
  for. But because the default releases the GIL for a `str` subject, a busy sibling thread burns
  the same budget: with `timeout=1.0` on desktop cp312 the matching thread got 1,000.3 ms of its
  own CPU (`time.thread_time`) alone, 312.2 ms beside two CPU-busy threads and 192.1 ms beside
  four, against 1,000.1 / 991.3 / 985.3 ms for the same three runs under `concurrent=False`. So
  `concurrent=False` protects the timeout as well as the throughput. It is a budget for the
  **call**, not for each match attempt — a `findall` over 1, 2, 4 and 8 separately expensive
  restart positions stopped at exactly 1.00 s of CPU in all four cases. Expiry raises the
  builtin `TimeoutError`, and `PyExc_TimeoutError` is an undefined symbol in every mobile slice,
  so this genuinely works there.
- **The classic catastrophic backtracking case that hangs `re` does not hang `regex` — but
  `regex` is not immune, and the timeout is the only defence.** Measured on desktop cp312 with
  `(a+)+b` against a run of `a` and no `b`: `re` quadrupled every two characters, 6.2 ms at 18
  and 1,623.0 ms at 26, while `regex` stayed between 0.018 and 0.094 ms throughout — it
  recognises the pattern and does not explore. Change the pattern slightly and the advantage
  vanishes: `(?:a|a)*$` against `"a"*30 + "b"` runs away in `regex` too, and
  `pattern.match(subject, timeout=0.5)` raised `TimeoutError` after 507 ms.
  **There is no equivalent move for `re`, and not because it merely lacks the keyword.** `re`
  holds the GIL for the whole match, so a runaway one cannot be escaped into a thread: with
  `re.findall(r"(a+)+b", "a"*28)` running in a sibling thread, the main thread got **0 wakeups
  in 17.8 s** against an idle rate of ~143/s. Nor can the subject be capped to a safe length —
  `((a+)+)+b` costs 283.3 ms at 14 characters and `(((a+)+)+)+b` 66.3 ms at 10, so a cap short
  enough to be safe is shorter than any usable input. On a phone, where an `on_click` handler
  runs on the event loop, that is an app frozen until the user kills it. An untrusted pattern
  therefore either goes to `regex` with a `timeout=`, or it is compiled and not run —
  compilation is cheap and safe in both engines, the worst adversarial pattern tried (a
  2,000-branch alternation) compiling in 147 ms.
- **A field where the user types a pattern needs its keyboard turned off.** Set
  `autocorrect=False`, `enable_suggestions=False` and
  `capitalization=ft.TextCapitalization.NONE` on the
  [`ft.TextField`](https://flet.dev/docs/controls/textfield/); without them a phone keyboard
  rewrites the pattern as it is typed — capitalising `\p{lu}`, substituting quotes — and the
  user sees a `regex.error` for something they did not write.
- **Do not locate anything relative to `regex._regex.__file__`, and do not assume the attribute
  exists.** Flet moves ABI-tagged extensions out of site-packages on both platforms, so that
  value is not a path you can open — and on Android it may be missing outright rather than
  merely wrong. Measured under the same Flet version on other recipes' extensions:
  [`pydantic-core`](../pydantic-core)'s `_pydantic_core` reports no `__file__` at all on Android
  while [`pyyaml`](../pyyaml)'s `_yaml` reports the bare `jniLibs` filename `libyaml-_yaml.so`,
  and both report a `.fwork` path on iOS. Read it as `getattr(module, "__file__", None)`;
  written plainly it is an `AttributeError`, and an `AttributeError` raised while building your
  page is a Flet crash screen rather than a message.
- **Avoid [`regex.LOCALE`](https://github.com/mrabarnett/mrab-regex#flags) / `(?L)` on a
  phone.** It makes `\w`, `\b` and case folding depend on the process locale, which an app on
  Android or iOS does not meaningfully control — and the two platforms do not even use the same
  back end, iOS reaching Darwin's locale-aware `<ctype.h>` where Android uses bionic's. The
  Unicode default (`(?u)`, which is the default for `str` patterns) is what you want. Note that
  the compile path calls `locale.getpreferredencoding()` for any pattern not already known to be
  locale-insensitive, so the locale is consulted more often than the flag's rarity suggests.
- **It costs more to import than `re`.** On desktop cp312, best of nine fresh interpreters:
  `import re` 1.68 ms, `import regex` 6.20 ms; RSS, median of seven `ru_maxrss` runs, +639 KB
  against +2.93 MB. Importing `regex` also pulls in `unicodedata`, `locale`, `_locale`,
  `threading`, `enum`, `string`, `copyreg`, `_string` and `_weakrefset` — on 3.12 and 3.13 the
  standard library's `re` as well, by way of `string`, so `regex` does not replace that import,
  it adds to it. At module scope that cost lands on the Flet splash screen; import it inside the
  function that needs it if the feature is optional.
- **It is not uniformly slower at matching, and it is uniformly slower at compiling.** On
  desktop cp312 over a 27,600-character corpus, `findall` best of five, as `re` ms / `regex` ms:
  `\d+` 0.285 / 0.348, `\w+@\w+\.\w+` 0.315 / 0.770, `[A-Za-z]+` 0.286 / 0.431 — but
  `\b\d{4}-\d{2}-\d{2}\b` 0.189 / 0.069, where `regex` is 2.8× *faster*. Compilation is
  consistently around 3× whatever the pattern. Compile once and keep the pattern object, as you
  would anyway.
- **Both engines cache implicitly, in separate caches with different rules.** `regex`'s cache
  holds 500 entries, and when it fills, `_shrink_cache` deletes a fifth of them **chosen with
  `random.sample`** rather than by age, so any given compiled pattern can be evicted while
  hotter ones survive. `re._MAXCACHE` is 512 and `re._compile` drops exactly one per overflow.
  Either way `regex.purge()` clears it, and a pattern built by string concatenation inside a
  loop will churn it.
- **Possessive quantifiers and atomic groups are no longer a reason to reach for this
  package.** `a++` and `(?>a+)b` both work in the standard library from Python 3.11, and both
  engines match `"aaab"` against either — measured across four interpreters, with CPython 3.10
  rejecting both (`unknown extension ?>`, `multiple repeat`) and 3.11, 3.12 and 3.14 accepting
  them. What `re` still does not have is everything else in the list at the top of this page.
- **`regex._regex.copyright` is a lie left over from SRE.** It reads
  `" RE 2.3.0 Copyright (c) 1997-2002 by Secret Labs AB "`. The version you want is
  `regex.__version__`; `regex._regex.MAGIC` (20100116) and `CODE_SIZE` (4) are internal and
  equally useless as version indicators.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is five lines — a name, a version and a build number — and that is the whole
recipe. There is no `patches/` directory, no `source:` key, no `requirements`, no
`build.script_env` and no `build.sh`, so forge builds the PyPI sdist unmodified with its stock
support. The evidence that nothing was touched: the four `.py` files, `METADATA` and
`LICENSE.txt` are byte-identical across all nineteen wheels, and the four `.py` files are
byte-identical to the sdist's. (`WHEEL` and `RECORD` differ per slice, as they must.) Options
that were therefore not needed and should not be added on a bump without a reason:
`extract_packages`, `excluded_arches`, `host_build` requirements, and any `source.url`
override.

The index carries nineteen wheels at one build number: Python 3.12 across four Android ABIs
(arm64-v8a, armeabi-v7a, x86_64 and the legacy 32-bit `android_24_x86`) and three iOS slices
(device, arm64 simulator, x86_64 simulator), and 3.13 and 3.14 across three Android ABIs and
the same three iOS slices. The wheels carry no `Requires-Dist` line at all: `regex` is C rather
than C++, so no `libc++_shared` and no `flet-libcpp-shared` come along. The legacy `x86` wheel
is harmless but unreachable from a Flet build — `serious_python_android` 4.5.1's
`python_versions.properties` lists only `arm64-v8a,x86_64,armeabi-v7a` for each Python.

Two shapes surprise people. The Android extension filename differs by Python version: cp313 and
cp314 ship the full triplet (`regex/_regex.cpython-314-aarch64-linux-android.so`) while all
four cp312 ABIs ship the short forge tag `regex/_regex.cpython-312.so`; iOS is uniform. Both
spellings are ABI-tagged, which is all serious_python's `jniLibs` relocation needs. And the
arm64 *simulator* slice reports `LC_BUILD_VERSION minos 14.0` at all three Python versions
where the other two iOS slices report 13.0, though every wheel is tagged `ios_13_0` —
simulator-only, and no consumer impact has been observed.

### Upgrade hazards

Upstream publishes often — 365 releases to date, ten of them in the first seven months of 2026
alone — so this is a recipe that will be bumped repeatedly, and a green build tells you almost
nothing about whether this page is still true.

- `DEFAULT_VERSION` is assigned in two places. `_regex_core.py` sets it to `VERSION1` and
  `_main.py` then overwrites both its own and `_regex_core`'s with `VERSION0`. The
  consumer-facing `(?V1)` warning rests on `_main.py` winning; a refactor that drops that second
  assignment inverts the page's sharpest bullet without changing any documented behaviour.
- The test suite's path moves. The 2024.11.6 wheels still on the index have a flat
  `regex/test_regex.py` (222,040 bytes) beside a `regex/regex.py`, with no `_main.py` and no
  `tests/` at all. The cleanup glob under **App size** is written against today's layout.
- The day upstream ships mobile wheels of its own, a bare `regex` resolves from PyPI for a
  mobile target and this recipe may stop being needed. Today it publishes none: of the files in
  its own release, not one carries an `android_` or `ios_` tag.

### Re-verification checklist

- **The Unicode version.** `grep RE_UNICODE_VERSION src/_regex_unicode.h` in the unpacked
  sdist, and the `Unicode` section of that sdist's `README.rst`, which states it in prose. Both
  say 17.0.0 today. It is not exposed at runtime and not in the binary, so a table refresh
  inside a `regex` release is invisible unless it is read here — and
  [Unicode tables](#unicode-tables) quotes two measured divergence counts that move with it.
- **The `concurrent` default.** `grep -n 'is_multithreaded' src/_regex.c` — today the `default:`
  arm of the `switch (concurrent)` is `PyUnicode_Check(string) || PyBytes_Check(string)`. The
  whole of [Threading](#threading) rests on that line. A release that flipped it would make
  this page's central warning wrong in the reader's favour, which is still wrong.
- **The timeout clock.** `grep -n 'CLOCKS_PER_SEC\|clock()' src/_regex.c` — today
  `decode_timeout` multiplies by `CLOCKS_PER_SEC` and `check_timed_out` compares `clock()`,
  which is what makes the timeout CPU time rather than wall time.
- **The linkage and the filename.** `DT_NEEDED` still
  `libm`/`libpython3.<minor>`/`libdl`/`libc` with no `libc++_shared`, `PT_LOAD p_align 0x4000`
  on all ten Android extensions, iOS still `MH_DYLIB` with no `Requires-Dist`, and the
  extension still ABI-tagged — an *untagged* `.so` is a silent `ModuleNotFoundError` on device,
  since serious_python keys its `jniLibs` relocation on that suffix.
- **The non-CPython undefined symbols.** Seven on Android today out of 102, on all ten slices
  (`__cxa_atexit`, `__cxa_finalize`, `__register_atfork`, `clock`, `memcpy`, `memmove`,
  `memset`); eleven out of 106 on the cp313 and cp314 iOS slices and twelve out of 107 on the
  cp312 ones, the extras being Darwin's `<ctype.h>` back end (`_DefaultRuneLocale`,
  `__maskrune`, `__tolower`, `__toupper`, plus `btowc` on cp312). The claim under
  [Other considerations](#other-considerations) that the extension touches neither the
  filesystem nor the network is exactly this list — no `open`, `fopen`, `stat`, `socket`,
  `getenv` or even `malloc` in it — so a new entry there needs investigating. Of the four
  Darwin entries only three are locale-gated: `__toupper` runs during `PyInit__regex`, which is
  why all 185 keys of `regex._regex.get_properties()` come back uppercase and stripped, so a
  slice *without* it would be the surprise.
- **The measurements.** Every timing, byte count and code-point count on this page is measured,
  most on a desktop CPython 3.12 on an Apple-Silicon laptop; the on-device pass behind the
  consumer claims was an arm64-v8a Android 14 emulator and an iPhone 16 simulator, both CPython
  3.14.6, where the example's table agreed on 15 of 15 rows. Re-measure rather than scaling —
  and note that the thread-contention multiplier swings by two orders of magnitude with machine
  load, which is why the switch-interval proportionality is quoted beside it as the durable
  evidence. Sizes on this page are decimal (`stat` for compressed, `unzip -l` for unpacked);
  `du` is binary and will read low.

### Coverage gaps

`tests/test_regex.py` is two functions — a property-class match plus an atomic group, and a
`findall` — which is presence, essentially, and it is thinner than what this page claims. Its
comment also calls the atomic group `(?>a+)b` "regex-only syntax", which stopped being true in
CPython 3.11 and should be corrected on the next touch; the property class beside it still
carries the test.

Nothing on device exercises the GIL release, the `timeout=` path, the cleanup glob or either
iOS locale path. In rough order of value, the additions that would protect the consumer-facing
claims: the `(?V1)` set-operation asymmetry, asserting that `[\p{Greek}&&\p{Lu}]+` returns
three matches without the flag and one with it, which is the gotcha an app author is most
likely to hit and would turn red the day `DEFAULT_VERSION` changes; a `timeout=` on a runaway
pattern asserting `TimeoutError`, the only device evidence that `clock()` and
`PyExc_TimeoutError` resolve on these platforms; `\X` over an emoji ZWJ sequence asserting one
match where `len()` is seven, which pins the grapheme tables; and one Unicode-table assertion of
the form "some code point exists that `\p{L}` matches and `unicodedata.category` calls `Cn`" —
stated as a relationship rather than a count, since the count is a property of the interpreter's
tables and would have to be edited on every Python bump. Per the repo's test convention, do not
assert `regex.__version__`.
