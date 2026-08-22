# greenlet

[`greenlet`](https://greenlet.readthedocs.io) gives CPython stackful coroutines. A greenlet
owns a real machine stack, and
[`switch()`](https://greenlet.readthedocs.io/en/latest/greenlet.html#greenlet.greenlet.switch)
moves the CPU from one to another and back again, from any depth, in the middle of anything —
including through frames you did not write. A generator can only suspend itself; a greenlet
can suspend a whole synchronous call stack and resume it later.

None of that is portable C. The switch is a page of hand-written assembly per architecture,
picked at compile time, and it works on every slice this index ships. The usual reason to
want it on a phone is that a library demands it: SQLAlchemy's asyncio support *is* a greenlet
bridge, and an async engine that resolves without greenlet fails at the first `await` rather
than at import.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "greenlet",
]
```

The entry belongs in top-level `[project] dependencies` and not in a
`[tool.flet.<platform>]` table: `flet build` resolves for the build host first, and PyPI has
desktop wheels for every host you would build from.

**If greenlet is here for SQLAlchemy, ask for it by name or take the extra.** SQLAlchemy's
base `greenlet` requirement carries a `platform_machine` marker, and pip evaluates markers
against the machine doing the build rather than the target — on an Apple Silicon Mac, where
`platform_machine` is `arm64`, it is simply false. Measured with `pip download --only-binary
:all: --platform android_24_arm64_v8a --python-version 3.14` against PyPI plus
`https://pypi.flet.dev/`: a bare `sqlalchemy` fetched SQLAlchemy and `typing_extensions` and
**no greenlet**, while `sqlalchemy[asyncio]` fetched this index's greenlet wheel. An app that
resolves without greenlet builds, installs and starts, then dies at the first `await`. Name
`"sqlalchemy[asyncio]"` or `"greenlet"` yourself instead of relying on that marker; see
[`sqlalchemy`](../sqlalchemy).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`coroutine-switch`](examples/coroutine-switch) — prices a switch against a generator and a
  thread on the device, and runs eight conformance checks over the paths the assembly has to
  get right.

## Usage in a Flet app

Build a greenlet from a callable, `switch()` into it, and `switch()` back out from inside it.
Whatever one call passes is what the other returns, and the greenlet resumes exactly where it
left off:

```python
import flet as ft
import greenlet


def main(page: ft.Page):
    output = ft.Text()

    def work():
        """Drive a greenlet on a worker thread and put what it yields on screen."""
        home = greenlet.getcurrent()

        def counter():
            for step in range(3):
                home.switch(step * step)  # park here, hand a value back

        worker = greenlet.greenlet(counter)
        try:
            output.value = " ".join(str(worker.switch()) for _ in range(3))
        finally:
            worker.throw()  # a parked greenlet holds its stack until something kills it
        page.update()  # auto-update does not reach background threads

    page.add(output, ft.Button("Run", on_click=lambda e: page.run_thread(work)))


if __name__ == "__main__":
    ft.run(main)
```

### Threading

**A greenlet is not a thread and never becomes one.** The extension imports no
`PyEval_SaveThread`, no `PyEval_RestoreThread` and no `PyGILState_*` symbol on any slice — the
five thread-state calls it does import are `PyThreadState_Get`, `GetDict`, `GetFrame`,
`EnterTracing` and `LeaveTracing` — so the GIL is never dropped and two greenlets never run at
once. Measured on desktop with the example's own GIL panel, which times 400,000 multiplies
done twice against the same work split across two greenlets: three runs gave **1.05×, 1.00×
and 0.96×** — one, within the noise of an 18 ms measurement. Greenlets buy you interleaving
and a call stack you can park; they do not buy you a second core.

