# jq

[`jq`](https://github.com/mwilliamson/jq.py) is a Python binding for
[jq](https://jqlang.github.io/jq/), and the reason to ship it is not that it parses JSON —
`json` already does that, in C, faster. It is that jq is a *query language*. A transform that
reads as a nested loop with an accumulator dictionary and three `isinstance` checks in Python
is one string here, and that string can arrive from a config file, a server response or a text
field the user typed into, which is something no amount of Python refactoring gets you.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "jq",
]
```

`jq` belongs in `[project] dependencies` rather than in a `[tool.flet.<platform>]` table: PyPI
publishes desktop wheels for every current CPython on macOS, Linux and Windows, so the host
resolve [`flet build`](https://flet.dev/docs/publish/) performs finds one as well.

The wheel it finds there is not the wheel your phone gets, in two ways worth knowing before
you build. It bundles a newer jq than the mobile wheel links, so `flet run` on your laptop
previews a different *language* — see [Language version](#language-version). And because PyPI
and this index publish on their own schedules, a bare `jq` can resolve one jq.py release for
`flet run` and another for `flet build`. Pin both sides, as
[`query-console`](examples/query-console) does, when the Python API version matters to you.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`query-console`](examples/query-console) — a bundled JSON document, an editable jq program,
  its output, and a hand-written Python twin per preset to check the answer and the cost
  against.

## Usage in a Flet app

Compile a program once, feed it JSON, and read the output values back as ordinary Python
objects:

```python
program = jq.compile('[.stations[] | select(.online) | .name] | join(", ")')
values = program.input_text(payload).all()
page.add(ft.Text(values[0] if values else "no matches"))
```

`payload` there is the JSON as *text*, which is what
[`.input_text()`](https://github.com/mwilliamson/jq.py#input-methods) wants; `.input_value()`
takes an already-parsed Python object. Prefer
[`.all()`](https://github.com/mwilliamson/jq.py#output-methods) to `.first()`, which raises
`StopIteration` when the program emits nothing, and put the result in any control that takes a
string — [`ft.Text`](https://flet.dev/docs/controls/text/) above. Hold onto the object
`jq.compile` returns: compiling is cheap, but running the program is where the time goes, and
the compiled object is what you reuse.

**A jq program is a runtime error waiting to happen, and it is a `ValueError`.** A syntax
error, an undefined function, and `Cannot iterate over number (42)` at run time all raise plain
`ValueError` — there is no exception class of jq's own to catch — and an unhandled exception in
a Flet event handler ends the session with a crash screen. If any part of the program is not a
literal you wrote, wrap the call:

```python
try:
    values = jq.compile(user_program).input_text(payload).all()
except ValueError as error:
    output.value, output.color = str(error), ft.Colors.ERROR
```

### Storage

jq opens no file in the normal path, and there is no cache or config directory to point
anywhere before importing it. The one exception is the module loader, and it is worth knowing
because it is also useful: jq's [`include` and `import`](https://jqlang.github.io/jq/manual/v1.7/#modules)
read `.jq` files from disk. Without a path they resolve relative to the process working
directory, which on a device is not somewhere you control; with the metadata form they resolve
wherever you say.

```python
program = jq.compile('include "helpers" {search: "%s"}; summarise' % library_dir)
```

That makes [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
a reasonable home for a library of reusable jq functions you ship or download,
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
the place for output you can regenerate, and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
the place for throwaway intermediates. A `.jq` library shipped with the application is an
asset: put it in the [assets directory](https://flet.dev/docs/cookbook/assets) and use
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir) to
build the absolute `search` path.
[`modulemeta`](https://jqlang.github.io/jq/manual/v1.7/#modulemeta) on a module that is not on
the search path raises `ValueError: module not found: <name>` rather than returning null, so it
is not a safe existence check.

**[`$ENV` and `env`](https://jqlang.github.io/jq/manual/v1.7/#$env-env) are not the same thing,
and the difference is a caching bug waiting to happen.** `$ENV` is a snapshot taken when the
program is *compiled*; `env` reads the environment when the program *runs*. Measured on
desktop: with a variable set after `jq.compile`, the same program object returned `null` for
`$ENV.X` and the new value for `env.X`. Compile a program before Flet has finished populating
the environment and its `$ENV` is frozen at whatever was there first — and it is not even
stable per program object, for the reason in [Threading](#threading).

### Threading

**jq never releases the GIL, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys
nothing here.** No `PyEval_SaveThread`, `PyEval_RestoreThread` or `PyGILState_*` call appears in
any published slice. Two measurements on an Apple M4 desktop, over the
[example](examples/query-console)'s 242 KB document, say what that costs: four concurrent
queries took 59.5–62.0 ms against 60.3–66.7 ms for four serial ones, so there is no parallelism
to have; and a pure-Python counting thread kept only **28–29%** of its idle rate while another
thread ran jq in a loop, against 48–55% when it competed with pure-Python work. jq is *worse*
than an ordinary Python competitor because it never yields mid-call — the counter runs only in
the gaps between calls.

**A running program cannot be interrupted, either.** A `KeyboardInterrupt` signalled 50 ms into
a program that takes 418–440 ms arrived at 435–471 ms across three runs, in every case after
that same call had already returned. jq programs can be unbounded (`repeat`, `recurse`, a
recursive `def`), and neither a timeout nor a cancel button can end one. Bound the program, not
the call.

So run short queries inline in the handler, which is what the
[example](examples/query-console) does. Use `run_thread` only for the reason it still has —
letting the handler return, and the spinner you set with it reach the client, before the work
starts — and remember it swallows whatever a worker raises and needs an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) at the end.

**A compiled program is safe to use from several threads, and concurrency costs a recompile
rather than a lock wait.** jq.py keeps one `jq_state` per compiled program behind a
`threading.Lock`; a second thread that finds the slot empty compiles a fresh state instead of
waiting, which is why four threads produced correct results above. The visible consequence is
that a program object's `$ENV`, captured at compile time, is not stable: with one iterator held
open across an `os.environ` change, `jq.compile('$ENV.X')` returned `None`, then `'changed'`,
and then **kept returning `'changed'` for good** — the recompiled state had claimed the slot.
Free a different iterator first and the older snapshot wins instead. Read configuration through
`env`, never `$ENV`.

### Language version

**The mobile wheel speaks jq 1.7.1, one release series behind the jq that upstream's own
desktop wheels bundle.** The recipe links this index's `flet-libjq` instead of the copy of jq
vendored in jq.py's sdist, so the *Python* API is identical and the *language* is older. Run
[`builtins`](https://jqlang.github.io/jq/manual/v1.7/#builtins) and count: **218** here against
**226** from the PyPI wheel. The nine that exist on desktop and not on mobile are `trim/0`,
`ltrim/0`, `rtrim/0`, `trimstr/1`, `toboolean/0`, `skip/2`, `add/1`, `have_decnum/0` and
`have_literal_numbers/0`. `pow10/0` goes the other way and gains you nothing — on both sides it
is a stub that raises `Error: pow10/0 not found at build time`, a name in the list rather than
a function. Reach for one of the nine and you get `jq: error: trim/0 is not defined`, from a
program that works on your laptop.

That count is also the version probe, because nothing in the module reports which libjq is
compiled in:

```python
builtins = jq.compile("builtins | length").input_value(None).first()
```

**`exp10` is a build-time stub on Android and a working function everywhere else.** The Android
slices append `def exp10: "Error: exp10/0 not found at build time"|error;` to the embedded
builtins; the iOS slices append only the matching `pow10` stub, and desktop answers `100` to
`2|exp10`. `builtins | length` is 218 either way — the stub keeps the name in the list — so the
probe above will not warn you. One obscure function, but a one-line program that runs on a
laptop and on an iPhone and raises `ValueError` on Android.

### App size

The wheel is essentially one extension: about **1.0 MB unpacked per architecture** — 0.8 MB on
`armeabi-v7a`, 1.1 MB on the iOS slices — so roughly **2.9 MB** if an Android build covers all
three ABIs. There is no Python module, data directory or test suite for
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) to remove.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI:

```toml
[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

`x86_64` is the emulator ABI; drop it for a device-only release. These figures describe the
package payload, not the amount added to the final APK or IPA; packaging and compression
determine that.

### Other considerations

A desktop `flet run` previews neither the language your phone will speak nor the speed it will
speak it at. The language gap is the one above. The speed gap is that upstream's PyPI wheel is
built without optimisation while this one is not, which makes it 3–4× slower on the same
queries — so treat a desktop timing as a floor rather than a forecast, and measure on a device
when the cost matters.

Nothing on this page except the [example](examples/query-console) run was measured on a phone.
Figures labelled *desktop* come from an Apple M4; the on-device ones come from an Android
emulator and an iOS simulator, and since the simulator runs on the host Mac's own CPU the two
platforms' timings do not compare with each other. What did compare: both reported the same 218
builtins over the same document and produced identical output values to the last digit, and on
both, compiling cost a couple of milliseconds against single- to double-digit milliseconds to
run. Compile once, and the per-run cost is what you pay.

`$ENV` is simply the process environment, and the two Flet runtimes are not obliged to populate
it identically — this recipe has no on-device evidence either way, which is the reason to check
rather than assume. `$ENV | keys` in the [example](examples/query-console)'s query field
answers it in one tap on each platform.

## Things to know

- **Every number comes back through a C `double`, and four things happen on the way.** Measured
  on desktop against the mobile pairing:

  | jq expression | Python value |
  | --- | --- |
  | `1.0` | `1` (an `int`; any integral float collapses) |
  | `nan` | `None` |
  | `infinite` | `1.7976931348623157e+308` (`DBL_MAX`, not `inf`) |
  | `.` on `12345678901234567890` | `12345678901234567168` |

  The last one is the dangerous one: jq itself keeps the literal — `tojson` on that input
  returns `12345678901234567890` exactly — and it is the binding's conversion that loses the
  digits. If you need a large integer or an exact decimal to survive, pipe it through `tojson`
  and parse the string yourself.
- **`.first()` raises `StopIteration` when the program emits nothing.** `jq.first("empty", 1)`
  does not return `None`; it raises, and `StopIteration` escaping a handler is as fatal as any
  other exception. Use `.all()` and check the list, which is what the
  [example](examples/query-console) does.
- **[`input` and `inputs`](https://jqlang.github.io/jq/manual/v1.7/#inputs) do not work the way
  the command-line tool taught you.** jq.py runs the program once per input document rather
  than handing the program a stream, so on the text `1 2 3` the program `[., inputs]` returns
  three separate results — `[1]`, `[2]`, `[3]` — instead of one `[1,2,3]`. Bare `input` raises
  `ValueError: break`, `input_line_number` raises `ValueError: Unknown input line number`, and
  `input_filename` is `null`. Use `input_text(..., slurp=True)` when you want the documents as
  one array; `add` over `1 2 3` slurped returns `6`.
- **[`error(...)`](https://jqlang.github.io/jq/manual/v1.7/#error) with a non-string arrives as
  JSON in the exception message.** `error({code: 1})` raises `ValueError: {"code": 1}`, so
  structured errors survive but you have to `json.loads` the message to read them.
  [`halt_error`](https://jqlang.github.io/jq/manual/v1.7/#halt_error) is harmless in-process: it
  produces no output values and the interpreter keeps running — it does not exit the app.
- **`input_value(obj)` is `input_text(json.dumps(obj))`, so pass text if you have text.** On the
  example's 242 KB document that dump costs 0.99 ms per call, which is what separates the same
  query at 3.05 ms through `input_value` from 2.08 ms through `input_text`; a payload that
  arrived as an HTTP response body should go straight to `input_text` rather than through
  `json.loads`. Two corollaries: a value Python cannot serialise raises
  `TypeError: Object of type set is not JSON serializable` from `json`, not from jq; and
  `float("nan")` and `float("inf")` are written as the non-standard `NaN`/`Infinity`, which jq
  accepts and then hands back as `None` and `DBL_MAX`.
- **The time goes into the parse, not the query and not the compile.** On the same desktop and
  document: `json.loads` 0.83 ms, jq's own parse 1.96 ms (measured with the program `1`, which
  ignores its input entirely), five real queries 1.99–14.40 ms end to end, and `jq.compile`
  0.37–0.45 ms. Against hand-written Python starting from the same text, jq ran 2.1× to 5.9×
  slower — you are buying the expression, not the speed. Reuse the compiled program even so: it
  owns the `jq_state`, and every `jq.compile` call takes a process-wide lock, so compiling
  inside a loop serialises threads that would otherwise proceed.
- **You get a full regex engine whether you use it or not.** Oniguruma is linked in, so
  [`test`](https://jqlang.github.io/jq/manual/v1.7/#test),
  [`capture`](https://jqlang.github.io/jq/manual/v1.7/#capture), `match`, `sub`, `splits` and
  `ascii_downcase` all work with no extra dependency;
  `capture("(?<y>[0-9]{4})-(?<m>[0-9]{2})")` on `"2026-08-20"` returns
  `{'y': '2026', 'm': '08'}`. It is also a large part of why the extension is a megabyte.
- **`jq -r` is a flag, not a function.** `.all()` gives you Python objects and `.text()` gives
  you `json.dumps` of each, so a program ending in `@csv` or `@tsv` yields *quoted JSON strings*
  unless you print them yourself. The example's `render` does the raw-string branch that `-r`
  does.

## Build notes (maintainers)

### Recipe shape

**`JQPY_USE_SYSTEM_LIBS` decouples the language version from the pip version.** jq.py's sdist
vendors its own copy of jq under `deps/`, and the recipe deliberately does not build it; it
links `flet-libjq` instead. Everything this page says about which builtins exist follows from
that pin and from nothing else, and a green build will not tell you it changed.

**There is no Python layer: `jq` *is* the extension.** Every wheel is six files — one extension
plus five `dist-info` entries — with no Python module and no data file of any kind. Two
consequences worth not rediscovering: the Flet 0.86 Android `sitepackages.zip` class of failure
has nothing to bite on, so no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is needed;
and the `.cpython-*` ABI tag that serious_python's `jniLibs` relocation keys on is present by
construction rather than by arrangement.

**The shipped build is optimised and upstream's PyPI wheel is not**, which is why the desktop
comparison in *Other considerations* is a build difference rather than a version difference.
jq.py's `setup.py` hands `./configure` a `CFLAGS=-fPIC -pthread` that *replaces* autoconf's
default `-g -O2`. The recipe never runs that `configure` — `JQPY_USE_SYSTEM_LIBS=1` selects a
plain `build_ext`, `recipes/flet-libjq/build.sh` sets no `CFLAGS` of its own, and forge passes
the cross interpreter's `-DNDEBUG -g -O3` through. Built both ways from the same jq 1.7.1
source, the example's `sentinels` program takes 63.5 ms unoptimised against 14.0 ms optimised,
and upstream's wheel parses the example document in 5.49 ms against 1.89 ms for the replica.
That is not the jq version: the 1.7.1 and 1.8.1 command-line binaries parse the same file in
2.28 ms and 2.12 ms. The shipped binaries agree that the flags arrived — the iOS slices carry
`_OUTLINED_FUNCTION_*` and `__MergedGlobals` symbols, which only optimising LLVM passes emit,
and no local symbol for `jvp_refcnt_inc`, a non-`inline` `static` in `jv.c` that survives `-O0`
and is inlined away at `-O2`.

### Upgrade hazards

- **Bumping either half moves the language claims, and neither bump announces it.** Bumping
  `flet-libjq` changes the language directly; bumping `jq` changes which jq upstream *thinks* it
  is bundling, so its release notes will describe a version the wheel does not contain.
- **A dynamic link would reintroduce exactly the collision `patches/mobile.patch` exists to
  avoid, and would not fail the build.** Any change to how the extension is linked needs the
  `DT_NEEDED` check below run by hand.
- **The number-coercion table is `_jv_to_python` in `jq.pyx`** and can change under you at a
  jq.py bump without any note in a changelog about doubles.

### Re-verification checklist

Behaviour claims here were derived from a desktop *replica of the mobile pairing* — jq.py built
with `JQPY_USE_SYSTEM_LIBS=1` against a local jq 1.7.1 prefix whose shared libraries were
deleted so the link had to be static, exactly what the recipe does. That replica reports the
same 218 builtins the wheels do, which is what makes it a replica. Rebuild it the same way to
re-derive anything below; a plain `pip install jq` reproduces neither the language nor the
timings.

- **The builtins count.** 218 is jq 1.7.1 and 226 is the 1.8 series. The list of nine
  differences, the `trim/0 is not defined` error text and the embedded-builtins strings below
  all move together.
- **The embedded `builtin.jq`,** which is the same evidence read out of the shipped `.so`:
  `def bsearch`, `def _nwise` and two `def unique` present, `trimstr/1` and `skip/2` absent, and
  `trim` — added as a C builtin in 1.8.0 — appearing as a standalone string in none of the
  wheels. **Match whole names.** A plain `strings … | grep trimstr` finds two hits that are
  `ltrimstr` and `rtrimstr`, both of which 1.7.1 has, and `grep skip` finds the unrelated
  `<skipped: too deep>`.
- **The `exp10`/`pow10` stubs,** which platform appends which, and whether `builtins | length`
  still hides the difference.
- **Zero `Requires-Dist` lines in `METADATA`, and no `libjq.so` in any Android slice's
  `DT_NEEDED`.** Those two together are the check that the static link held. `DT_NEEDED` should
  be exactly `libm.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so`, with no `SONAME`,
  `RPATH` or `RUNPATH`, and the extension should define its own `jq_*`, `jv_*` and `onig*`
  symbols while importing none of them.
- **`MH_DYLIB` on every iOS slice** (`otool -hv`). A CMake-shaped build that produced
  `MH_BUNDLE` would install and `dlopen` fine in older Flet and fail at link under 0.86.
  `otool -L` should name only `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`.
- **The extension filename per slice**, especially whether 3.12 still drops the platform
  triplet where 3.13 and 3.14 carry it. An untagged `.so` would be a silent
  `ModuleNotFoundError` on Android.
- **16 KB `PT_LOAD` alignment on Android**, which Android 15 requires, and that `armeabi-v7a` is
  a genuine `ELF32`/`ARM` build rather than a stub.
- **Size.** Re-measure from the wheels rather than scaling the figures above. Note that the iOS
  slices weigh about 8% more than Android arm64 for the same source because they keep a local
  symbol table where the Android ones are stripped bare; that is not debug information — no
  slice has a `__DWARF` segment — so stripping is not a size lever someone forgot to pull.

### Coverage gaps

`tests/test_jq.py` is two functions: a `select`/`compile` filter and `jq.first`. That is enough
to prove the extension loads and executes a program on device, and not enough to protect what
this page claims. Every claim above about number coercion, `input`/`inputs`, regex, error types
and the builtins count rests on desktop measurement or wheel inspection alone.

In rough order of value, the additions worth making: a regex assertion (`test`/`capture`), which
is the only thing that would catch a build that lost oniguruma while still importing; a
`ValueError` assertion for a bad program, since this page tells people that is the exception to
catch; the number-coercion behaviour, since it is the trap most likely to reach a user's data;
and a `slurp` round trip, since `input`/`inputs` do not work and `slurp` is what this page
recommends instead. A test asserting the *builtins count* is deliberately not on that list — it
would fail on every `flet-libjq` bump by design, which is a maintenance burden rather than a
signal; check the pairing by hand at bump time instead.
