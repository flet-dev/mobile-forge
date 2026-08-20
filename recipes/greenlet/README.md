# greenlet

[`greenlet`](https://greenlet.readthedocs.io) gives CPython stackful coroutines: a
`greenlet` object owns a real machine stack, and `switch()` moves the CPU from one to another
and back again, from any depth, in the middle of anything. That is not portable C. The
switch is a page of hand-written inline assembly per architecture, chosen at compile time by
`greenlet/slp_platformselect.h`, and the whole question a mobile wheel has to answer is
whether the right page was chosen and whether it survives the toolchain.

It is worth having because other people's libraries need it. SQLAlchemy's asyncio extension
is a greenlet bridge — 2.0.52 lists `greenlet>=1` under the `asyncio`, `aiosqlite`,
`asyncmy`, `aioodbc`, `aiomysql` and `postgresql-asyncpg` extras, and again as a base
requirement gated on `platform_machine` — so an async engine that resolves without it fails
at the first `await`, not at import. `gevent` 26.8.0 requires `greenlet>=3.2.2` on CPython
and `playwright` 1.62.0 requires `greenlet>=3.1.1,<4`; neither of those has a wheel on this
index, so on a phone the realistic consumer is SQLAlchemy's bridge — see
[`sqlalchemy`](../sqlalchemy) — plus whatever you build on `switch()` yourself.

**What the shipped binaries say about the assembly, checked slice by slice.** The selector
routes `__aarch64__` to `platform/switch_aarch64_gcc.h`, 32-bit `__arm__` to
`switch_arm32_gcc.h`, `__amd64__` to `switch_amd64_unix.h` and `__i386__` to
`switch_x86_unix.h`, and each of those leaves a fingerprint that is easy to find in a
disassembly because nothing else in the module writes the stack pointer from a register:

| slice | header | fingerprint, found once per slice |
| --- | --- | --- |
| Android arm64-v8a, iOS device, iOS arm64 sim | `switch_aarch64_gcc.h` | `add sp, sp, x8` then `add x29, x29, x8`, under a prologue saving `x19`–`x28`, `x30`, `d8`–`d15` |
| Android armeabi-v7a | `switch_arm32_gcc.h`, `__thumb__` branch | `add sp, r0` then `add r7, r0` — `r7` because the slice is Thumb-2 — under `push {r4-r7,lr}` / `push.w {r8-r11}` / `vpush {d8-d15}` |
| Android x86_64, iOS x86_64 sim | `switch_amd64_unix.h` | `fnstcw`/`stmxcsr`/`ldmxcsr`/`fldcw`, saving the x87 control word and `MXCSR` |
| Android x86 (legacy 32-bit, 3.12 only) | `switch_x86_unix.h` | `fnstcw`/`fldcw`, which is all that header saves |

In the arm64 and armeabi-v7a disassemblies the three return paths (`-1`, `1`, `0`) that
`SLP_SAVE_STATE` produces sit around the pair. All nineteen wheels were checked this way and
every one matches its architecture, at exactly one occurrence per slice.

Whether it *runs* is a device question, which is what
[`coroutine-switch`](examples/coroutine-switch) is for: its eight-check panel covers a
50,000-switch accumulator, a 1,000-frame unwind across a switch, an exception carrying its
traceback out of a greenlet, `throw()` into a parked one, `GreenletExit` on a dropped one,
the cross-thread refusal, contextvars isolation, and the switch to a dead greenlet.

**On-device numbers are not filled in yet.** Everything measured below was measured on a
desktop or read out of the published wheels, and each claim says which. The desktop
reference is CPython 3.14.6 on an Apple M4, macOS 26.6, greenlet 3.5.1 from PyPI: a switch
pair costs **237 ns**, a generator `next()` 23 ns, and a round trip between two OS threads
through two queues 3,260 ns. Read that as the shape rather than the magnitude — a greenlet
switch is an order of magnitude dearer than a generator resume and an order of magnitude
cheaper than waking another thread.

**The iOS slices are compiled without optimisation, and it costs about 7× on the switch.**
This is the one thing on this page that would change what you build. The evidence is in the
wheels: every iOS slice imports `___assert_rtn` and carries live assertion text
(`this->_stack_start == nullptr`, `p->pimpl == nullptr`, …) tagged with the source files they
came from, while every Android slice imports no assert symbol and carries none — so `NDEBUG`
is defined for Android and not for iOS. `__text` on the cp314 iOS device slice is 86,048 bytes
against a 58,044-byte `.text` on Android arm64-v8a. The cause is in the recipe and
[Build notes](#build-notes-maintainers) has it; the price was measured by reproducing the
flag on a desktop build of the same sdist, where the switch pair went from 228 ns to
**1,601 ns**, `create + run` from 1,809 ns to 4,233 ns, and the machine stack copied per
switch from 1,384 to 2,456 bytes. Expect the iOS device figures to sit well above Android's
for that reason and not because of anything about the CPU.

**Measured on device, 2026-08-20**, on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6 — and the hand-written assembly works on both. All of the
correctness checks passed on each platform: 50,000 switches keep an accumulator exact at
1,249,975,000, 1,000 frames unwind after a switch, an exception crosses the switch carrying its
traceback, `throw()` lands inside a parked greenlet, dropping one raises `GreenletExit` in it,
switching to another thread's greenlet is refused, each greenlet carries its own `contextvars`
context, and switching to a dead greenlet returns rather than raising. All of it ran on a Flet
`page.run_thread` worker, not the main thread.

**The "greenlets are far cheaper than threads" claim does not survive the platform change, and
you should quote the iOS number.** A switch pair costs 1,623 ns on iOS and 1,789 ns on Android —
close. A thread round trip costs **2,979 ns on iOS and 396,687 ns on Android**, so greenlets look
1.8× cheaper than threads on the simulator and 222× cheaper on the emulator. The emulator's
thread handoff is the outlier, not greenlet. A plain generator beats both everywhere (24 ns iOS,
96 ns Android), which is the honest recommendation when you do not need to suspend mid-callstack.

**Depth is the real cost, and it is not the stack copy.** The bytes saved per switch stay
constant with depth — 2,504 B on iOS and 1,448 B on Android at 0, 100 and 1,000 parked frames —
while the switch itself goes 1,614 → 3,088 → 17,824 ns on iOS and 1,109 → 3,795 → 102,053 ns on
Android. Park shallow greenlets.

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
desktop wheels for every host you would build from. The 3.5.1 release is 79 files — 78
wheels covering CPython 3.10 through 3.15 on macOS (`universal2`), Linux (`manylinux_2_24`
× x86_64, aarch64, ppc64le and s390x, `musllinux_1_2` × x86_64 and aarch64, plus
`manylinux_2_39_riscv64`) and Windows (`win_amd64`, `win_arm64`), with free-threaded
variants from 3.14, and an sdist. **Not one of those 79 files carries an Android or iOS
tag**, which is why this recipe exists; there is no upstream
mobile wheel for a bare requirement to prefer, and none to fall back to if you pin.
`Requires-Python` is `>=3.10` on every wheel, which is also Flet's floor.

**If greenlet is here for SQLAlchemy, ask for it by name or take the extra.** SQLAlchemy's
*base* `greenlet` requirement carries a `platform_machine` marker — `aarch64`, `ppc64le`,
`x86_64`, `amd64`, `AMD64`, `win32`, `WIN32` — and pip evaluates markers against the machine
doing the build rather than the target, so on an Apple Silicon Mac (`platform_machine` is
`arm64`) it is simply false. Measured with `pip download --only-binary :all: --platform
android_24_arm64_v8a --python-version 3.14` against PyPI plus `https://pypi.flet.dev/`: a bare
`sqlalchemy` fetched `sqlalchemy-2.0.52-py3-none-any.whl` and `typing_extensions` and **no
greenlet**, while `sqlalchemy[asyncio]` fetched this index's greenlet wheel and
`flet-libcpp-shared` behind it. An app that resolves without greenlet builds, installs and
starts, then fails at the first `await` — so name `"sqlalchemy[asyncio]"` or `"greenlet"`
yourself instead of relying on that marker.

Nineteen wheels at build number 1: Python 3.12 across all four Android ABIs (arm64-v8a,
armeabi-v7a, x86_64 and the legacy 32-bit `android_24_x86`) and 3.13 and 3.14 across three
each, plus all three iOS slices — device, arm64 simulator, x86_64 simulator — for each of
the three Pythons. No architecture is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. They are 231–268 KB to download and 650–983 KB unpacked.

**One wheel comes along on Android and none on iOS.** Both `METADATA`s carry the five
extras-gated requirements upstream declares (`Sphinx`, `furo`, `objgraph`, `psutil`,
`setuptools`, none of which an app resolve pulls); on top of those the Android one carries a
single unconditional `Requires-Dist: flet-libcpp-shared (>=27.2.12479018)` and the iOS one
carries nothing. Resolved with pip against PyPI plus `https://pypi.flet.dev` for cp312 and
cp314 on `android_24_arm64_v8a`, `android_24_armeabi_v7a` and `android_24_x86_64`, every
Android resolve pulled `flet_libcpp_shared 27.3.13750724` build 10 — 407 KB / 350 KB /
417 KB per ABI, holding one `opt/lib/libc++_shared.so` of 1,292,904 / 872,872 / 1,252,080
bytes — and both iOS resolves pulled greenlet alone. The reason is in
[Android notes](#android-notes).

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. `greenlet/__init__.py` is thirteen `from ._greenlet import …` lines and a
version string; it never touches `__file__`, `importlib.resources` or `pkgutil`. The only
three `__file__` reads in the whole wheel are in `greenlet/tests/`, which nothing in an app
imports. The extension carries a CPython ABI tag on every slice, which is what
serious_python's Android packaging keys on when it relocates a module into `jniLibs`.

**Nothing here opens a file, reads an environment variable or touches the network**, so
there is no cache directory to point at Flet's app storage and no variable to set before
importing. Outside CPython's own API the Android arm64 slice imports 59 non-CPython
symbols: the C++ runtime and its exception machinery,
`malloc`/`free`/`memcpy`/`memmove`/`memset`/`strlen`, three
`pthread_rwlock_*`, `clock`, `getpid`, `abort`, `syscall`, `dl_iterate_phdr`,
`__register_atfork` and the `stderr`/`fprintf`/`fwrite`/`fflush` group it uses to complain.
The iOS arm64 device slice imports 51, the same C++ runtime and libc core in Darwin
spelling, with `___assert_rtn` and `__tlv_bootstrap`/`__tlv_atexit` where Android has
`__emutls_get_address` — and without `memmove`, the three `pthread_rwlock_*`, `getpid`,
`abort`, `syscall`, `dl_iterate_phdr`, `__register_atfork`, `fwrite` or `fflush`. What
matters is what neither list has: `open`, `fopen`, `getenv`, `mmap`, `stat` and any socket
call are absent on both.

**What actually reaches the device is 453 KB, of which 297 KB is upstream's test suite.**
The wheel is 96 files, and `flet build` passes `--cleanup-packages` by default, whose junk
list (`junkFilesMobile` in serious_python's `package_command.dart`, read at 4.5.1 — the
mobile list is the desktop one plus `**.exe`, `**.dll` and `bin`) includes `**.c`,
`**.h`, `**.cpp` and `**.hpp`: that removes 56 files and 360,809 bytes of the C++ sources
greenlet ships for its C API, leaving 40 files. Those 40 are three `.so` files
(182,088 bytes), 26 Python modules, five Windows leftovers the glob list does not name
(`switch_x64_masm.asm`/`.obj`, `switch_arm64_masm.asm`/`.obj` and a `.cmd`, 5,053 bytes of
code that will never run), and the `dist-info`. Measure the payload *after* the compile
step, not from the wheel: `compile.packages` is on by default and serious_python runs
`compileall -b` and deletes the `.py` files **before** the junk pass, so the 183,303 bytes
of source become 251,527 bytes of `.pyc` and the 40 files land at 453,115 bytes. Every
`.pyc` total here moves by roughly 150 bytes per file with the install path, which each
one records in `co_filename`, so re-measuring under a longer path gives slightly larger
figures without anything having changed.
`greenlet/tests/` alone is 26 of those files and 296,858 bytes, including two extension
modules built solely to test greenlet's C API.
`[tool.flet.cleanup] package_files = ["greenlet/tests"]` is the lever — serious_python
appends those globs to its own list and deletes a matching directory recursively — though no
build on this page was run with it set.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`coroutine-switch`](examples/coroutine-switch) — switch cost against a generator and a
  thread, how it grows with the depth of the parked greenlet, eight conformance checks over
  the paths the assembly has to get right, and two greenlets that fail to beat the GIL.

## Threading

**A greenlet is not a thread and never becomes one.** The extension imports no
`PyEval_SaveThread`, no `PyEval_RestoreThread` and no `PyGILState_*` symbol on any of the
nineteen slices — the five thread-state calls it does import are `PyThreadState_Get`,
`GetDict`, `GetFrame`, `EnterTracing` and `LeaveTracing` — so the GIL is never dropped and
two greenlets never run at once. Measured on desktop with the example's own `gil_ratio()`,
which times 400,000 multiplies done twice against the same work split across two greenlets:
three runs gave **1.05×, 1.00× and 0.96×** — one, within the noise of an 18 ms measurement.
Greenlets buy you interleaving and a call stack you can park; they do not buy you a second
core, and neither do threads while the GIL is there.

**Greenlets belong to the thread that created them**, and this is the rule that decides how
they fit into Flet. Every thread gets its own main greenlet — `greenlet.getcurrent().parent`
is `None` on each — and switching to a greenlet created on a different thread raises
`greenlet.error` rather than corrupting anything. Verified on desktop, and the two spellings
are worth recognising: while the owning thread is alive the message is
`Cannot switch to a different thread` followed by a `Current:`/`Expected:` dump of both
greenlets; once greenlet's cleanup for that thread has run it becomes the one-line
`cannot switch to a different thread (which happens to have exited)`. Which one you get is
not a reliable signal — upstream's own test suite waits for pending cleanups before it dares
assert the second — and `dead` separates the two cases in only one direction: a greenlet that
had actually started reports `dead == True` once its thread has gone, while one that was never
started stays `False` through the join, the failed switch and a `gc.collect()`.
Catch `greenlet.error`; do not test `dead` to find out whose thread a greenlet belongs to.

So [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is
where a greenlet workload belongs, and a whole greenlet graph must live inside one worker.
Two consequences worth stating plainly:

- **Create and drive the greenlets inside the worker.** A greenlet built in an event handler
  and switched to from a `run_thread` worker will raise, and the raise is invisible —
  `run_thread` never retrieves the worker's future, so a `greenlet.error` there produces no
  log, no dialog and no crash. Wrap the worker body in `try/except`, and end it with an
  explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
  auto-update does not reach background threads. The
  [example](examples/coroutine-switch) does both, and it runs every measurement inside
  `run_thread` precisely so a green result also proves greenlets work off the main thread.
- **Cooperative means cooperative.** A greenlet yields only where you wrote `switch()`. A
  blocking call inside one blocks the OS thread it is on, and therefore every other greenlet
  on that thread, with no preemption to save you. On the UI thread that is a frozen app; the
  reason to keep this in a worker is not throughput, it is that a greenlet cannot be
  interrupted.

For SQLAlchemy the whole bridge is internal — you write `async with engine.begin()` and
greenlet is what carries the `await` across the sync driver call — so the rule reduces to
running the async engine on one thread's event loop and not sharing greenlet-backed
connections across `run_thread` workers.

## Android notes

- **`libc++_shared.so` is the reason `flet-libcpp-shared` is a requirement.** `DT_NEEDED` on
  all ten Android slices is `libm.so`, `libpython3.<minor>.so`, `libc++_shared.so`,
  `libdl.so`, `libc.so`, with no `SONAME`, no `RPATH` and no `RUNPATH`. greenlet is C++ —
  it throws real C++ exceptions and the undefined list includes `__cxa_throw`,
  `__gxx_personality_v0` and `std::runtime_error` — and the NDK's C++ runtime is a separate
  library on Android. Drop the requirement and the wheel still builds and installs, and the
  app dies at import with `dlopen failed: library "libc++_shared.so" not found`. The same
  applies to one of the two test extensions: `_test_extension_cpp` needs it,
  `_test_extension` is plain C and does not.
- **Three native libraries land in `jniLibs` per ABI, and two of them are test code.**
  serious_python's Gradle step relocates every ABI-tagged extension and mangles the dotted
  name by replacing dots with dashes (`mangledLib` in
  serious_python_android's `android/build.gradle.kts`, read at 4.5.1), leaving a `.soref` marker
  behind: `greenlet/_greenlet.…so` → `libgreenlet-_greenlet.so`,
  `greenlet/tests/_test_extension.…so` → `libgreenlet-tests-_test_extension.so`, and
  `…_test_extension_cpp` likewise. Nothing collides with a system library. Read from
  serious_python's source, not from a built APK.
- **Thread-local storage is emulated.** The Android slices import `__emutls_get_address` and
  `__cxa_thread_atexit`, where the iOS ones use Darwin's native `__tlv_bootstrap` and
  `__tlv_atexit`. greenlet keeps its per-thread state in `thread_local` storage and reads it
  on every switch, so this is a plausible source of an Android-versus-iOS gap in the switch
  cost that has nothing to do with the assembly. Worth remembering when the device numbers
  arrive and the two platforms disagree.
- **armeabi-v7a is a genuine Thumb-2 build, and its switch uses `r7` as the frame pointer.**
  `switch_arm32_gcc.h` picks `REG_FP` by `#ifdef __thumb__`, and the shipped slice takes the
  Thumb branch: `add sp, r0` / `add r7, r0` with `r7` saved in the prologue. Its `.text` is
  27,448 bytes against 58,044 on arm64-v8a. Beware when re-checking: the Android slices are
  stripped, so the `$a`/`$t` mapping symbols are gone and `objdump` decodes Thumb-2 as ARM
  by default — pass `--triple=thumbv7a-linux-androideabi` or the disassembly is fiction.
- **Every `PT_LOAD` segment is 16 KB aligned**, which Android 15 requires. arm64-v8a and
  x86_64 are `ELF64`; armeabi-v7a and the legacy `android_24_x86` slice are `ELF32`.
- **The 3.12 Android slices name the extension `_greenlet.cpython-312.so`, without the
  platform triplet**, while 3.13 and 3.14 use the full
  `_greenlet.cpython-31X-<triplet>.so`. Both spellings match the
  `\.(cpython-[^/]+|abi3)\.so$` tag the `jniLibs` relocation keys on, so both work, but the
  untripleted form means the three 3.12 Android slices cannot be told apart by filename. The
  `e_machine` of each was checked and every slice is the right architecture; this is the
  first thing to look at if a 3.12 Android wheel ever imports on one ABI and not another.

## iOS notes

- **The extensions are `MH_DYLIB`, which is what Flet 0.86 needs.** `otool -hv` reports
  filetype `DYLIB` (not `BUNDLE`) on all nine iOS slices, so the *Unsupported mach-o filetype
  (only MH_OBJECT and MH_DYLIB can be linked)* failure at app link time does not arise here.
  `otool -L` names three libraries besides the extension's own install name:
  `@rpath/Python.framework/Python`, `/usr/lib/libc++.1.dylib` and `/usr/lib/libSystem.B.dylib`.
  The C++ runtime is part of iOS, which is why nothing like `flet-libcpp-shared` appears in
  the iOS `METADATA`.
- **They are built without `-O` and without `-DNDEBUG`.** Every iOS slice imports
  `___assert_rtn` and embeds the text of the assertions it can trip, together with the
  source-file names they came from: fifteen of greenlet's own on every slice (`TGreenlet.cpp`,
  `TStackState.cpp`, and whichever `switch_*.h` its own architecture selected) plus the CPython
  headers whose inline functions assert, which grow with the interpreter — three on cp312
  (`object.h`, `listobject.h`, `tupleobject.h`), four on cp313 (`pycore_frame.h` joins) and six
  on cp314, where `pycore_frame.h` becomes `pycore_interpframe.h` and `refcount.h` and
  `pycore_stackref.h` join it. No Android slice imports an assert symbol or embeds one of those
  strings. `__text` is 86,048 bytes on the cp314 device slice where the same source at `-O3` on
  a desktop compiles to 39,396. The recipe line responsible
  and the experiment to run are in [Build notes](#build-notes-maintainers); the measured cost
  is in the opening section. Two practical consequences until it changes: assertion failures
  in a shipped iOS build call `abort()` rather than being compiled out, and iOS switch
  timings from the [example](examples/coroutine-switch) should not be read as a statement
  about Apple silicon.
- **The iOS slices are not stripped.** Each keeps a full symbol table — `nm` lists 1,135
  entries on the cp314 device slice, 994 of them defined — which is why the static
  `slp_switch` is still findable there as `__ZL10slp_switchv` and is inlined beyond
  recognition on Android. `strip -x` takes that file from 280,832 to 233,880 bytes, so about
  47 KB of each iOS wheel is symbol table.
- **The iOS wheels are the biggest of the nineteen**, 832–983 KB unpacked against 650–746 KB
  for Android, and both of the preceding bullets are why.

## Things to know

- **A switch is not O(1). It is O(the parked greenlet's Python frame depth), on every
  CPython the mobile wheels target.** Measured on desktop with the example's own helpers,
  CPython 3.14.6, best of three:

  | frames parked | machine stack copied | ns per switch pair |
  | --- | --- | --- |
  | 0 | 1,416 B | 223 |
  | 100 | 1,416 B | 712 |
  | 1,000 | 1,416 B | 7,082 |

  The two columns disagree, and that is the point. Since 3.11 a Python-to-Python call does
  not recurse in C, so a thousand Python frames cost no extra machine stack and the memcpy
  stays flat — yet the switch gets 32× dearer. The cause is in the shipped source:
  `Greenlet::expose_frames()` in `TGreenlet.cpp` walks the entire `_PyInterpreterFrame` chain
  every time a greenlet is switched away from, so that a traceback taken later still works,
  and `PythonState::unexpose_frames()` in `TPythonState.cpp` walks it again on the way back
  in. Both are guarded by `GREENLET_PY312`, and CPython 3.12 measures the same flat out
  (230 ns per switch pair against 237 on 3.14, one run each), so nothing about this is a
  3.14 regression. Design for shallow greenlets: park at the top of a call stack, not the
  bottom of one.
- **Recursion *through C* is the other cost, and that one really is the memcpy.** Forcing a
  C frame per level on desktop (recursing through `map`) moved the saved stack from 1,416
  bytes to 51,880 at 50 levels and 404,616 at 400, and the switch pair from 215 ns to 17,803.
  A greenlet parked inside a deep chain of C calls copies hundreds of kilobytes on every
  switch, in both directions.
- **A parked greenlet you keep a reference to is a leak, and one you drop raises
  `GreenletExit` inside itself.** Dropping the last reference to a suspended greenlet raises
  `greenlet.GreenletExit` at its `switch()` — verified on desktop, and one of the example's
  checks. Keep the reference and never resume it and nothing happens at all: it stays
  `dead == False` holding its saved stack forever. Kill it deliberately with
  `gl.throw()`, which is what the example does in a `finally` after every timing loop.
- **Three ways the exit path goes wrong, all of them quiet.** Catching `GreenletExit` and
  returning normally is allowed and silent. Raising a *different* exception while dying gets
  printed as `Exception ignored in: <greenlet.greenlet object …>` with a traceback and then
  swallowed. Calling `switch()` back to the parent from inside the `except GreenletExit:`
  handler prints `GreenletExit did not kill <greenlet …>` to stderr, and the greenlet is left
  suspended forever — it never resumes past that switch. All three were reproduced on
  desktop; on device every one of those lines goes to `console.log` and nowhere else.
- **Switching to a dead greenlet returns instead of raising.** `gl.switch("x")` on a finished
  greenlet hands `"x"` straight back and control goes to its parent, so a scheduler bug shows
  up as a value appearing from nowhere rather than as an exception. `bool(gl)` is `False`
  once it is dead and `gl.dead` is `True`; test one of those, not the return value.
- **Exceptions cross a switch intact, and so do contextvars — in opposite directions.** An
  exception raised inside a greenlet propagates out of the `switch()` that started it with
  its traceback attached (two frames in the example's check). A `ContextVar.set()` inside a
  greenlet does *not* escape it: each greenlet carries its own `contextvars.Context` in
  `gr_context`, because `GREENLET_USE_CONTEXT_VARS` is true on every slice. Code that sets a
  request id in a greenlet and reads it back on the main one gets the old value and no error.
- **The recursion limit still applies inside a greenlet.** With `sys.setrecursionlimit(5000)`
  a greenlet reached 4,998 frames before `RecursionError` on desktop — greenlet gives you a
  new stack, not a new limit. The example raises the limit to 4,000 at import because one of
  its panels parks 1,000 frames deep and the default is 1,000.
- **It is not asyncio and it does no I/O.** There is no scheduler, no event loop and no
  socket in this package — `switch()` is the entire concurrency model, and something has to
  decide who runs next. If what you want is concurrent I/O in a Flet app, `asyncio` is
  already there and is the cheaper answer; reach for greenlet when a library demands it or
  when you need to suspend a *synchronous* call stack that you do not control.
- **The C API is exported for other extensions.** `greenlet._C_API` is a
  `PyCapsule` named `greenlet._C_API`, and the wheel ships `greenlet.h` under
  `greenlet-3.5.1.data/headers/` plus the full C++ source tree. That is how gevent and
  friends call `PyGreenlet_Switch` from C. Nothing in an app needs it, and the sources it
  exists for are removed from the device payload by `--cleanup-packages` — see
  [Install](#install).
- **`greenlet.__version__` comes from a `.py` file** (`greenlet/__init__.py`), so it reports
  what the Python layer says and not what the extension is. There is no second version
  constant to cross-check it against.

## Build notes (maintainers)

The recipe is `meta.yaml` and nothing else: name, version, build number, one Android-only
host requirement, and one `script_env` line for the non-Android platforms. There are no
patches and no `build.sh`, which is earned rather than lucky — upstream's `setup.py` declares
three `Extension`s from C++ sources with no `libraries`, no `library_dirs` and no
`sys.platform` branch that a mobile target trips, and the platform selection all happens in
the preprocessor. A bump that suddenly needs a patch means upstream restructured.

**The `CXXFLAGS: -std=c++14` line needs revisiting, and it is the highest-value thing on this
page.** It applies to every non-Android platform, so it is the iOS build only. Two findings,
worked out on a desktop build of the same 3.5.1 sdist and on the sources of the tools
involved:

- **It replaces the compiler flags rather than adding to it.** `src/forge/build.py` appends
  `script_env` values only for `LDFLAGS`, `CFLAGS` and `CPPFLAGS`; every other key is
  assigned. setuptools' `customize_compiler` then takes `os.environ["CXXFLAGS"]` as the
  *entire* C++ flag set. Probed directly with setuptools 80.9.0: with `CXXFLAGS` unset the
  C++ command is `c++ -fno-strict-overflow … -DNDEBUG -g -O3 -Wall -O3 -arch arm64 … -fPIC`;
  with `CXXFLAGS=-std=c++14` it is `c++ -std=c++14`, and nothing else. Forge's own iOS
  `CFLAGS` — `… -DNDEBUG -g -O3 -Wall -mios-version-min=13.0 -I…iPhoneOS.sdk/usr/include`,
  read from a build log — never reaches the C++ compile. That is why the iOS slices carry
  live assertions and unoptimised code, per [iOS notes](#ios-notes).
- **Whether it selects C++14 at all depends on a branch that reads differently when cross
  compiling, and it cannot be settled from the wheel.** `setup.py` appends `--std=c++11` to
  `extra_compile_args` when `sys.platform == 'darwin' or 'clang' in platform.python_compiler()`,
  and `extra_compile_args` land *after* the flag set on the command line — so where that
  append happens the later flag wins. It happens on a desktop macOS build: the observed
  compile line ends `… -c src/greenlet/greenlet.cpp -o … --std=c++11`, via the `darwin` arm.
  In a cross env neither arm holds. crossenv's `sys-patch` sets `sys.platform` from the host
  platform triple, so it is `'ios'` (and `'android'`), never `'darwin'`; and the fallback
  test is case-sensitive `'clang'` while `platform.python_compiler()` on the build
  interpreter returns `'Clang 22.1.3 '` with a capital C, so it is `False` there too. On the
  cross build the recipe's `-std=c++14` is therefore the only `-std=` on the line. Nothing in
  the shipped binaries can confirm that: compiling `greenlet.cpp` at `-std=c++11` and at
  `-std=c++14` gives objects of identical size (258,480 bytes), identical symbol count
  (1,394) and identical `__text` (0x149fc), so the standard leaves no fingerprint the way
  `NDEBUG` and `-O` do.

What that is worth: on a desktop build with the recipe's flag the switch pair measured
1,601 ns against 228 ns without it, `create + run` 4,233 against 1,809, and `_stack_saved`
2,456 bytes against 1,384 — the unoptimised code spills 78% more machine stack per frame, so
every switch copies more as well as executing more. The experiment is cheap: delete the
`script_env` block, rebuild the three iOS slices, and check that `___assert_rtn` is gone from
the undefined symbols. If a flag really is needed on the C++ compile, `CPPFLAGS` is the place:
forge appends it, and setuptools appends it to the C++ line *after* the optimisation flags
rather than in place of them — probed with the same setuptools, `CPPFLAGS=-DPROBE=1` leaves
`-DNDEBUG -g -O3 … -fPIC -DPROBE=1`. It still loses to anything in `extra_compile_args`, so
check what upstream puts there before relying on a `-std=` in it.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **That the right switch header is still selected per slice**, using the fingerprints in the
  table at the top of this page. `slp_platformselect.h` is a preprocessor ladder, so a
  toolchain that stops defining `__thumb__`, or a new upstream branch for Apple silicon,
  changes which page of assembly is compiled without changing anything a build log shows.
  This is the only claim on the page that a passing import does not cover: `import greenlet`
  loads the module, and `test_switch` in `tests/` is what actually executes the assembly.
- **`NDEBUG` and optimisation, per platform** — `___assert_rtn` (iOS) or `__assert2`
  (Android) in the undefined symbols is the one-command check, and the `__text`/`.text` sizes
  are the corroboration. Both are consequences of `script_env`, so they change the moment
  anyone edits it.
- **The Android linkage**: `libc++_shared.so` still in `DT_NEEDED`, and
  `flet-libcpp-shared` still in the Android `METADATA` and absent from the iOS one. Losing
  the requirement produces a wheel that builds, installs, and fails at `dlopen` on device.
- **The extension filenames**, per slice: they must keep a CPython ABI tag, since an untagged
  `NAME.so` gets no `.soref`, is not relocated into `jniLibs`, and becomes a silent
  `ModuleNotFoundError` on device. That covers `greenlet/tests/`'s two extensions too.
- **Whether upstream has started publishing mobile wheels.** 3.5.1 publishes none, so this
  index is the only source and there is no shadowing decision to make. The day that changes,
  the build tag decides ties and it should be a deliberate choice — check before bumping.
- **The frame-walk cost**, if [Things to know](#things-to-know) is to keep its table:
  `expose_frames`/`unexpose_frames` are `GREENLET_PY312`-guarded, so a CPython that changes
  the interpreter-frame layout, or an upstream that finds a cheaper way, moves those numbers
  by an order of magnitude at depth.

`tests/test_greenlet.py` covers three things: that `import greenlet` loads the extension
(the `libc++_shared.so` canary on Android), a two-greenlet ping-pong asserting the exact
interleaving, and that a returned greenlet reports `dead`. Additions worth making at the next
touch, in rough order of value: **deep recursion across a switch**, since the stack copy is
the half of the switch that the current ping-pong never stresses; an **exception propagating
out of a greenlet with its traceback**, which is the exception-state save/restore path;
`throw()` into a parked greenlet and the `GreenletExit` a dropped one receives, which is the
lifecycle path; and a **greenlet driven from a non-main thread**, since every consumer path
on a phone is a `run_thread` worker and nothing in `tests/` leaves the main thread today.
The [example](examples/coroutine-switch) carries all of those as on-screen checks, which is
the wrong home for them.