**Greenlets belong to the thread that created them**, and that is the rule that decides how
they fit into Flet. Every thread gets its own main greenlet — `greenlet.getcurrent().parent`
is `None` on each — and switching to a greenlet created on a different thread raises
`greenlet.error` rather than corrupting anything. The two spellings are worth recognising:
while the owning thread is alive the message is `Cannot switch to a different thread` followed
by a `Current:`/`Expected:` dump of both greenlets; once greenlet's cleanup for that thread has
run it becomes the one-line `cannot switch to a different thread (which happens to have
exited)`. Which one you get is not a reliable signal, and `dead` separates the two cases in
only one direction: a greenlet that had actually started reports `dead == True` once its thread
has gone, while one that was never started stays `False` through the join, the failed switch
and a `gc.collect()`. Catch `greenlet.error`; do not test `dead` to find out whose thread a
greenlet belongs to.

So [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is where
a greenlet workload belongs, and a whole greenlet graph must live inside one worker.

- **Create and drive the greenlets inside the worker.** A greenlet built in an event handler
  and switched to from a `run_thread` worker will raise, and the raise is invisible —
  `run_thread` never retrieves the worker's future, so a `greenlet.error` there produces no
  log, no dialog and no crash. Wrap the worker body in `try`/`except`, and end it with an
  explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
  auto-update does not reach background threads.
- **Cooperative means cooperative.** A greenlet yields only where you wrote `switch()`. A
  blocking call inside one blocks the OS thread it is on, and therefore every other greenlet on
  that thread, with no preemption to save you. On the UI thread that is a frozen app; the reason
  to keep this in a worker is not throughput, it is that a greenlet cannot be interrupted.

For SQLAlchemy the whole bridge is internal — you write `async with engine.begin()` and
greenlet is what carries the `await` across the sync driver call — so the rule reduces to
running the async engine on one thread's event loop and not sharing greenlet-backed connections
across `run_thread` workers.

### Depth and cost

**A generator beats a greenlet everywhere, and a greenlet beats a thread by an amount you
should not quote.** Measured 2026-08-20 on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6, inside a `run_thread` worker:

| handoff | iOS simulator | Android emulator |
| --- | ---: | ---: |
| greenlet switch pair | 1,623 ns | 1,789 ns |
| generator `next()` | 24 ns | 96 ns |
| thread round trip | 2,979 ns | 396,687 ns |

The switch itself is close on both. The thread row is not a platform fact: an emulated
Android thread handoff is roughly 130× the simulator's, which makes greenlets look 1.8× cheaper
than threads in one column and 222× cheaper in the other. Read the generator row instead — if a
generator can express what you need, it is one to two orders of magnitude cheaper, and the
reason to reach for greenlet is that it can suspend frames a generator cannot.

**A switch is O(the parked greenlet's Python frame depth), and the cost is not the stack copy.**
The same run parked one greenlet 0, 100 and 1,000 Python frames down and reported both the time
and `_stack_saved`, the bytes copied off the machine stack:

| frames parked | machine stack copied | ns per switch pair | | |
| --- | ---: | ---: | ---: | ---: |
| | iOS | Android | iOS | Android |
| 0 | 2,504 B | 1,448 B | 1,614 | 1,109 |
| 100 | 2,504 B | 1,448 B | 3,088 | 3,795 |
| 1,000 | 2,504 B | 1,448 B | 17,824 | 102,053 |

The bytes column is flat and the time column is not, on both platforms. **Park shallow
greenlets**: suspend at the top of a call stack, not the bottom of one. Why the two columns
disagree is in [Things to know](#things-to-know).

### iOS

**The iOS slices are compiled without `-O` and without `-DNDEBUG`, and it has two
consequences you can see from an app.** Every iOS slice imports `___assert_rtn` and carries the
live text of the assertions it can trip, while no Android slice imports an assert symbol or
embeds one of those strings. So an assertion failure inside greenlet on iOS calls `abort()` in
a shipped build rather than having been compiled out, and any iOS timing from the
[example](examples/coroutine-switch) is a statement about how the wheel was built, not about
Apple silicon. Reproducing the same flags on a desktop build moved a switch pair from 228 ns to
1,601 ns. The cause and the fix are in [Build notes](#build-notes-maintainers).

### App size

The wheels are 231–268 KB compressed and 650–983 KB unpacked, the iOS slices being the larger
half of that range (832–983 KB against 650–746 KB). At that size greenlet is not a reason to
narrow [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures).

What reaches the device is about 453 KB, and 297 KB of it is upstream's own test suite —
`greenlet/tests/`, which nothing in an app imports and which includes two extension modules
built solely to exercise greenlet's C API.
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) is the lever:

```toml
[tool.flet.cleanup]
package_files = ["greenlet/tests"]
```

serious_python appends those globs to its own junk list and deletes a matching directory
recursively. No build behind the figures on this page was run with it set. Measure the payload
*after* the compile step and in decimal bytes: `compile.packages` is on by default and
serious_python runs `compileall -b` and deletes the `.py` files before the junk pass, so source
becomes larger `.pyc`, and every `.pyc` moves by roughly 150 bytes per file with the install
path, which each one records in `co_filename`.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel, which is optimised and has assertions compiled
out; the iOS slices on this index are neither. A switch that costs 237 ns under `flet run` on
an Apple M4 measured 1,623 ns on a simulator, and a slow greenlet path you tune on the desktop
may be a different shape on device. Time the workload where it will run.

## Things to know

- **The frame walk, not the memcpy, is what makes a deep greenlet expensive.** Measured on
  desktop, CPython 3.14.6, best of three:

  | frames parked | machine stack copied | ns per switch pair |
  | --- | ---: | ---: |
  | 0 | 1,416 B | 223 |
  | 100 | 1,416 B | 712 |
  | 1,000 | 1,416 B | 7,082 |

  Since 3.11 a Python-to-Python call does not recurse in C, so a thousand Python frames cost no
  extra machine stack and the copy stays flat — yet the switch gets 32× dearer. The cause is in
  the shipped source: `Greenlet::expose_frames()` in `TGreenlet.cpp` walks the entire
  `_PyInterpreterFrame` chain every time a greenlet is switched away from, so that a traceback
  taken later still works, and `PythonState::unexpose_frames()` in `TPythonState.cpp` walks it
  again on the way back in. Both are guarded by `GREENLET_PY312`, and CPython 3.12 measures the
  same flat out (230 ns per switch pair against 237 on 3.14, one run each), so this is not a
  3.14 regression.
- **Recursion *through C* is the other cost, and that one really is the memcpy.** Forcing a C
  frame per level on desktop (recursing through `map`) moved the saved stack from 1,416 bytes to
  51,880 at 50 levels and 404,616 at 400, and the switch pair from 215 ns to 17,803. A greenlet
  parked inside a deep chain of C calls copies hundreds of kilobytes on every switch, in both
  directions.
- **A parked greenlet you keep a reference to is a leak, and one you drop raises `GreenletExit`
  inside itself.** Dropping the last reference to a suspended greenlet raises
  `greenlet.GreenletExit` at its `switch()`. Keep the reference and never resume it and nothing
  happens at all: it stays `dead == False` holding its saved stack forever. Kill it deliberately
  with [`gl.throw()`](https://greenlet.readthedocs.io/en/latest/greenlet.html#greenlet.greenlet.throw),
  which is what the example does in a `finally` after every timing loop.
- **Three ways the exit path goes wrong, all of them quiet.** Catching `GreenletExit` and
  returning normally is allowed and silent. Raising a *different* exception while dying gets
  printed as `Exception ignored in: <greenlet.greenlet object …>` with a traceback and then
  swallowed. Calling `switch()` back to the parent from inside the `except GreenletExit:`
  handler prints `GreenletExit did not kill <greenlet …>` to stderr and leaves the greenlet
  suspended forever — it never resumes past that switch. On device every one of those lines goes
  to `console.log` and nowhere else.
- **Switching to a dead greenlet returns instead of raising.** `gl.switch("x")` on a finished
  greenlet hands `"x"` straight back and control goes to its parent, so a scheduler bug shows up
  as a value appearing from nowhere rather than as an exception. `bool(gl)` is `False` once it is
  dead and `gl.dead` is `True`; test one of those, not the return value.
- **Exceptions cross a switch intact, and contextvars do not.** An exception raised inside a
  greenlet propagates out of the `switch()` that started it with its traceback attached. A
  [`ContextVar.set()`](https://docs.python.org/3/library/contextvars.html#contextvars.ContextVar.set)
  inside a greenlet does *not* escape it: each greenlet carries its own `contextvars.Context` in
  `gr_context`, because `GREENLET_USE_CONTEXT_VARS` is true on every slice. Code that sets a
  request id in a greenlet and reads it back on the main one gets the old value and no error.
- **The recursion limit still applies inside a greenlet.** With `sys.setrecursionlimit(5000)` a
  greenlet reached 4,998 frames before `RecursionError` — greenlet gives you a new stack, not a
  new limit. The example raises the limit at import because one of its panels parks 1,000 frames
  deep and the default is 1,000.
- **It is not asyncio and it does no I/O.** There is no scheduler, no event loop and no socket in
  this package — `switch()` is the entire concurrency model, and something has to decide who runs
  next. If what you want is concurrent I/O in a Flet app,
  [`asyncio`](https://flet.dev/docs/getting-started/async-apps/) is already there and is the
  cheaper answer; reach for greenlet when a library demands it or when you need to suspend a
  *synchronous* call stack you do not control.
- **The C API is exported for other extensions.** `greenlet._C_API` is a
  [`PyCapsule`](https://docs.python.org/3/c-api/capsule.html) named `greenlet._C_API`, and the
  wheel ships `greenlet.h` under its `.data/headers/` directory plus the full C++ source tree.
  That is how gevent and friends call `PyGreenlet_Switch` from C. Nothing in an app needs it, and
  `flet build` removes those sources from the device payload by default.
- **`greenlet.__version__` comes from a `.py` file** (`greenlet/__init__.py`), so it reports what
  the Python layer says and not what the extension is. There is no second version constant to
  cross-check it against.

## Build notes (maintainers)

### Recipe shape

The recipe is `meta.yaml` and nothing else. There are no patches and no `build.sh`, which is
earned rather than lucky: upstream's `setup.py` declares three `Extension`s from C++ sources
with no `libraries`, no `library_dirs` and no `sys.platform` branch that a mobile target trips,
and the whole per-architecture selection happens in the preprocessor via
`greenlet/slp_platformselect.h`. A bump that suddenly needs a patch means upstream restructured.

**The `CXXFLAGS: -std=c++14` line does more than it looks like, and nothing else records
this.** It is gated to the non-Android platforms, so in practice it is the iOS build only. Two
findings, from a desktop build of the same sdist and from the sources of the tools involved:

- **It replaces the C++ flags rather than adding to them.** `src/forge/build.py` appends
  `script_env` values only for `LDFLAGS`, `CFLAGS` and `CPPFLAGS`; every other key is assigned.
  setuptools' `customize_compiler` then takes `os.environ["CXXFLAGS"]` as the *entire* C++ flag
  set. Probed directly with setuptools 80.9.0: with `CXXFLAGS` unset the C++ command is
  `c++ -fno-strict-overflow … -DNDEBUG -g -O3 -Wall -O3 -arch arm64 … -fPIC`; with
  `CXXFLAGS=-std=c++14` it is `c++ -std=c++14`, and nothing else. Forge's own iOS `CFLAGS` —
  `… -DNDEBUG -g -O3 -Wall -mios-version-min=13.0 -I…iPhoneOS.sdk/usr/include`, read from a
  build log — never reaches the C++ compile. That is why the iOS slices carry live assertions
  and unoptimised code, and why `__text` on the cp314 iOS device slice is 86,048 bytes against a
  58,044-byte `.text` on Android arm64-v8a and 39,396 bytes for the same source at `-O3` on a
  desktop.
- **Whether it selects C++14 at all depends on a branch that reads differently when cross
  compiling, and it cannot be settled from the wheel.** `setup.py` appends `--std=c++11` to
  `extra_compile_args` when `sys.platform == 'darwin' or 'clang' in platform.python_compiler()`,
  and `extra_compile_args` land *after* the flag set on the command line, so where that append
  happens the later flag wins. It happens on a desktop macOS build: the observed compile line
  ends `… -c src/greenlet/greenlet.cpp -o … --std=c++11`, via the `darwin` arm. In a cross env
  neither arm holds. crossenv's `sys-patch` sets `sys.platform` from the host platform triple, so
  it is `'ios'` (and `'android'`), never `'darwin'`; and the fallback test is case-sensitive
  `'clang'` while `platform.python_compiler()` on the build interpreter returns `'Clang 22.1.3 '`
  with a capital C, so it is `False` there too. On the cross build the recipe's `-std=c++14` is
  therefore the only `-std=` on the line. Nothing in the shipped binaries can confirm that:
  compiling `greenlet.cpp` at `-std=c++11` and at `-std=c++14` gives objects of identical size
  (258,480 bytes), identical symbol count (1,394) and identical `__text` (0x149fc), so the
  standard leaves no fingerprint the way `NDEBUG` and `-O` do.

Two further shape facts that no other file holds. The Android slices reach thread-local storage
through `__emutls_get_address` and `__cxa_thread_atexit` where the iOS ones use Darwin's native
`__tlv_bootstrap`/`__tlv_atexit`, and greenlet reads its per-thread state on every switch — a
plausible source of an Android/iOS gap, which did not appear: the measured switch pairs came out
within 10% of each other. And the iOS slices are unstripped, keeping a full symbol table (1,135
`nm` entries on the cp314 device slice, 994 of them defined); `strip -x` takes that file from
280,832 to 233,880 bytes, so roughly 47 KB of each iOS wheel is symbol table. Together with the
missing `-O` that is why the iOS wheels are the top of the size range quoted in
[App size](#app-size).

### Upgrade hazards

- **The `script_env` block is the open defect, and the experiment is cheap.** Delete it, rebuild
  the three iOS slices, and check that `___assert_rtn` is gone from the undefined symbols. If a
  flag really is needed on the C++ compile, `CPPFLAGS` is the place: forge appends it, and
  setuptools appends it to the C++ line *after* the optimisation flags rather than in place of
  them — probed with the same setuptools, `CPPFLAGS=-DPROBE=1` leaves `-DNDEBUG -g -O3 … -fPIC
  -DPROBE=1`. It still loses to anything in `extra_compile_args`, so check what upstream puts
  there before relying on a `-std=` in it. Fixing this invalidates every iOS timing on this page,
  in the good direction.
- **A CPython that changes the interpreter-frame layout, or an upstream that finds a cheaper
  `expose_frames`, moves the depth tables by an order of magnitude.** Both walks are
  `GREENLET_PY312`-guarded. The "park shallow greenlets" advice and both tables under
  [Depth and cost](#depth-and-cost) and [Things to know](#things-to-know) depend on them.
- **Upstream publishes no Android or iOS wheels today**, so this index is the only source and
  there is no shadowing decision to make. The day that changes, the build tag decides ties and it
  should be a deliberate choice — check before bumping.

### Re-verification checklist

- **That the right switch header is still selected per slice.** This is the only claim on the
  page that a passing import does not cover — `import greenlet` loads the module, and
  `test_switch` in `tests/` is what actually executes the assembly. `slp_platformselect.h` is a
  preprocessor ladder, so a toolchain that stops defining `__thumb__`, or a new upstream branch
  for Apple silicon, changes which page of assembly is compiled without changing anything a build
  log shows. Each header leaves a fingerprint that is easy to find in a disassembly, because
  nothing else in the module writes the stack pointer from a register:

  | slice | header | fingerprint, once per slice |
  | --- | --- | --- |
  | Android arm64-v8a, iOS device, iOS arm64 sim | `switch_aarch64_gcc.h` | `add sp, sp, x8` then `add x29, x29, x8`, under a prologue saving `x19`–`x28`, `x30`, `d8`–`d15` |
  | Android armeabi-v7a | `switch_arm32_gcc.h`, `__thumb__` branch | `add sp, r0` then `add r7, r0` — `r7` because the slice is Thumb-2 — under `push {r4-r7,lr}` / `push.w {r8-r11}` / `vpush {d8-d15}` |
  | Android x86_64, iOS x86_64 sim | `switch_amd64_unix.h` | `fnstcw`/`stmxcsr`/`ldmxcsr`/`fldcw`, saving the x87 control word and `MXCSR` |
  | Android x86 (legacy 32-bit) | `switch_x86_unix.h` | `fnstcw`/`fldcw`, which is all that header saves |

  The Android slices are stripped, so the `$a`/`$t` mapping symbols are gone and `objdump`
  decodes armeabi-v7a as ARM by default: pass `--triple=thumbv7a-linux-androideabi` or the
  disassembly is fiction.
- **`NDEBUG` and optimisation, per platform.** `___assert_rtn` (iOS) or `__assert2` (Android) in
  the undefined symbols is the one-command check, and the `__text`/`.text` sizes are the
  corroboration. Both are consequences of `script_env`, so they change the moment anyone edits it.
- **The Android linkage.** `libc++_shared.so` still in `DT_NEEDED` on every Android slice, and
  `flet-libcpp-shared` still in the Android `METADATA` and absent from the iOS one. Losing the
  requirement produces a wheel that builds, installs, and fails at `dlopen failed: library
  "libc++_shared.so" not found` on device. The same applies to one of the two test extensions:
  `_test_extension_cpp` needs it, `_test_extension` is plain C and does not.
- **The extension filenames, per slice.** They must keep a CPython ABI tag: serious_python's
  Gradle step relocates every ABI-tagged extension into `jniLibs`, mangling dots to dashes
  (`greenlet/_greenlet.…so` → `libgreenlet-_greenlet.so`) and leaving a `.soref` marker behind, so
  an untagged `NAME.so` is never relocated and becomes a silent `ModuleNotFoundError` on device.
  That covers `greenlet/tests/`'s two extensions too. The 3.12 Android slices name the extension
  `_greenlet.cpython-312.so` without the platform triplet where 3.13 and 3.14 use the full
  `_greenlet.cpython-31X-<triplet>.so`; both spellings match the tag the relocation keys on, but
  the untripleted form means the 3.12 Android slices cannot be told apart by filename — so check
  each one's `e_machine` if a 3.12 Android wheel ever imports on one ABI and not another.
- **iOS mach-o filetype.** `otool -hv` must report `DYLIB`, not `BUNDLE`, on every iOS slice, or
  the app fails at link time with *Unsupported mach-o filetype (only MH_OBJECT and MH_DYLIB can be
  linked)*.
- **Android 16 KB `PT_LOAD` alignment**, which Android 15 requires.
- **The sizes and the timings.** Re-measure the compressed and unpacked ranges from the resulting
  wheels rather than scaling the old figures, and re-run the example on an emulator and a
  simulator: [Depth and cost](#depth-and-cost) and [App size](#app-size) are the consumer claims
  a bump silently invalidates.

### Coverage gaps

`tests/test_greenlet.py` covers three things: that `import greenlet` loads the extension (the
`libc++_shared.so` canary on Android), a two-greenlet ping-pong asserting the exact interleaving,
and that a returned greenlet reports `dead`. It does not exercise deep recursion across a switch,
which is the stack-copy half of the switch; an exception propagating out of a greenlet with its
traceback, which is the exception-state save/restore path; `throw()` into a parked greenlet or
the `GreenletExit` a dropped one receives, which is the lifecycle path; contextvars isolation; or
a greenlet driven from a non-main thread, even though every consumer path on a phone is a
`run_thread` worker. The [example](examples/coroutine-switch) carries all of those as on-screen
checks, which is the wrong home for them — move them into `tests/` at the next touch.
