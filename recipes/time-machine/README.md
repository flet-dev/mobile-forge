# time-machine

[`time-machine`](https://github.com/adamchainz/time-machine) moves the clock. You name a
destination with
[`travel()`](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.travel),
and inside the block `time.time()`, `datetime.now()` and most of what CPython offers for
reading the wall clock report that instant instead of the real one — so a test can assert what
a subscription renewal screen shows on the day a trial expires, or what a "3 days ago" label
says, without waiting three days or threading a fake clock through every function that needs
one.

**time-machine patches CPython, not the operating system, and that is what decides which
readings follow.** It does not patch libc, and it does not rebind module attributes the way
`unittest.mock.patch` does. Its extension overwrites the `ml_meth` function pointer in the
`PyMethodDef` structs of nine built-in methods — `time.time`, `time.time_ns`, `time.gmtime`,
`time.localtime`, `time.strftime`, `time.clock_gettime`, `time.clock_gettime_ns`,
`datetime.datetime.now` and `datetime.datetime.utcnow` — and puts the saved pointers back on
exit. Three things follow. A reference bound *before* the trip is patched too, because the
swap is in the method struct and not in a namespace: a `from time import time` captured at
import still returns the fake value. The struct is per-process, so **the patch is not scoped
to a thread** — a worker started before the trip sees the frozen clock. And
`datetime.date.today()` follows without being one of the nine, because it reaches the clock
through the `time` module rather than directly — while anything that reads the clock in C
*without* going through those nine does not follow at all, which is the trap with
[its own section](#what-follows-the-clock-and-what-does-not) below.

**This is a testing library, and shipping it in a production app is almost always the wrong
call.** The patch is a process-global mutation with no owner and no timeout: it stays in place
until something calls `stop()`, and while it is in place it reaches every thread, every
dependency and Flet's own internals. If your app needs a clock it can steer — a demo mode, a
countdown you can fast-forward, a "what does this screen look like next Tuesday" toggle —
inject the clock instead (`def build(now=datetime.now)`, then pass a stub) and keep
time-machine for the tests. What it is genuinely good for on a device is the case in the
[example](examples/frozen-clock): finding out what your app's dependencies actually read the
clock with.

Every figure below is a desktop measurement against the published wheels (Apple M4, macOS
26.6, CPython 3.14.6 and 3.12.13) unless the sentence says otherwise; the Android and iOS
platform facts were read out of an emulator, a simulator and a built app on 2026-08-20.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "time-machine",
]
```

**The pip name is hyphenated and the import name is not.** You install `time-machine`, write
`import time_machine`, and ask `importlib.metadata.version("time-machine")` — the hyphenated
spelling — which build is on the device.

**Pin both sides if the difference could matter to you.** Upstream has releases newer than the
one [`meta.yaml`](meta.yaml) declares, so a bare requirement resolves upstream's latest for
`flet run` on your laptop and this index's for `flet build` — two different releases behind
the same import. The [`frozen-clock`](examples/frozen-clock) example pins both.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`frozen-clock`](examples/frozen-clock) — a frozen clock beside the real one, with thirteen
  ways of asking the time classified as *followed*, *real clock* or *elsewhere*.

## Usage in a Flet app

Wrap the work in a trip and put the result in a control:

```python
import flet as ft
import time_machine


def main(page: ft.Page):
    def preview(e):
        with time_machine.travel("2026-03-01 09:00:00+00:00", tick=False):
            banner.value = renewal_notice()  # whatever reads datetime.now() inside
        page.update()

    page.add(
        banner := ft.Text(),
        ft.Button("Show 1 March", on_click=preview),
    )
```

`travel()` accepts the destination as an ISO string, a `datetime`, a `date` or a float epoch.
`tick=False` freezes it; the default `tick=True` starts there and advances at the real rate.
The returned object is both a context manager and something you can drive by hand with
`.start()` and `.stop()`, which is what a UI toggle needs — a `with` block cannot span two
taps. Either way, keep the trip no longer than the work inside it: the patch is process-global
for as long as it is in place, and `stop()` is the only thing that ends it.
[`Traveller.shift()`](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.Traveller.shift)
moves the destination without leaving the trip.

To ask whether a trip is running, call
[`time_machine.escape_hatch.is_travelling()`](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.escape_hatch).
It is the only member of `escape_hatch` that is safe to call off a trip.

### Threading

**A trip is process-global. There is nothing thread-local about it, and this is the single
most important thing to know before using it in a Flet app.** Two mechanisms make it so: the
`ml_meth` swap happens once in a struct every thread shares, and `time_machine.traveller_stack`
is a plain module-level list. A worker thread started **before** any travel began, then
released inside a `travel(..., tick=False)` block, read `time.time()` as `1000000000.0` and
`datetime.now()` as the destination — while its `time.monotonic()` stayed within 0.0000 s of
the main thread's. A background job you did not think about is on the fake clock too.

**Two overlapping trips corrupt each other, and the failure is silent.** `stop()` pops the
last entry of that shared list without checking who pushed it. Two threads entering `travel()`
at once, thread A to 2001 and thread B to 1980, over 8 runs, all 8 identical:

| | inside its own `with` block | after leaving its own `with` block |
|---|---|---|
| thread A (entered first, to 2001) | **1980** | **2001** |
| thread B (entered second, to 1980) | **2001** | 2026 |

Read the second column twice. **Thread A left its `with` block and time was still fake**,
because the entry it popped was B's and its own was still on the stack; time only came back
when B exited. No exception is raised anywhere in that, and the traveller stack is empty and
correct at the end, so nothing afterwards shows it happened.

This matters in Flet specifically because
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) submits to
a shared thread pool, so two taps in quick succession genuinely overlap — and it never
retrieves the worker's future, so anything the worker raised surfaces nowhere. The fix is the
ordinary one: hold a `threading.Lock` across the whole `with travel(...)` block, or travel
only on one thread. The same 8 runs with a lock were correct 8 times out of 8.

**Freezing the clock does not stall the UI.** asyncio schedules on `time.monotonic()`, which
time-machine does not patch: an `asyncio.sleep(0.3)` inside a frozen block took 0.301 s of
real time while `time.time()` sat at `1000000000.0`. No clock read is on the ordinary repaint
path either, which is why the [example](examples/frozen-clock) can redraw through a trip.

Four Flet controls do read it, in a `default_factory` that runs when the control is
constructed: [`DatePicker.current_date`](https://flet.dev/docs/controls/datepicker/),
`DateRangePicker.current_date`, `CupertinoDatePicker.value` and
[`TimePicker.value`](https://flet.dev/docs/controls/timepicker/). So a picker built during a
trip opens on the destination date — `ft.DatePicker().current_date` came back
`1969-07-20 21:17:40` inside a trip to 1969-07-20 20:17:40 UTC.

### What follows the clock and what does not

The nine patched functions follow, and so do `date.today()` and `datetime.today()`, which
reach the clock through `time` — those eleven names are upstream's
[list of mocked functions](https://time-machine.readthedocs.io/en/latest/usage.html#mocked-functions).
A `logging` record's `created` and `uuid.uuid1()`'s embedded timestamp follow as well, because
both reach the clock through the `time` module.

**`time.ctime()` and `time.asctime()` do not follow, and they sit one line away from things
that do.** Frozen at 2001-09-09, `time.strftime("%Y")` returned `2001` while `time.ctime()`
returned the real `Thu Aug 20 10:30:13 2026` in the same block. `ctime` sits in the same module method table as the
nine functions that *are* patched, so a pointer to swap does exist — upstream simply does not
assign it, and `ctime` goes on reading the system clock.
Anything logging or rendering through `ctime` is quietly telling the truth while the rest of
your app is not — and neither name appears in upstream's
[unmocked time sources](https://time-machine.readthedocs.io/en/latest/usage.html#unmocked-time-sources)
note, which lists NumPy's `np.datetime64("now")` and SQLite.

Two more real-clock leaks, from the same desktop sweep frozen at 1969-07-20: SQLite's
`CURRENT_TIMESTAMP` (SQLite's own C clock) and the `st_mtime` a file gets when you write it
(the kernel's). 10 of 13 readings moved in that sweep — 9 on Android, where `uuid.uuid1()`
drops out for a reason that has nothing to do with this wheel (see
[Things to know](#things-to-know)). The [example](examples/frozen-clock) is that sweep with a
button on it.

**`time.monotonic()`, `time.perf_counter()`, `time.process_time()` and `time.thread_time()`
are never patched**, by design — they measure elapsed time, not dates. If you are freezing the
clock to test a timeout, check which clock the timeout is written against first; `asyncio`,
`threading.Event.wait` and most retry libraries use the monotonic one and will not notice your
trip at all.

### Android

- **There is no readable time-zone database, so `ZoneInfo(...)` fails.** Python's `TZPATH` in
  Flet's Android build is the standard Unix list —
  `/usr/share/zoneinfo:/usr/lib/zoneinfo:/usr/share/lib/zoneinfo:/etc/zoneinfo` — and on an
  Android 14 arm64 emulator **none of those four directories exists**. What the platform has
  instead is bionic's own format, a single 429,558-byte `tzdata` file at
  `/system/usr/share/zoneinfo/tzdata`, which `zoneinfo` cannot read because it opens
  `<TZPATH>/<key>` as a TZif file. The symptom is
  `ZoneInfoNotFoundError: 'No time zone found with key Europe/Paris'`, raised by your own
  `ZoneInfo(...)` call before time-machine ever sees it.
- **Only the destination forms that name an IANA zone are affected.** In the same
  no-database run, `travel("2001-09-09 01:46:40+00:00")`, `travel("2001-09-09 01:46:40")`,
  `travel(1000000000.0)` and `travel(datetime(..., tzinfo=timezone.utc))` all worked.
- **The fix is the pure-Python [`tzdata`](https://pypi.org/project/tzdata/) package** —
  `zoneinfo` falls back to it when the filesystem has nothing. It is a 348,168-byte
  `py2.py3-none-any` wheel, so it resolves for a mobile target without a recipe:

  ```toml
  dependencies = ["flet", "time-machine", "tzdata"]
  ```

### iOS

**Whether iOS itself carries a time-zone database is not established here, so add `tzdata` on
both platforms and stop thinking about it.** `TZPATH` is the same four-entry Unix list. A
booted iPhone 16 simulator (iOS 18.6) does resolve `/usr/share/zoneinfo` →
`/var/db/timezone/zoneinfo`, but **that is the host Mac's database, not one iOS ships**: the
iOS 18.6 `RuntimeRoot` contains no `zoneinfo` directory anywhere under it, and `stat` on
`Europe/Paris` returns the same device:inode inside the simulator as on the host. A simulator
run therefore proves nothing about a phone, and no physical device was available for this
page.

### App size

The wheels are 14,557 to 15,548 bytes to download, so the payload is not the cost of this
package — the import is (see [Other considerations](#other-considerations)).

There is one lever if you want the last kilobytes back. `time_machine/cli.py` ships and cannot
run on a device, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) can drop it:

```toml
[tool.flet.cleanup]
package_files = ["**time_machine/cli.pyc"]
```

Match the `.pyc`, not the `.py` — serious_python's `bin/package_command.dart` runs
`compileall -b` and deletes the `.py` files before it applies these globs (checked in 4.5.1).
**That glob has not been verified against a build here**, so unpack the APK's
`assets/sitepackages.zip` and grep it for `time_machine` before relying on it.

### Other considerations

**A desktop `flet run` is not evidence about the device build.** Unless you pin, the two
resolve different releases (see [Install](#install)), so a behaviour you confirmed on your
laptop belongs to a version the phone is not running.

**Every timing figure on this page is a desktop measurement**, including the ~200 ns per-call
surcharge and the ~15 ms import cost in [Things to know](#things-to-know). Re-take both on a
device if start-up time or a hot loop matters to you; the import is the one that shows up in a
launch you can feel.

## Things to know

- **The
  [escape hatch](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.escape_hatch)
  only works while you are travelling.** It reaches the *saved* pointers, so off a trip
  `escape_hatch.datetime.datetime.now()` and `escape_hatch.time.time()` both raise
  `ValueError: Not currently time-travelling.` Call `escape_hatch.is_travelling()` first —
  and off a trip, plain `time.time()` is already the real clock.

- **A naive destination means different things depending on its type.** With the default
  [`naive_mode`](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.naive_mode)
  (`MIXED`), a naive `datetime` **object** is treated as UTC, while a naive **string** is
  parsed and left naive, which `.timestamp()` then reads as *local* time. On a machine at
  UTC+2, `travel(datetime(2001, 9, 9, 1, 46, 40))` and `travel("2001-09-09 01:46:40")` landed
  two hours apart. Set `time_machine.naive_mode = time_machine.NaiveMode.ERROR` if you would
  rather be told.

- **Only a `datetime` destination can change the
  [time zone](https://time-machine.readthedocs.io/en/latest/usage.html#timezone-mocking); a
  string never does.** time-machine sets `os.environ["TZ"]` and calls `tzset()` when the
  destination is a `datetime` carrying a `ZoneInfo` or `timezone.utc`, and restores both on
  exit: around a trip to a `ZoneInfo("Pacific/Auckland")` instant, `time.tzname` went
  `('CET', 'CEST')` → `('NZST', 'NZDT')` → `('CET', 'CEST')`. The same instant written as the
  string `"2001-09-09 01:46:40+00:00"` left `TZ` untouched, because the string branch never
  derives a zone name. That environment mutation is process-wide like everything else here.

- **A patched clock call costs about 200 ns more than an unpatched one**, because each one is
  a round trip back into Python: import `time_machine`, look up an attribute, call it.

  | Call | Unpatched | Inside a trip | Multiple |
  | --- | ---: | ---: | ---: |
  | `time.time()` | 27–29 ns | 221–237 ns | ~8× |
  | `datetime.now()` | 209–237 ns | 512–528 ns | ~2.4× |

  The surcharge is near-constant, so the multiple depends entirely on what you are calling —
  `datetime.now()` was already doing more work. Entering and leaving a trip is cheap by
  comparison: a `travel().start()` + `stop()` round trip is 0.83–0.89 µs. Measured over
  200,000 calls, repeated, on both CPython 3.12.13 and 3.14.6. None of that matters for a
  test; it matters if you are tempted to leave a trip running under a hot loop.

- **`import time_machine` pulls in 84 modules and costs about 15 ms, and 12–13 ms of that is
  `unittest` and `inspect`** — dragged in because `travel()` can decorate a
  `unittest.TestCase`. On CPython 3.14.6 the import takes 15.0–17.0 ms warm and 25–27 ms on the
  first import of a cold session; 3.12.13 is about 13 ms. That is a real slice of app start-up
  spent on a test framework, and one more reason not to ship this in a release build.
  Importing it patches nothing on its own.

- **`uuid.uuid1()` clamps when you travel backwards, and Android clamps sooner than the
  desktop does.** CPython's pure-Python `uuid1()` keeps a `_last_timestamp` and refuses to emit
  a lower one, so a trip to an earlier date than the last one gets that previous value plus one
  tick: 2038 → 2000 → 1969 reported `2038-01-19T03:14:07` all three times, while the same three
  ascending each reported their own destination. *Which* calls count as "the last one" is
  platform-dependent, because `uuid1()` only takes that Python path when the `_uuid` C
  extension is unavailable — which time-machine forces for the duration of a trip.
  **serious_python_android 4.5.1 ships no `_uuid` at all**, so on Android the Python path is
  the only path: one `uuid.uuid1()` call before you travel pins `_last_timestamp` to today, and
  every backwards trip after that clamps, including the first. iOS ships `_uuid.fwork`, so it
  behaves like the desktop and the clamp only shows up between trips.

- **`travel()` refuses to start when freezegun is active**, raising
  `RuntimeError("time-machine cannot start when freezegun is active.")`. Pick one.

- **There is no `time_machine.__version__`.** Use
  `importlib.metadata.version("time-machine")` if you want to print which build is on the
  device.

- **`time_machine/cli.py` ships and cannot run on a device.** It is over a third of the
  package's Python by size, and it imports `tokenize_rt` at module level — the `cli` extra,
  which is not installed. `import time_machine` never touches it, so this is dead payload
  rather than a hazard; [App size](#app-size) has the lever if you want it gone.

## Build notes (maintainers)

### Recipe shape

The recipe is `meta.yaml` and nothing else — a name, a version and a build number, with no
patches, no `build.sh`, no `requirements`, no `script_env`, no `platforms` key and no
`excluded_arches`. That shape is worth recording because it is earned rather than lucky:
upstream's whole `setup.py` is
`setup(ext_modules=[Extension(name="_time_machine", sources=["src/_time_machine.c"])])` behind
a PyPy guard — no `define_macros`, no `include_dirs`, no `libraries` — and the C file carries
its own `PY_VERSION_HEX` checks instead of asking the build system for anything. There is
nothing for a cross build to get wrong, and the Python half of the wheel comes out
byte-identical to upstream's sdist: `__init__.py`, `__main__.py`, `cli.py` and `py.typed` hash
the same in a cp312 Android arm64 wheel, a cp314 iOS device wheel and the sdist.

One packaging detail with no other home: the wheel declares a `pytest11` entry point
(`time_machine = time_machine`), so **pytest auto-loads this package as a plugin** wherever it
is installed — including the on-device recipe-tester app. That is harmless today (the plugin
registers a marker and a fixture) but it means the package is imported before any test runs, so
an import-time failure on device would surface as a pytest collection error rather than as a
failing test.

### Upgrade hazards

Upstream has moved on and has releases waiting for a bump. Every consumer claim on this page —
which readings follow, the per-call overhead, the import cost, the `Requires-Dist` promise —
was measured against the single release `meta.yaml` declares, and a bump can invalidate any of
them without failing a build or a test. Re-take the measurements in the same commit as the
version change, or delete the claim.

### Re-verification checklist

In rough order of what a green build fails to tell you:

- **Which functions the extension patches.** The list of nine in the opening section is read
  from `src/_time_machine.c`'s `_time_machine_patch()`. Upstream adding `time.monotonic` or
  removing `datetime.utcnow` (deprecated since 3.12, and the module fails to import if the
  attribute is missing) would invalidate several sections at once. The cheap check is that
  `_time_machine_patch()` still makes exactly nine `ml_meth =` assignments.
- **That no clock symbol has appeared in the import table.** The "does not touch libc" claim
  rests on the undefined-symbol lists being 16 entries on cp312 Android and 17 on cp313/cp314
  — of which exactly three are bionic (`__cxa_atexit`, `__cxa_finalize`, `__register_atfork`)
  and the rest CPython entry points — and 14 on cp312 iOS and 15 on cp313/cp314, one of them
  `dyld_stub_binder`. On all nineteen published slices the number of imported symbols whose
  name contains `time` or `clock` is zero. A release that started calling `clock_gettime`
  directly would break the mental model this page is built on without failing any test.
- **The thread-interleaving table in [Threading](#threading).** It is a property of
  `traveller_stack` being a module-level list with a LIFO `pop()`; upstream making that
  thread-local — which would be a fix, not a regression — would turn that whole section into a
  historical note.
- **The overhead figures**, which are desktop measurements rather than estimates. The ~200 ns
  surcharge follows from the patched function doing an import and a Python call per
  invocation; a release that caches the module reference in the extension would move it a lot.
- **`Requires-Dist` still being empty of unconditional entries.** Today the `METADATA` in all
  nineteen wheels declares two optional extras only — `cli` (`tokenize-rt`) and `dateutil`
  (`python-dateutil>=2.8.2`) — and `Requires-Python` is `>=3.10`, below every Python Flet ships
  on mobile. [Install](#install) is written on that basis; upstream promoting `python-dateutil`
  out of its extra would make it false without failing anything.
- **The extension filename.** It must keep a CPython ABI tag; an untagged `NAME.so` gets no
  `.soref`, is not relocated into `jniLibs`, and becomes a silent `ModuleNotFoundError` on
  device. Note the two spellings already in play — `_time_machine.cpython-312.so` on the 3.12
  Android wheels and `_time_machine.cpython-31X-<triplet>.so` on the 3.13 and 3.14 ones — so a
  check must match the prefix, not the exact suffix. iOS spells them
  `_time_machine.cpython-314-iphoneos.so` and `…-iphonesimulator.so`.
- **`otool -hv` reporting `DYLIB` on every iOS slice.** Forge's `MH_BUNDLE` → `MH_DYLIB`
  conversion landed in 2026-07; wheels published before it are the class of breakage that only
  appears at app link time, never in the recipe's own tests. Besides each extension's own
  install name, `otool -L` should list exactly two dependencies on every slice:
  `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`.
- **The Android ELF shape.** `DT_NEEDED` is exactly `libm.so`, `libpython3.<minor>.so`,
  `libdl.so` and `libc.so` on all ten Android slices, with no `SONAME`, no `RPATH`, no
  `RUNPATH` and no `libc++_shared` — the source is one C file, not C++. Every `PT_LOAD`
  segment carries 16 KB alignment, which Android 15 requires. arm64-v8a and x86_64 are
  `ELF64`; armeabi-v7a and the legacy `x86` slice are genuine `ELF32`/`ARM` and `ELF32`/`i386`
  builds rather than stubs, and each slice exports exactly one symbol,
  `PyInit__time_machine`. All ten are stripped: no `.symtab`, no `.debug_*`.
- **That the wheel is still eleven files with no data file.** One extension, three Python
  modules, an empty `py.typed` and six `dist-info` entries. Neither `__init__.py` nor
  `__main__.py` touches `__file__`, `importlib.resources`, `pkgutil` or `open` — the only two
  `open()` calls are in `cli.py`. That is what keeps
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) out of the
  consumer guidance; a data file appearing in the wheel would put it back.
- **That a bare `time-machine` still resolves from this index for a mobile target.** Checked
  with `pip download --only-binary :all:` with PyPI listed first and this index only as
  `--extra-index-url`, once for each of the nineteen published (Python, platform tag) pairs:
  all nineteen came back with this index's wheel. The two pairs that have no wheel —
  `android_24_x86` on 3.13 and on 3.14 — failed with *No matching distribution found*.
- **Whether upstream has started publishing mobile wheels.** The release this recipe builds is
  78 files — eleven per ABI family across cp310–cp314 plus `cp313t`/`cp314t`, and one sdist —
  with no Android tag, no iOS tag and no `py3-none-any` among them. That is what makes the
  bare-requirement resolution above work, and the day it changes this recipe may stop being
  needed.
- **Whether serious_python has started shipping `_uuid` on Android.** Still no, as of the 4.5.1
  payload built on 2026-08-20 — verified against a real APK, which contains no `_uuid` entry of
  any kind and whose `lib/arm64-v8a/libpython3.14.so` yields zero matches for `PyInit__uuid`,
  while the same example's iOS bundle ships `Frameworks/_uuid.framework/_uuid`. The
  [Things to know](#things-to-know) claim about `uuid.uuid1()` clamping from the first trip is a
  property of the runtime, not of this wheel; a future release adding the extension would
  quietly restore the desktop behaviour.
- **Flet's own clock reads**, on a Flet bump. 0.86.5's Python side reads the wall clock in
  seven places, all patched while travelling: the four pickers named in
  [Threading](#threading), plus three pieces of plumbing — `messaging/session.py:207`
  (disconnected-session expiry), `messaging/protocol.py:194` (naive-`datetime` tzinfo fallback
  on the way to the client) and `auth/authorization_service.py:203` (OAuth token expiry). A
  clock read landing on the repaint path is what would falsify "redraws through a trip".

### Coverage gaps

`tests/test_time_machine.py` is a single `test_basic` that freezes the clock at
2020-04-12 12:00 UTC, asserts the year, month, day and hour of `datetime.now(timezone.utc)`,
and then checks the real clock is not simultaneously 2020 and the 12th. That last assertion
catches more than it looks like it does: run the same trip with `start()` and no `stop()`, and
`datetime.now()` stays pinned at 2020-04-12, so both halves of the `or` are false and the
assert fires — checked by running exactly that. What it cannot see is a restore that lands on
some clock other than the real one. The narrowness generally is the thing to fix, and this page
names exactly what would close the gaps, in rough order of value:

- **`time.monotonic()` unchanged across a trip**, which is what the timeout advice in
  [What follows the clock and what does not](#what-follows-the-clock-and-what-does-not) rests
  on and is a one-line assert.
- **A reading that must *not* follow** — `time.ctime()` is the cheapest — since a build where
  the patch somehow reached further than documented would pass every test there is.
- **`tick=False` giving two identical reads and `tick=True` giving two different ones**, which
  pins the destination arithmetic to the device rather than to a desktop.
- **The escape hatch**, both directions: real time inside a trip, `ValueError` outside one.
- **`time.localtime()` and `time.strftime()`**, the two patched functions nothing currently
  touches — and on Android they are the ones nearest the missing time-zone database.

The thread-interleaving behaviour is deliberately not on that list: two threads racing on a
shared stack is a poor fit for a CI test that must never flake.
