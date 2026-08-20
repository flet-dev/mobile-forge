# jq

[`jq`](https://github.com/mwilliamson/jq.py) is a Python binding for
[jq](https://jqlang.github.io/jq/), and the reason to ship it is not that it parses JSON —
`json` already does that, in C, faster. It is that jq is a *query language*. A transform
that reads as a nested loop with an accumulator dictionary and three `isinstance` checks in
Python is one string here, and the string can come from a config file, a server response or
a text field the user types into, which is something no amount of Python refactoring gets
you.

Two programs from the [`query-console`](examples/query-console) example. Every number
anywhere in a document that equals a sentinel, reported by path, without the query knowing
the document's shape:

```
[ paths(numbers) as $p | select(getpath($p) == -99) | $p | map(tostring) | join(".") ]
```

Every key that looks like a secret, masked at any depth:

```
walk(if type == "object" then with_entries(
  if (.key | test("token|secret|password"; "i")) then .value = "***" else . end) else . end)
```

The Python equivalents in that example are 13 and 15 lines, and both are recursive walkers
that have to be told how the document is nested. The jq versions are not.

**The mobile wheel speaks jq 1.7.1, not the 1.8.1 upstream's own wheels bundle.** The
recipe links this index's `flet-libjq` 1.7.1 instead of the copy of jq vendored in jq.py's
sdist, so the *Python* API is identical and the *language* is one release behind. Measured
by running `builtins` under both: 218 under a desktop replica of the mobile pairing against
226 from the PyPI wheel. The nine that exist on desktop and not on mobile are `trim/0`, `ltrim/0`, `rtrim/0`,
`trimstr/1`, `toboolean/0`, `skip/2`, `add/1`, `have_decnum/0` and `have_literal_numbers/0`;
`pow10/0` goes the other way, and gains you nothing — on both sides it is a stub that
raises `Error: pow10/0 not found at build time`, a name in the list rather than a function.
Reach for one of the nine and you get
`jq: error: trim/0 is not defined`, from a program that works on your laptop. The evidence
is in the shipped binaries as well as the run: all eighteen published wheels embed jq
1.7.1's `builtin.jq` — `def bsearch`, `def _nwise` and two `def unique` present, `trimstr/1`
and `skip/2` absent — and `trim`, which 1.8.0 added as a C builtin, appears as a standalone
string in none of them. Match whole names when you re-check this: a plain
`strings … | grep trimstr` finds two hits that are `ltrimstr` and `rtrimstr`, both of which
1.7.1 has, and `grep skip` finds the unrelated `<skipped: too deep>`.

**Where the numbers on this page come from.** Anything about the wheels was measured on the
published build-2 files from `pypi.flet.dev`. Anything about behaviour or timing was measured
on an Apple M4 desktop, macOS 26.6, CPython 3.12.13, against a *replica of the mobile
pairing* — jq.py 1.11.0 built with `JQPY_USE_SYSTEM_LIBS=1` against a local jq 1.7.1 whose
shared libraries were deleted so the link had to be static, exactly what the recipe does.
That replica reports the same 218 builtins the wheels do. Do not try to reproduce the
timings with a plain `pip install jq`: upstream's PyPI wheel runs the same queries 3–4×
slower than the replica (parse 5.49 ms against 1.89), and that is its build rather than its
jq version, since the 1.7.1 and 1.8.1 command-line binaries parse the same file in 2.28 and
2.12 ms. The cause is one line of jq.py's `setup.py`: it configures its vendored jq with
`CFLAGS=-fPIC -pthread`, which *replaces* autoconf's default `-g -O2`. Built both ways from
the same jq 1.7.1 source here, the example's `sentinels` program takes 63.5 ms unoptimised
against 14.0 ms optimised. The recipe never runs that `configure` — `JQPY_USE_SYSTEM_LIBS=1`
selects a plain `build_ext`, `recipes/flet-libjq/build.sh` sets no `CFLAGS` of its own, and
forge passes the cross interpreter's `-DNDEBUG -g -O3` through — and the shipped binaries
agree: the iOS slices carry `_OUTLINED_FUNCTION_*` and `__MergedGlobals` symbols, which only
optimising LLVM passes emit, and no local symbol for `jvp_refcnt_inc`, a non-`inline`
`static` in `jv.c` that survives `-O0` and is inlined away at `-O2`. Expect a phone to beat
what a laptop shows here rather than match it. Nothing here was measured on a phone; run the
[example](examples/query-console) for that.

**A jq program is a runtime error waiting to happen, and it is a `ValueError`.** A syntax
error, an undefined function, and `Cannot iterate over number (42)` at run time all raise
plain `ValueError` — there is no exception class of jq's own to catch, and an unhandled
exception in a Flet event handler ends the session with a crash screen. If any part of the
program is not a literal you wrote, wrap the call.

**Measured on device, 2026-08-20**, on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6. Both report the same **218 builtins** over the same bundled
242,202-byte document (120 stations, 2,880 readings), and both produced identical output values
to the last digit. The cost splits into two numbers the example reports separately, which is the
distinction that matters if you run a query more than once: compiling the program took 1.73 ms
on iOS and 2.44 ms on Android, while *running* it took 3.2 ms and 17.3 ms. Compile once, reuse
the compiled program, and the per-run cost is what you pay.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "jq",
]
```

Nothing else to configure, and nothing comes along with it: the `METADATA` in all eighteen
published wheels contains **zero** `Requires-Dist` lines. In particular the `flet-libjq`
wheel this recipe builds against does not follow it onto the device — the static archives
are linked into the extension, so there is nothing left to depend on at runtime.
`Requires-Python` is `>=3.8`, so the Python floor you actually hit is Flet's.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Every wheel is six files — one extension plus five `dist-info` entries —
with no Python module and no data file of any kind, so the Flet 0.86 Android
`sitepackages.zip` class of failure has nothing to bite on. There is no Python layer at
all: `top_level.txt` says `jq` and `jq` *is* the extension, which also means the ABI tag
serious_python's Android packaging keys on is present by construction.

Eighteen wheels at build 2: Android arm64-v8a, armeabi-v7a and x86_64 plus iOS device,
arm64-simulator and x86_64-simulator, on each of Python 3.12, 3.13 and 3.14. The recipe
declares no `excluded_arches`, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is required — though there is a size reason to consider it anyway, in
[Android notes](#android-notes).

**A bare `jq` really does resolve from this index for a mobile target.** Upstream publishes
60 files for 1.11.0 on PyPI and not one is an Android wheel, an iOS wheel or a
`py3-none-any` wheel — only an sdist and CPython 3.8-through-3.14 (plus PyPy 3.11) binaries
for macOS, manylinux, musllinux and Windows. Checked with
`pip download --only-binary :all:` with **PyPI listed first** and this index only as
`--extra-index-url`, once per platform family across the three Pythons: every one came back
with this index's build-2 wheel.

Because those desktop wheels exist for every CPython from 3.10 to 3.14 on macOS, Linux and
Windows, `jq` belongs in `[project] dependencies` and not in a `[tool.flet.<platform>]`
table — the host resolve `flet build` performs will find one. Just remember that the one it
finds bundles a newer jq than your phone will run, and is an unoptimised build, so `flet run`
on your laptop previews neither the language your phone will speak nor the speed it will
speak it at.

**Desktop and device can also be on different *pip* releases unless you pin.** PyPI's newest
jq.py is 1.12.0; this index's newest is 1.11.0 build 2. A bare `jq` therefore resolves 1.12.0
for `flet run` on your laptop and 1.11.0 for `flet build` — verified for an Android
arm64-v8a / cp314 target, which still came back with this index's wheel because 1.12.0
publishes no mobile wheel either. The language gap is unchanged by that: 1.12.0's desktop
wheel answers `builtins | length` with **226** and runs `trim`, exactly as 1.11.0's does, so
everything below about the 218-builtin mobile build still holds. Pin both sides — as
[`query-console`](examples/query-console) does — if the Python API version matters to you.

## Storage

**jq opens no file in the normal path, and there is no cache or config directory to point
anywhere before importing it.** The one exception is the module loader, and it is worth
knowing because it is also useful: jq's `include` and `import` read `.jq` files from disk.
Without a path they resolve relative to the process working directory, which on a device is
not somewhere you control; with the metadata form they resolve wherever you say. Verified on
desktop:

```python
program = jq.compile('include "helpers" {search: "%s"}; summarise' % library_dir)
```

That makes [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
a reasonable home for a library of reusable jq functions you ship or download, and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
the place for anything derived. `modulemeta` on a module that is not on the search path
raises `ValueError: module not found: <name>` rather than returning null, so it is not a
safe existence check.

**`$ENV` and `env` are not the same thing, and the difference is a caching bug waiting to
happen.** `$ENV` is a snapshot taken when the program is *compiled*; `env` reads the
environment when the program *runs*. Measured on desktop: with a variable set after
`jq.compile`, the same program object returned `null` for `$ENV.X` and the new value for
`env.X`. Compile a program before Flet has finished populating the environment and its
`$ENV` is frozen at whatever was there first. Worse, it is not stable per program object —
see [Threading](#threading).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`query-console`](examples/query-console) — a bundled JSON document, an editable jq
  program, its output, and a hand-written Python twin per preset to check the answer and
  the cost against.

## Threading

**jq never releases the GIL, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys
nothing here.** `PyEval_SaveThread`, `PyEval_RestoreThread` and every `PyGILState_*` entry
point are absent from all eighteen slices — zero hits across the nine Android extensions'
dynamic symbol tables and the nine iOS extensions' undefined-symbol lists. Three
measurements on an Apple M4 desktop, the first two over the example's 242,202-byte
document:

- A pure-Python counting thread, which can only advance while it holds the GIL, kept
  **28.1–29.0%** of its idle rate over three trials while another thread ran jq queries in a
  loop, against **47.9–54.8%** when it competed with pure-Python work. jq is *worse* than an
  ordinary Python competitor because it never yields mid-call; the counter only runs in the
  gaps between calls.
- Four concurrent queries took **59.5–62.0 ms**; four serial ones took **60.3–66.7 ms**.
  There is no parallelism to have.
- **A running program cannot be interrupted.** A `KeyboardInterrupt` signalled 50 ms into a
  program that takes 418–440 ms uninterrupted arrived at 435 ms, 471 ms and 449 ms across
  three runs — in each of them after that same run's call had already returned, never during
  it. jq programs can be unbounded (`repeat`,
  `recurse`, a recursive `def`), and neither a timeout nor a cancel button can end one.

So run short queries inline in the handler, which is what the
[example](examples/query-console) does. Use `run_thread` only for the reason it still has —
letting the handler return, and the spinner you set with it reach the client, before the
work starts — and remember it swallows whatever a worker raises and needs an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) at the end.

**A compiled program is safe to use from several threads, and concurrency costs a recompile
rather than a lock wait.** jq.py keeps one `jq_state` per compiled program behind a
`threading.Lock`; a second thread that finds the slot empty compiles a fresh state instead
of waiting. That is why four threads produced correct results above. It has one visible
consequence: because `$ENV` is captured at compile time, the *same* program object can
report different `$ENV` values depending on whether the pooled state was free — and which
snapshot it settles on depends on the order its iterators are freed, because the pool holds
exactly one state and tears down any other. Measured on desktop, one iterator held open
across an `os.environ` change: `jq.compile('$ENV.X')` returned `None`, then `'changed'`
while held, and then **kept returning `'changed'` for good**, the recompiled state having
claimed the slot the moment it was released. Hold two iterators and free the older one
first and the older snapshot wins instead — `None`, `'changed'`, `None`.

## Android notes

- **Three ABIs mean three copies of a ~1 MB extension.** The `.so` is 98.90–99.16% of the
  unpacked wheel on every Android slice: 1,046,784 B on arm64-v8a, 805,584 B on
  armeabi-v7a and 1,054,984 B on x86_64 for 3.14 — **2,907,352 bytes** if a build covers
  all three, and within 3,320 bytes of that on 3.12 and 3.13. If size matters more than
  emulator coverage, that is the lever:

  ```toml
  [tool.flet.android]
  target_arch = ["arm64-v8a", "x86_64"]   # x86_64 = emulator; drop it for a device-only release
  ```
- **The extension links nothing but the interpreter and bionic.** `DT_NEEDED` is exactly
  `libm.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` on all nine Android slices,
  with no `SONAME`, no `RPATH`, no `RUNPATH` and **no `libjq.so`** — jq and oniguruma are
  linked in statically, and the arm64-v8a 3.14 extension defines 77 `jq_*`, 99 `jv_*` and
  274 `onig*` symbols itself, importing none of them: of its 281 undefined dynamic symbols,
  not one is a jq, jv or oniguruma name. No `libc++_shared` either, so none
  of the usual Android C++ staging applies. All `PT_LOAD` segments carry 16 KB alignment,
  which Android 15 requires, and armeabi-v7a is a genuine `ELF32`/`ARM` build rather than a
  stub.
- **Every Android slice is stripped** — no `.symtab`, no `.debug_*`. A crash inside jq will
  give you an address and no name.
- **The 3.12 Android slices name the extension `jq.cpython-312.so`, without the platform
  triplet**, while 3.13 and 3.14 use the full `jq.cpython-31X-<triplet>.so`. Both carry the
  `.cpython-*` tag serious_python's `jniLibs` relocation keys on, so both work.
- **`exp10` is a build-time stub here and a working function everywhere else.** All three
  Android slices append `def exp10: "Error: exp10/0 not found at build time"|error;` to the
  embedded `builtin.jq`; the iOS slices append only the matching `pow10` stub, and the
  desktop replica answers `100` to `2|exp10`. `builtins | length` is 218 either way — the
  stub keeps the name in the list — so neither that probe nor the
  [example](examples/query-console)'s header line will warn you. One obscure function, but a
  one-line program that runs on a laptop and on an iPhone and raises `ValueError` on Android.

## iOS notes

- **The same source weighs 7.6% more here, and the difference is symbol names, not code.**
  1,126,400 bytes of Mach-O on the 3.14 device slice against 1,046,784 of ELF on Android
  arm64 — 79,616 bytes. The iOS extensions keep a local symbol table (`nm -a` lists
  8,583–8,799 entries per slice; plain `nm` only 2,416–2,448) where the Android ones are
  stripped bare. It is not debug information:
  there is no `__DWARF` segment on any slice, only `__TEXT`, `__DATA_CONST`, `__DATA` and
  `__LINKEDIT`.
- **Each extension is `MH_DYLIB`**, checked on all nine iOS slices, which matters because
  Flet 0.86 turns every site-packages `.so` into a framework binary that SwiftPM *links*,
  and `ld` refuses an `MH_BUNDLE`. `otool -L` names exactly two dependencies on every slice —
  `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib` — under a third line that
  is no dependency at all but the extension's own `LC_ID_DYLIB`, still the relative
  `build/lib.ios-.../jq.cpython-...so` path setuptools linked it with.
- **Do not assume `$ENV` holds the same keys here as on Android.** It is simply the process
  environment, and the two Flet runtimes are not obliged to populate it identically — this
  recipe has no on-device evidence either way, which is the reason to check rather than
  assume. `$ENV | keys` in the [example](examples/query-console)'s query field answers it in
  one tap on each platform.

## Things to know

- **Every number comes back through a C `double`, and four things happen on the way.**
  Measured on desktop against the mobile pairing:

  | jq expression | Python value |
  | --- | --- |
  | `1.0` | `1` (an `int`; any integral float collapses) |
  | `nan` | `None` |
  | `infinite` | `1.7976931348623157e+308` (`DBL_MAX`, not `inf`) |
  | `.` on `12345678901234567890` | `12345678901234567168` |

  The last one is the dangerous one: jq itself keeps the literal — `tojson` on that input
  returns `12345678901234567890` exactly — and it is the binding's conversion that loses
  the digits. If you need a large integer or an exact decimal to survive, pipe it through
  `tojson` and parse the string yourself.
- **`.first()` raises `StopIteration` when the program emits nothing.** `jq.first("empty", 1)`
  does not return `None`; it raises, and `StopIteration` escaping a handler is as fatal as
  any other exception. Use `.all()` and check the list, which is what the
  [example](examples/query-console) does.
- **`input` and `inputs` do not work the way the command-line tool taught you.** jq.py runs
  the program once per input document rather than handing the program a stream, so on the
  text `1 2 3` the program `[., inputs]` returns three separate results — `[1]`, `[2]`,
  `[3]` — instead of one `[1,2,3]`. Bare `input` raises `ValueError: break`,
  `input_line_number` raises `ValueError: Unknown input line number`, and `input_filename`
  is `null`. Use `input_text(..., slurp=True)` when you want the documents as one array;
  `add` over `1 2 3` slurped returns `6`.
- **`error(...)` with a non-string arrives as JSON in the exception message.**
  `error({code: 1})` raises `ValueError: {"code": 1}`, so structured errors survive but you
  have to `json.loads` the message to read them. `halt_error` is harmless in-process: it
  produces no output values and the interpreter keeps running — it does not exit the app.
- **`input_value(obj)` is `input_text(json.dumps(obj))`, so pass text if you have text.** On
  the example's 242,202-byte document that dump costs 0.99 ms per call, which is what
  separates the same query at 3.05 ms through `input_value` from 2.08 ms through
  `input_text`; a payload that arrived as an HTTP response body should go straight to
  `input_text` rather than through `json.loads`. Two corollaries: a value
  Python cannot serialise raises `TypeError: Object of type set is not JSON serializable`
  from `json`, not from jq; and `float("nan")` and `float("inf")` are written as the
  non-standard `NaN`/`Infinity`, which jq accepts and then hands back as `None` and
  `DBL_MAX`.
- **The parse dominates, so the query is usually not what costs you.** On the same desktop
  and the same document: `json.loads` 0.83 ms, jq's own parse 1.96 ms (measured with the
  program `1`, which ignores its input entirely), and five real queries 1.99–14.40 ms
  end to end. Against hand-written Python starting from the same text, jq ran 2.1× to 5.9×
  slower. You are buying the expression, not the speed.
- **Compiling is cheap, but reuse the compiled program anyway.** 0.37–0.45 ms per
  `jq.compile` for the example's programs, against 2–14 ms to run them. The reason to hold
  onto the object is not the compile time — it owns the `jq_state`, and every `jq.compile`
  call also takes a process-wide lock, so compiling inside a loop serialises threads that
  would otherwise proceed.
- **You get a full regex engine whether you use it or not.** Oniguruma is linked in — 274
  distinct `onig*` symbols in the Android arm64 3.14 extension — so `test`, `match`, `capture`,
  `sub`, `splits` and `ascii_downcase` all work with no extra dependency;
  `capture("(?<y>[0-9]{4})-(?<m>[0-9]{2})")` on `"2026-08-20"` returns
  `{'y': '2026', 'm': '08'}`. It is also a large part of why the extension is a megabyte.
- **There is no `jq.__version__`.** Nothing in the module reports which libjq is compiled
  in. `jq.compile("builtins | length").input_value(None).first()` is the closest thing to a
  version probe, and it is the check that distinguishes this wheel (218) from upstream's
  (226).
- **`jq -r` is a flag, not a function.** `.all()` gives you Python objects and `.text()`
  gives you `json.dumps` of each, so a program ending in `@csv` or `@tsv` yields *quoted
  JSON strings* unless you print them yourself. The example's `render` does the raw-string
  branch that `-r` does.

## Build notes (maintainers)

The one thing that has no home in `meta.yaml` or in `patches/mobile.patch`, and the reason
this section exists: **`JQPY_USE_SYSTEM_LIBS` decouples the language version from the pip
version.** jq.py 1.11.0's sdist vendors jq 1.8.1 under `deps/`, and the recipe deliberately
does not build it; it links `flet-libjq` 1.7.1 instead. Everything on this page about which
builtins exist follows from that pin and from nothing else, and a green build will not tell
you it changed.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **The builtins count, whichever half moves.** Bumping `flet-libjq` changes the language;
  bumping `jq` changes which jq upstream *thinks* it is bundling, and its release notes will
  describe a version the wheel does not contain. Build the same pairing on desktop
  (`JQPY_USE_SYSTEM_LIBS=1` against a local `flet-libjq` prefix with the shared libraries
  removed) and run `builtins`; 218 is jq 1.7.1 and 226 is 1.8.1. The list of nine
  differences quoted above, the `trim/0 is not defined` error text and the
  `def bsearch`/`def _nwise` strings in the shipped `.so` all move together.
- **That `METADATA` still has zero `Requires-Dist` lines, and that no Android slice names
  `libjq.so` in `DT_NEEDED`.** Those two together are the check that the static link held —
  a dynamic link would reintroduce exactly the collision `patches/mobile.patch` exists to
  avoid, and it would do so without failing the build.
- **`MH_DYLIB` on all nine iOS slices** (`otool -hv`). A CMake-shaped build that produced
  `MH_BUNDLE` would install and `dlopen` fine in older Flet and fail at link under 0.86.
- **The extension filename per slice**, especially whether 3.12 still drops the platform
  triplet. An untagged `.so` would be a silent `ModuleNotFoundError` on Android, since
  serious_python keys its relocation on that suffix.
- **The number-coercion table**, which is `_jv_to_python` in `jq.pyx` and can change under
  you at a jq.py bump without any note in a changelog about doubles.

`tests/test_jq.py` is two functions: a `select`/`compile` filter and `jq.first`. That is
enough to prove the extension loads and executes a program on device, and not enough to
protect what this page claims. In rough order of value, the additions worth making: a regex
assertion (`test`/`capture`), which is the only thing that would catch a build that lost
oniguruma while still importing; a `ValueError` assertion for a bad program, since
[the intro](#jq) tells people that is the exception to catch; the number-coercion
behaviour, since it is the trap most likely to reach a user's data; and a `slurp` round trip,
since `input`/`inputs` do not work and `slurp` is what this page recommends instead. A test
asserting the *builtins count* is deliberately not on that list — it would fail on every
`flet-libjq` bump by design, which is a maintenance burden rather than a signal; check the
pairing by hand at bump time instead.
