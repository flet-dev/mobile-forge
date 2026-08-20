# regex

[`regex`](https://github.com/mrabarnett/mrab-regex) is a drop-in replacement for the
standard library's [`re`](https://docs.python.org/3/library/re.html) with a much larger
pattern language. Every `re` pattern is a `regex` pattern; the reason to add 780 KB of
native code to a phone app is the set of things `re` answers with an exception. The five
that come up most in mobile text handling are Unicode property classes (`\p{Greek}`,
`\p{Lu}`), fuzzy matching with an explicit error budget (`{e<=2}`), overlapping matches,
variable-width lookbehind, and set operations inside a character class (`--`, `&&`).
`\X` — one match per user-perceived character, so an emoji family or a flag counts as
one — is the sixth, and on a phone it is arguably the first.

Every one of those is a one-line comparison against `re`, which is how the
[`regex`](examples/vs-re) example presents them: fifteen patterns, both engines, the
answers side by side and checked rather than described. Run it on a phone as well as a
laptop — the table will agree, and the three measurements under it will not.

Two things about this package are not obvious from its documentation and are the reason
to read further before writing code against it. **It releases the GIL while matching a
`str`, by default** — which costs nothing while your app is single-threaded and turns
into a several-hundred-fold *slowdown* the moment a second thread is busy, so see
[Threading](#threading) before you reach for
[`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread). And **its
Unicode tables are its own**, compiled into the extension and newer than the
interpreter's: on CPython 3.12, whose `unicodedata` is 15.0.0, there are 9,568 code
points that `regex` calls `\p{L}` and `unicodedata` calls unassigned. That is a feature,
and it is also why `\p{L}` and `str.isalpha()` will disagree on the same character.

**Both halves of that were measured on 2026-08-20**, on an arm64-v8a Android 14 emulator and
an iPhone 16 simulator, both CPython 3.14.6. The table agreed exactly: **15 of 15 rows as
expected on each platform**, with `re` raising `PatternError` or `TypeError` on the rows it
cannot answer and `regex` returning the same values on both devices — including `\X` matching a
four-person ZWJ emoji family and a flag as one character each, and `(?:Ljubljana){e<=2}` matching
`Lujbljana` at a reported cost of `(2, 0, 0)`. The timings under the table did not agree, which
is what the split is there to show.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "regex",
]
```

Nothing else to configure. The wheels carry **no `Requires-Dist` line at all** — not on
Android, not on iOS — so no `flet-lib*` wheel and no transitive dependency follows
`regex` in. No
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry and no loader shim are needed either: the package `__init__.py` is a real `.py`
file, the extension beside it carries a CPython ABI tag on every slice, there is no data
file and no `.pyi` stub, and nothing in the package opens a path relative to its own
`__file__` — `_regex_core.py` and `_main.py` contain no `open(`, no `os.path`, no
`__file__` and no `importlib.resources` between them.

The entry belongs in top-level `[project] dependencies` rather than in a
`[tool.flet.android]` / `[tool.flet.ios]` table, because `flet build` resolves for the
build host first and PyPI has a desktop wheel for every host you would build from: the
2026.5.9 release is 113 wheels plus an sdist, covering CPython 3.10 through 3.14 (with
free-threaded `cp313t`/`cp314t` builds as well) across macOS, `manylinux`/`musllinux`
and Windows. Keeping it top-level is also what makes the package present under
`flet run` on your desktop, which matters here more than usual — the example is a
comparison against `re`, and half of it is worth running while you develop.

Nineteen mobile wheels at the same build number: Python 3.12 across four Android ABIs
(arm64-v8a, armeabi-v7a, x86_64 and the legacy 32-bit `android_24_x86`) and three iOS
slices (device, arm64 simulator, x86_64 simulator), and 3.13 and 3.14 across three
Android ABIs and the same three iOS slices. No architecture is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. `Requires-Python` in the wheel is upstream's `>=3.10`, so the floor
you will actually hit is Flet's. And nothing on PyPI competes for these targets: of the
114 files in upstream's own 2026.5.9 release, not one carries an `android_` or `ios_`
tag.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`vs-re`](examples/vs-re) — fifteen patterns run through both engines side by side,
  plus three measurements taken on the device itself.

## Threading

**`regex` releases the GIL while matching, and unless you stop it that is a trap rather
than a gift.** `re` holds the GIL for the whole of a match; `regex` does not. The switch
is the `concurrent` keyword, taken by all twelve matching functions — `search`,
`match`, `fullmatch`, `prefixmatch`, `findall`, `finditer`, `split`, `splititer`, `sub`,
`subn`, `subf`, `subfn`, plus `scanner` on a compiled pattern — and
[documented upstream](https://github.com/mrabarnett/mrab-regex#multithreading) only as a
way to *force* release. Its default is not "off" — `_regex.c` sets `state->is_multithreaded` to
`PyUnicode_Check(string) || PyBytes_Check(string)` when `concurrent` is left alone, so
every ordinary `str` subject gets GIL release without asking. The mechanism ships on
mobile: `PyEval_SaveThread` and `PyEval_RestoreThread` are undefined symbols in every
one of the nineteen wheels, alongside four `PyThread_*` lock entry points and
`PyExc_TimeoutError`.

The cost is that the engine *reacquires* the GIL constantly — around allocation, around
deallocation, and around every cancel check — and each reacquisition has to wait out a
scheduler handoff when another thread wants the GIL too. Measured on desktop cp312 with
a 69,000-character corpus and `\w+@\w+\.\w+` (1,000 matches), against one CPU-busy
sibling thread:

| call | alone | with a busy thread | slowdown |
| --- | --- | --- | --- |
| `re.findall` | 0.76 ms | 0.81 ms | 1.1× |
| `regex.findall` (default) | 1.86 ms | 4,649 ms | 2,494× |
| `regex.findall(..., concurrent=True)` | 1.89 ms | 4,690 ms | 2,488× |
| `regex.findall(..., concurrent=False)` | 1.86 ms | 2.26 ms | 1.2× |

The same shape on the other two mobile Pythons: 1,962× / 1.8× on cp313 and 1,570× /
1.1× on cp314. **The magnitude is scheduler-dependent and moves a lot with machine
load** — repeating the measurement on a heavily loaded laptop gave 19× to 42× instead of
thousands — so treat the exact multiplier as indicative and the direction as solid. What
pins the mechanism is not the multiplier but its proportionality to the GIL switch
interval: 500 matches beside a busy thread took 3,066 ms at the default
`sys.setswitchinterval(0.005)`, 432 ms at 0.001 and 65 ms at 0.0002 — a straight line,
i.e. roughly one GIL round trip per match.

A pure-Python counter thread settles which calls release and which do not, without
depending on the multiplier at all: a C call that keeps the GIL cannot be preempted
between bytecodes, so such a counter advances at essentially nothing while one runs.
Over the same 27.6 M-character corpus on desktop cp312 the counter advanced at 36 k/s
during `re.findall` and at 5,735 k/s during `regex.findall` at its default — 159× — and
fell back to 48 k/s under `concurrent=False`.

**In a Flet app that second thread is not hypothetical.**
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
submits to a shared `ThreadPoolExecutor`, so two taps in quick succession genuinely
overlap, and a scan that took a millisecond in testing becomes seconds. Pass
`concurrent=False` on anything you call from a `run_thread` worker, or on a
[`Pattern`](https://docs.python.org/3/library/re.html#re-objects) you reuse across the
app. There is no module-level default to set: `concurrent` is per call.

**`concurrent=True` buys nothing over the default**, since the default is already `True`
for `str` and `bytes`. It is only meaningful for a subject type that is neither — a
`memoryview` or an `array`, which regex accepts through the buffer protocol and where
it cannot prove the data is immutable. The counter probe reads that straight off: at the
default, `bytes` releases (4,018 k/s) while a `memoryview` and an `array('B')` do not
(46 k/s and 16 k/s, the same as `re`), and only `concurrent=True` moves those two
(4,617 k/s and 4,213 k/s).

The rest is the ordinary Flet arithmetic. Scanning a few kilobytes costs well under a
millisecond and belongs on the UI thread; the case for a background thread is a large
subject, or a pattern you did not write. Whatever you do move, wrap the worker body in
`try/except` — `run_thread` never retrieves the worker's future, so an exception there
is silent — and end it with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach a background thread.

**Nothing in the package starts a thread of its own.** `pthread_create` is not among the
undefined symbols of any slice. `regex` does take a `threading.RLock` around its own
pattern cache (`_main.py`), and the C engine allocates a `PyThread` lock for the match
states that outlive a single call — those behind `finditer` and `splititer`, which pass
`use_lock = TRUE` where the single-shot entry points pass `FALSE` — but only when
multithreading is enabled for that match.

## Android notes

**The extension links nothing but the interpreter and bionic.** `DT_NEEDED` is
`libm.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` on every ABI, with no
`SONAME`, `RPATH` or `RUNPATH` and no `libc++_shared` — regex is C, not C++, so none of
the usual Android C++ staging applies and no `flet-libcpp-shared` comes along. Of the
102 undefined symbols on the cp314 arm64-v8a slice, exactly seven are outside CPython's
API: `__cxa_atexit`, `__cxa_finalize`, `__register_atfork`, `clock`, `memcpy`, `memmove`
and `memset`. There is no `open`, `fopen`, `stat`, `socket`, `connect`, `getenv` or even
`malloc` among them — memory goes through `PyMem_Malloc`, and `clock` is there for the
`timeout` argument. The symbol list alone does not settle it — `PyImport_ImportModule`
is in there, and importing is a filesystem operation — so it is worth confirming from
the other side: under a `sys.addaudithook` on desktop cp312, a battery of compiles,
matches, substitutions, a `timeout=` expiry and a `purge()` raised **zero** `open`,
`os.*`, `socket.*`, `import` or `exec` audit events. (The module's one C-level import is
`get_object("regex._regex_core", "error")`, which finds it already in `sys.modules`.) So
the extension touches neither the filesystem nor the network, and the sandbox has
nothing to say about it.

**Every slice is 16 KB page-aligned**, as Android 15 requires: every `PT_LOAD` segment
in all ten Android extensions reports `p_align 0x4000`. arm64-v8a and x86_64 are
`ELF64`; armeabi-v7a and the legacy `x86` slice are genuine `ELF32`/`ARM` and
`ELF32`/`i386` builds rather than stubs.

**On Android the extension filename shape differs by Python version.** cp313 and
cp314 Android ship the full triplet —
`regex/_regex.cpython-314-aarch64-linux-android.so` — while all four cp312 Android ABIs
ship the short forge tag `regex/_regex.cpython-312.so`. iOS is uniform by comparison:
`_regex.cpython-3NN-iphoneos.so` or `-iphonesimulator.so` at every version. All of them
are ABI-tagged, which is
all that serious_python's relocation into `jniLibs` needs, so none of the shapes asks
anything of you.

**The legacy 32-bit `android_24_x86` wheel exists on the index and `flet build` cannot
target it.** `serious_python_android` 4.5.1's `python_versions.properties` lists
`arm64-v8a,x86_64,armeabi-v7a` for each of 3.12, 3.13 and 3.14, and no `x86`. The wheel
is harmless; it is simply not reachable from a Flet build.

## iOS notes

**Nothing extra to install, and no `MH_BUNDLE` problem.** All nine iOS slices are
already `MH_DYLIB` (`otool -hv` → `filetype DYLIB`, flag `NOUNDEFS`), so the
bundle-to-dylib conversion some CMake-built extensions need does not arise, and there is
exactly one extension per wheel so there is no interdependent-dylib problem either.
`otool -L` lists only the extension's own install name, `@rpath/Python.framework/Python`
and `/usr/lib/libSystem.B.dylib` — no `libc++`, no framework.

**The undefined-symbol set differs from Android's in one interesting way.** Besides
`clock`, `memcpy`, `memmove`, `dyld_stub_binder`, the stack-guard pair and one zeroing
primitive — `bzero` on the two arm64 slices, `memset` on the x86_64 simulator — the iOS
slices import `_DefaultRuneLocale`, `__maskrune`, `__tolower` and `__toupper`, Darwin's
locale-aware `<ctype.h>` back end, which bionic implements differently. That is eleven
non-CPython symbols out of 106 on cp313 and cp314; the three cp312 slices carry a
twelfth, `btowc`, out of 107.

**Three of those four are locale-only; `__toupper` is not, and it runs at import.** The
classification functions behind `_DefaultRuneLocale` and `__maskrune`, and `tolower`,
are called from `scan_locale_chars()` in `_regex.c`, which only runs under
`RE_FLAG_LOCALE` — the `(?L)` /
[`regex.LOCALE`](https://github.com/mrabarnett/mrab-regex#flags) path, a poor idea on a
phone regardless (see [Things to know](#things-to-know)). But `toupper` is also called by
`munge_name()`, and `init_property_dict()` calls that once per property name and value
from `PyInit__regex` itself. The result is readable from Python: all 185 keys of
`regex._regex.get_properties()` come back fully uppercase with `' '`, `'_'` and `'-'`
stripped, which is exactly that loop's output. So a slice with no `__toupper` would be
the surprise, not one with it.

**The arm64 simulator slice disagrees with its own wheel tag about the deployment
target.** `LC_BUILD_VERSION` reports `minos 13.0` on the device slice and on the x86_64
simulator slice but `minos 14.0` on the arm64 simulator slice, at all three Python
versions, though every wheel is tagged `ios_13_0`. Simulator-only, so no consumer impact
has been observed, but it is a real disagreement.

## Things to know

- **Set operations need `(?V1)`, and without it you get a different answer rather than
  an error.** This is the sharpest edge in the package. `regex.DEFAULT_VERSION` is `V0`,
  which is `re`-compatible, and in `V0` a `--` or `&&` inside a character class is just
  more characters in the set. Measured on desktop: `[\p{Greek}&&\p{Lu}]+` over
  `"ΑΒΓ αβγ ABC"` returns `['ΑΒΓ']` with `(?V1)` — the intersection, uppercase Greek —
  and `['ΑΒΓ', 'αβγ', 'ABC']` without it, because the class degenerates to the *union*
  of Greek, `&` and uppercase. `[\p{L}--[aeiou]]+` over `"beautiful day"` is worse: with
  `(?V1)` it gives `['b', 't', 'f', 'l', 'd', 'y']`, and without it, `[]` — the `]`
  after `[aeiou` closes the class and the trailing `]` becomes a literal that never
  matches. Both cases are silent. Write `(?V1)` at the head of any pattern using set
  operations, or set `regex.DEFAULT_VERSION = regex.VERSION1` once at startup and accept
  that it is process-global mutable state your dependencies also see.
- **`regex.error` is not `re.error`, and a `regex` pattern is not an `re.Pattern`.**
  `regex.error is re.error` is `False` and neither is a subclass of the other, so an
  `except re.error:` around code you have just migrated catches nothing. The objects
  differ too: `type(regex.compile("a"))` is `_regex.Pattern` and
  `isinstance(regex.compile("a"), re.Pattern)` is `False`. Anything doing
  `isinstance(x, re.Pattern)` — including some libraries' argument validation — will
  reject a `regex` pattern. Catch `Exception`, or import both error classes.
- **`timeout=` is CPU time, not wall time — and it is the *process's* CPU, which
  another thread can spend for you.** `_regex.c` converts the float with
  `(Py_ssize_t)(value * CLOCKS_PER_SEC)` and compares against `clock()`, which on both
  platforms is processor time for the whole process, all threads included. Two
  consequences pull in opposite directions. A scan that gets suspended when the user
  backgrounds the app does not expire while it is suspended, and on a phone that
  throttles it expires later in wall-clock terms than you sized it for. But because the
  default releases the GIL for a `str` subject, a busy sibling thread burns the same
  budget: measured on desktop cp312 with `timeout=1.0`, the matching thread got
  1,000.3 ms of its own CPU (`time.thread_time`) with nothing else running, 312.2 ms
  beside two CPU-busy threads and 192.1 ms beside four. With `concurrent=False` the same
  three runs gave 1,000.1 / 991.3 / 985.3 ms, because nothing else can run at all. So
  `concurrent=False` protects the timeout as well as the throughput. Expiry raises
  `TimeoutError` — the builtin, and `PyExc_TimeoutError` is an undefined symbol in every
  mobile slice, so this genuinely works there. It is the right guard for a pattern the
  user typed; it is not a way to measure elapsed time. It is also a budget
  for the **call**, not for each match attempt: a `findall` whose subject was built to
  contain 1, 2, 4 and 8 separately expensive restart positions stopped at exactly 1.00 s
  of CPU in all four cases (desktop cp312), rather than spending a fresh second on each.
  The wall-clock cost of that second is whatever the machine is busy doing — on a laptop
  at load average 43 it was 3.8–4.8 s, and a pure-Python control spending 1.00 s of CPU
  took 4.06 s there too, so the gap is the machine and not the engine.
- **The classic catastrophic backtracking case that hangs `re` does not hang `regex` —
  but `regex` is not immune, and the timeout is the only defence.** Measured on desktop
  cp312 with `(a+)+b` against a run of `a` and no `b`: `re` took 6.2 / 25.2 / 102.6 /
  422.8 / 1,623.0 ms at 18 / 20 / 22 / 24 / 26 characters, quadrupling every two, while
  `regex` stayed between 0.018 and 0.094 ms throughout — it recognises the pattern and
  does not explore. Change the pattern slightly and the advantage vanishes:
  `(?:a|a)*$` against `"a"*30 + "b"` runs away in `regex` too, and
  `pattern.match(subject, timeout=0.5)` raised `TimeoutError` after 507 ms of wall
  clock. If a pattern can come from user input or a server, pass a timeout.
  **There is no equivalent move for `re`, and not because it merely lacks the
  keyword.** `re` holds the GIL for the whole match, so a runaway one cannot be
  escaped by moving it to a thread: with `re.findall(r"(a+)+b", "a"*28)` running in a
  sibling thread, the main thread got **0 wakeups in 17.8 s** of desktop wall clock
  against an idle rate of ~143/s. Nor can the subject be capped to a safe length —
  `((a+)+)+b` costs 33.9 ms at 12 characters and 283.3 ms at 14, and
  `(((a+)+)+)+b` 2.6 ms at 8 and 66.3 ms at 10 — 8× and 25× per two characters, so a
  cap short enough to be safe is shorter than any usable input. On a phone, where an
  `on_click` handler runs on the event loop, that is an app frozen until the user kills
  it. So an untrusted pattern
  either goes to `regex` with a `timeout=`, or it is compiled and not run —
  compilation is cheap and safe in both engines (the worst adversarial pattern tried,
  a 2,000-branch alternation, compiled in 147 ms).
- **`regex`'s Unicode tables are newer than the interpreter's, and there is no way to
  read their version at runtime.** `RE_UNICODE_VERSION` in the sdist's
  `src/_regex_unicode.h` is `"17.0.0"` for this release, and upstream's
  [README](https://github.com/mrabarnett/mrab-regex#unicode) says the same in prose — but
  the constant is defined and never used, so it reaches neither the module nor the
  binary: `strings` finds no `17.0.0` in any shipped slice. What you can do is measure
  the gap, which is what the
  [example](examples/vs-re) does: on CPython 3.12 (`unicodedata` 15.0.0) there are
  **9,568 code points that `\p{L}` matches and `unicodedata.category()` calls `Cn`**,
  and on CPython 3.14 (`unicodedata` 16.0.0) there are 4,644 — with **zero** in the
  other direction, which is the signature of one table simply being ahead of the other.
  U+088F, U+0C5C and U+0CDC are in both lists. `\p{L}` against `str.isalpha()` gives
  exactly the same figures — 9,568 characters that `\p{L}` matches and `isalpha()`
  rejects on 3.12, 4,644 on 3.14, none the other way — so which of the two is "right"
  is only a question of which Unicode release you meant.
- **`regex._regex.copyright` is a lie left over from SRE.** It reads
  `" RE 2.3.0 Copyright (c) 1997-2002 by Secret Labs AB "`. The version you want is
  `regex.__version__`; `regex._regex.MAGIC` (20100116) and `CODE_SIZE` (4) are internal
  and equally useless as version indicators.
- **Every wheel ships upstream's test suite, and Flet's default build makes it bigger.**
  `regex/tests/test_regex.py` is 225,809 bytes — 55.5% of the 406,601 bytes of Python in
  the wheel — and nothing imports it. The wheel ships no `regex/tests/__init__.py`, though
  do not rely on that as the reason on Android: serious_python's zip step synthesises an
  empty one for any directory it packages that lacks it, because `zipimport` has no
  namespace packages. A built APK of the [example](examples/vs-re) carries a zero-byte
  `regex/tests/__init__.py` it never had in the wheel — as does `flet/messaging/`, the only
  other such directory in that payload. Flet compiles site-packages to `.pyc` and deletes the
  sources by default
  ([`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup) is `True`
  in `flet_cli/commands/build_base.py`), and compiling *grows* this package. It grows by
  a different amount on each interpreter, so the leg matters: `python -m compileall -b`,
  which is the invocation serious_python uses, turns 406,601 bytes of `.py` into 589,760
  bytes of `.pyc` on cp314, of which 338,666 — 57.4% — is `test_regex.pyc`, and into
  571,555 bytes on cp312, where that file is 335,024 bytes and 58.6%. A real cp314 APK of
  the [example](examples/vs-re) agrees: 590,272 bytes of `regex` bytecode in
  `sitepackages.zip`, `test_regex.pyc` 338,794 of it. The few hundred bytes above the
  desktop figure are the build's longer source path, which `compileall` bakes into each
  `co_filename`. To drop it, name it in the cleanup globs, which serious_python applies to
  site-packages after compiling:

  ```toml
  [tool.flet.cleanup]
  package_files = ["**test_regex.pyc"]
  ```

  **There is no slash after the leading wildcard, and that is not a typo.** serious_python
  matches each glob with Dart's `Glob` against the absolute entry path, and a wildcard
  followed by `/` insists on a literal separator there — so
  `**/regex/tests/test_regex.pyc` would miss a top-level `regex/`. Unslashed, the wildcard
  spans directory separators the same way
  serious_python's own built-in `"**.py"` entry matches `regex/_main.py`, and
  `cleanupDirRecursive` deletes the directory once it is empty. **The glob itself has not
  been verified against a real build here** — check it the way you would check any payload
  question, by opening the artifact:
  `unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l
  /tmp/sp.zip | grep test_regex`.
- **It costs more to import than `re`.**
  On desktop cp312, best of nine fresh interpreters: `import re` 1.68 ms, `import regex`
  6.20 ms. RSS, median of seven runs of `ru_maxrss`: `re` +638,976 B, `regex`
  +2,932,736 B. Importing `regex` also pulls in `unicodedata`, `locale`, `_locale`,
  `threading`, `enum`, `string`, `copyreg`, `_string` and `_weakrefset` — on 3.12 and
  3.13 the standard library's `re` as well, by way of `string`, so `regex` does not
  replace that import, it adds to it. If your app imports it at module scope that cost
  lands on the Flet splash screen. Import it inside the function that needs it if the
  feature is optional.
- **It is not uniformly slower at matching, and it is uniformly slower at compiling.**
  On desktop cp312 over a 27,600-character corpus, `findall` best of five, as `re` ms /
  `regex` ms: `\d+` 0.285 / 0.348, `\w+@\w+\.\w+` 0.315 / 0.770, `[A-Za-z]+` 0.286 /
  0.431 — but `\b\d{4}-\d{2}-\d{2}\b` 0.189 / 0.069, where `regex` is 2.8× *faster*. At
  552,000 characters the email pattern is 7.32 ms against 25.79 ms. Compilation is
  consistently around 3× (median of 200, cache purged between): `\d+` 0.0062 / 0.0188
  ms, `[A-Za-z]+` 0.0076 / 0.0312 ms, `(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})` 0.0187 /
  0.0557 ms. Compile once and keep the pattern object, as you would anyway.
- **Both engines cache implicitly, in separate caches with different rules.**
  `regex._main._MAXCACHE` is 500, and when the cache reaches it `_shrink_cache` deletes
  `_MAXCACHE // 5` entries **chosen with `random.sample`** rather than by age, so the
  size sawtooths 500 → 401 → 500 and any given compiled pattern can be evicted while
  hotter ones survive. `re._MAXCACHE` is 512 and `re._compile` drops exactly one per
  overflow. Measured on desktop cp312 after `purge()` and 600 distinct compiles: 500
  entries for `regex`, 512 for `re`. Either way `regex.purge()` clears it, and a pattern
  built by string concatenation inside a loop will churn it.
- **Possessive quantifiers and atomic groups are no longer a reason to reach for this
  package.** `a++` and `(?>a+)b` both work in the standard library from Python 3.11, and
  both engines match `"aaab"` against either — measured across four interpreters, with
  CPython 3.10 rejecting both (`unknown extension ?>`, `multiple repeat`) and 3.11, 3.12
  and 3.14 accepting them. What `re` still does not have is everything else in the list
  at the top of this page.
- **Avoid `regex.LOCALE` / `(?L)` on a phone.** It makes `\w`, `\b` and case folding
  depend on the process locale, which on Android and iOS is not something an app
  meaningfully controls; the Unicode default (`(?u)`, which is the default for `str`
  patterns) is what you want. Note also that the compile path calls
  `locale.getpreferredencoding()` for any pattern not already known to be
  locale-insensitive, so the locale is consulted more often than the flag's rarity
  suggests.
- **Do not locate anything relative to `regex._regex.__file__`, and do not assume the
  attribute exists.** Flet moves ABI-tagged extensions out of site-packages on both
  platforms, so that value is not a path you can open — and on Android it may be missing
  outright rather than merely wrong. Measured under the same Flet version on other
  recipes' extensions: [`pydantic-core`](../pydantic-core)'s `_pydantic_core` reports no
  `__file__` at all on Android while [`pyyaml`](../pyyaml)'s `_yaml` reports the bare
  `jniLibs` filename `libyaml-_yaml.so`, and both report a `.fwork` path on iOS. Read it
  as `getattr(module, "__file__", None)`; written plainly it is an `AttributeError`, and
  an `AttributeError` raised while building your page is a Flet crash screen rather than
  a message. Nothing in `regex` reads it, so this only bites code of yours; the
  [example](examples/vs-re) prints it in its header line so you can read the real shape
  off a device.
- **Size: 271–297 KB to download, 1.12–1.26 MB unpacked, and the extension is 59–64% of
  that.** Per slice:

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | cp314 Android arm64-v8a | 288,269 B | 1,239,574 B | 780,024 B |
  | cp314 Android armeabi-v7a | 270,594 B | 1,117,676 B | 658,124 B |
  | cp314 Android x86_64 | 293,006 B | 1,255,018 B | 795,472 B |
  | cp314 iOS device | 283,772 B | 1,260,580 B | 801,040 B |
  | cp314 iOS arm64 simulator | 291,828 B | 1,250,522 B | 790,968 B |
  | cp312 Android x86 (legacy 32-bit) | 296,469 B | 1,221,838 B | 762,316 B |

  The extension is large because the Unicode tables are in it: 105 of the 112 exported
  dynamic symbols are `re_get_*` property lookups — the same 105 on the cp314 arm64-v8a
  Android slice and on the cp314 iOS device slice
  (`re_get_script`, `re_get_grapheme_cluster_break`, `re_get_east_asian_width` and so
  on). That is the same data that makes `\p{...}` work without touching `unicodedata`.

## Build notes (maintainers)

`meta.yaml` is five lines — a name, a version and a build number — and that is the whole
recipe. There is no `patches/` directory, no `source:` key, no `requirements`, no
`build.script_env` and no `build.sh`, so forge builds the PyPI sdist unmodified with its
stock support. The evidence that nothing was touched: the four `.py` files, `METADATA` and
`LICENSE.txt` are byte-identical across all nineteen wheels, and the four `.py` files
are byte-identical to `regex-2026.5.9.tar.gz`'s. (`WHEEL` and `RECORD` differ per slice,
as they must.) Options that were therefore not needed
and should not be added on a bump without a reason: `extract_packages`,
`excluded_arches` (all four Android ABIs and all three iOS slices build),
`host_build` requirements, and any `source.url` override.

Upstream publishes often — 365 releases to date, ten of them in the first seven months
of 2026 alone — and PyPI is already at **2026.7.19** while this recipe pins 2026.5.9. So
this is a recipe that will be bumped repeatedly. What to re-verify each time, in rough
order of what a green build fails to tell you:

- **The Unicode version.** `grep RE_UNICODE_VERSION src/_regex_unicode.h` in the
  unpacked sdist, and the `Unicode` section of the same sdist's `README.rst`, which
  states it in prose. Both say 17.0.0 today; it is not exposed at runtime and it is not
  in the binary, so a table refresh inside a `regex` release is invisible unless it is read
  here. [Things to know](#things-to-know) quotes it and quotes two measured divergence
  counts against `unicodedata`; both move when it moves.
- **The `concurrent` default.** `grep -n 'is_multithreaded' src/_regex.c` — today the
  `default:` arm of the `switch (concurrent)` is
  `PyUnicode_Check(string) || PyBytes_Check(string)`. The whole of
  [Threading](#threading) rests on that line. A release that flipped the default would
  make this page's central warning wrong in the reader's favour, which is still wrong.
- **The timeout clock.** `grep -n 'CLOCKS_PER_SEC\|clock()' src/_regex.c` — today
  `decode_timeout` multiplies by `CLOCKS_PER_SEC` and `check_timed_out` compares
  `clock()`, which is what makes the timeout CPU time rather than wall time. If upstream
  moves to a monotonic clock, the corresponding bullet stops being true.
- **Whether the test suite is still in the wheel.** `regex/tests/test_regex.py` is 55.5%
  of the shipped Python today and the size table and the cleanup-glob advice both depend
  on it. Upstream restructures this occasionally: the 2024.11.6 wheels still on the
  index have a flat `regex/test_regex.py` (222,040 bytes) beside a `regex/regex.py`, and
  no `_main.py` or `tests/` at all. Re-check the path before repeating the glob.
- **The linkage and the filename.** `DT_NEEDED` still
  `libm`/`libpython3.<minor>`/`libdl`/`libc` with no `libc++_shared`, 16 KB `PT_LOAD`
  alignment on all Android ABIs, iOS still `MH_DYLIB` with no `Requires-Dist`, and the
  extension still ABI-tagged — an *untagged* `.so` would be a silent
  `ModuleNotFoundError` on device, since serious_python keys its `jniLibs` relocation on
  that suffix.
- **The non-CPython undefined symbols.** Seven on Android today
  (`__cxa_atexit`, `__cxa_finalize`, `__register_atfork`, `clock`, `memcpy`, `memmove`,
  `memset`) out of 102, on all ten slices; eleven out of 106 on the cp313 and cp314 iOS
  slices and twelve out of 107 on the cp312 ones. The claim that the extension touches
  neither the filesystem nor the network is exactly this list; a new `open` or `getenv`
  in it would need investigating and would change what
  [Android notes](#android-notes) says.
- **That `regex` still has no mobile wheels of its own on PyPI.** Today it publishes
  none, so a bare `regex` can only resolve from this index for a mobile target; the day
  upstream ships one, this recipe may stop being needed.
- **The measurements.** Every timing, byte count and code-point count above is measured,
  most on desktop cp312 on an Apple-Silicon laptop. Re-measure rather than scaling — and
  note that the thread-contention multiplier in particular is scheduler-dependent and
  swings by two orders of magnitude with machine load, which is why the switch-interval
  proportionality is quoted beside it as the durable evidence.

`tests/test_regex.py` is two functions — a property-class match plus an atomic group,
and a `findall` — which is presence, essentially, and it is thinner than what this page
claims. Its comment also calls the atomic group `(?>a+)b` "regex-only syntax", which
stopped being true in CPython 3.11 and should be corrected on the next touch; the
property class beside it still carries the test.

In rough order of value, the additions that would protect the
consumer-facing claims: the `(?V1)` set-operation asymmetry, asserting that
`[\p{Greek}&&\p{Lu}]+` returns three matches without the flag and one with it, which is
the gotcha an app author is most likely to hit and would turn red the day upstream
changes `DEFAULT_VERSION`; a `timeout=` on a runaway pattern asserting `TimeoutError`,
which is the only device evidence that `clock()` and `PyExc_TimeoutError` resolve on
these platforms; `\X` over an emoji ZWJ sequence asserting one match where `len()` is
seven, which pins the grapheme tables; and one Unicode-table assertion of the form "some
code point exists that `\p{L}` matches and `unicodedata.category` calls `Cn`" — stated
as a relationship rather than a count, since the count is a property of the
interpreter's tables and would have to be edited on every Python bump. Per the repo's
test convention, do not assert `regex.__version__`.
