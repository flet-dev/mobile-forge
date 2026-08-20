# time-machine

[`time-machine`](https://github.com/adamchainz/time-machine) moves the clock. You name a
destination with
[`travel()`](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.travel),
and inside the block `time.time()`, `datetime.now()` and most of what CPython offers for
reading the wall clock report that instant instead of the real one — so a test can assert
what a subscription renewal screen shows on the day a trial expires, or what a "3 days ago"
label says, without waiting three days or threading a fake clock through every function that
needs one.

**It is worth being precise about what "C level" means here, because it decides what works
and what does not.** time-machine does not patch libc, and it does not rebind module
attributes the way `unittest.mock.patch` does. Its extension reaches into the
`PyMethodDef` structs that CPython's own built-in methods are described by and overwrites
the `ml_meth` function pointer for nine of them — `time.time`, `time.time_ns`,
`time.gmtime`, `time.localtime`, `time.strftime`, `time.clock_gettime`,
`time.clock_gettime_ns`, `datetime.datetime.now` and `datetime.datetime.utcnow` — then puts
the saved pointers back on exit. (Upstream's
[list of mocked functions](https://time-machine.readthedocs.io/en/latest/usage.html#mocked-functions)
has eleven entries; the two extra, `date.today()` and `datetime.today()`, follow along
rather than being patched — see below.) The wheel's symbol table is the evidence that libc
is not
involved: the Android extension imports 16 symbols on cp312 and 17 on cp313/cp314, of which
exactly three are bionic (`__cxa_atexit`, `__cxa_finalize`, `__register_atfork`) and the
rest are CPython entry points; the iOS list is 14 entries on cp312 and 15 on cp313 and 3.14,
one of them `dyld_stub_binder` and the rest CPython. **On all nineteen published slices the
number of imported symbols whose name contains `time` or `clock` is zero.**

Three consequences follow from that, and they are the whole story on a phone. Because the
swap is in the method struct rather than in a namespace, a reference bound *before* the trip
is patched too: `from time import time` captured at import still returns the fake value
(verified). Because the struct is per-process, **the patch is not scoped to a thread** —
a worker started before the trip sees the frozen clock. And `datetime.date.today()` follows
even though it is not one of the nine, because it reaches the clock through the `time`
module rather than directly — with time-machine absent entirely and `time.time` simply
rebound to `lambda: 0.0`, `date.today()` returned `1970-01-01` while `datetime.now()` and
`time.ctime()` both reported the real date. Anything reading the clock in C without going
through those nine does not follow: `time.ctime()`, SQLite's `CURRENT_TIMESTAMP` and a
file's `st_mtime` all keep reporting the real date in the middle of a frozen block.

**This is a testing library, and shipping it in a production app is almost always the wrong
call.** The patch is a process-global mutation with no owner and no timeout: it stays in
place until something calls `stop()`, and while it is in place it reaches every thread,
every dependency and Flet's own internals. If your app needs a clock it can steer — a demo
mode, a countdown you can fast-forward, a "what does this screen look like next Tuesday"
toggle — inject the clock instead (`def build(now=datetime.now)`, then pass a stub) and keep
time-machine for the tests. What it is genuinely good for on a device is the case in the
[example](examples/frozen-clock): finding out what your app's dependencies actually read
the clock with.

**Not yet run on a device.** Every measurement on this page was made against the published
wheels, on a desktop (Apple M4, macOS 26.6, CPython 3.14.6 and 3.12.13), or over `adb` /
`simctl` against an idle emulator or simulator — no Flet app has been built from it. Each
claim says which. `tests/test_time_machine.py` runs on device in CI and asserts the
central claim — that `datetime.now()` follows `travel()` and is restored afterwards — but
the per-reading breakdown below has not been reproduced on an emulator or a phone yet.

**Measured on device, 2026-08-20**, on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6. The frozen clock held on both: every one of the eleven readings
the example takes — `time.time`, `time.time_ns`, `time.clock_gettime(CLOCK_REALTIME)`,
`datetime.now(utc)`, `date.today`, `gmtime`, `localtime`, `strftime`, `ctime`, `uuid.uuid1` and
the timestamp on a `logging` record — followed the destination, while **`time.monotonic()` was
never patched** and kept counting real seconds since launch. That split is the useful one: a
timeout or an animation driven by `monotonic` keeps running normally while wall-clock reads are
frozen.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "time-machine",
]
```

**The pip name is hyphenated and the import name is not** — you install `time-machine` and
write `import time_machine`. `importlib.metadata.version` wants the hyphenated spelling.

Nothing else to configure, and nothing comes along with it. The `METADATA` in all nineteen
published wheels declares **no unconditional `Requires-Dist`** — two optional extras only,
`cli` (which wants `tokenize-rt`) and `dateutil` (`python-dateutil>=2.8.2`) — so no
`flet-lib*` wheel and no transitive dependency follows. `Requires-Python` is `>=3.10`,
below every Python Flet ships on mobile.

The entry belongs in top-level `[project] dependencies` rather than in a
`[tool.flet.android]` / `[tool.flet.ios]` table: `flet build` resolves for the build host
first, and upstream publishes desktop binaries for every host you would build from. The
3.2.0 release is 78 files: eleven per ABI family — two macOS (`universal2` and `x86_64`),
six Linux (`manylinux` and `musllinux` × x86_64, i686, aarch64) and three Windows (`win32`,
`win_amd64`, `win_arm64`) — for each of cp310 through cp314 plus the free-threaded `cp313t`
and `cp314t`, and one sdist. **None of those 78 files carries an Android tag, an iOS tag or
`py3-none-any`**, which is why this recipe exists.

A bare `time-machine` really does resolve from this index for a mobile target. Checked with
`pip download --only-binary :all:` with **PyPI listed first** and this index only as
`--extra-index-url`, once for each of the nineteen published (Python, platform tag) pairs:
all nineteen came back with this index's wheel. The two pairs that have no wheel —
`android_24_x86` on 3.13 and on 3.14 — failed with *No matching distribution found*.

**Desktop and device are not on the same release unless you pin.** PyPI's newest
time-machine is 3.4.0; this index's newest is 3.2.0, so a bare requirement resolves 3.4.0 for
`flet run` on your laptop and 3.2.0 for `flet build`. Everything measured on this page is
3.2.0, and 3.4.0 has not been checked against it here. Pin both sides — as
[`frozen-clock`](examples/frozen-clock) does — if the difference could matter to you.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Every wheel is eleven files — one extension, three Python modules, an empty
`py.typed` and six `dist-info` entries — with no data file of any kind, so the Flet 0.86
Android `sitepackages.zip` class of failure has nothing to bite on. Neither `__init__.py`
nor `__main__.py` touches `__file__`, `importlib.resources`, `pkgutil` or `open`; the only
two `open()` calls in the package are in `cli.py`, which needs the `cli` extra to import at
all (see [Things to know](#things-to-know)). The extension carries a CPython ABI tag on
every slice — `_time_machine.cpython-312.so` on the 3.12 Android wheels,
`_time_machine.cpython-313-aarch64-linux-android.so` and its `-314-` twin on the 3.13 and
3.14 Android ones, and `_time_machine.cpython-314-iphoneos.so` / `…-iphonesimulator.so` on
iOS — which is what
serious_python's relocation of native modules into `jniLibs` keys on, so no shim is needed.

Nineteen wheels at the same build number: Python 3.12 across all four Android ABIs
(arm64-v8a, armeabi-v7a, x86_64 and the legacy 32-bit `android_24_x86`) and 3.13 and 3.14
across three each, plus all three iOS slices (device, arm64 simulator, x86_64 simulator) for
each of the three Pythons. No architecture is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. The wheels are 14,557 to 15,548 bytes to download.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`frozen-clock`](examples/frozen-clock) — a frozen clock beside the real one, with thirteen
  ways of asking the time classified as *followed*, *real clock* or *elsewhere*.

## Threading

**A trip is process-global. There is nothing thread-local about it, and this is the single
most important thing to know before using it in a Flet app.** Two mechanisms make it so: the
`ml_meth` swap described above happens once in a struct every thread shares, and
`time_machine.traveller_stack` is a plain module-level list.

Measured on desktop: a worker thread started **before** any travel began, then released
inside a `travel(..., tick=False)` block, read `time.time()` as `1000000000.0` and
`datetime.now()` as the destination — while its `time.monotonic()` stayed within 0.0000 s of
the main thread's. So a background job you did not think about is on the fake clock too.

**Two overlapping trips corrupt each other, and the failure is silent.** `stop()` pops the
last entry of that shared list without checking who pushed it. Two threads entering
`travel()` at once, thread A to 2001 and thread B to 1980, over 8 runs, all 8 identical:

| | inside its own `with` block | after leaving its own `with` block |
|---|---|---|
| thread A (entered first, to 2001) | **1980** | **2001** |
| thread B (entered second, to 1980) | **2001** | 2026 |

Read the second column twice. **Thread A left its `with` block and time was still fake**,
because the entry it popped was B's and its own was still on the stack; time only came back
when B exited. No exception is raised anywhere in that, and the traveller stack is empty and
correct at the end, so nothing afterwards shows it happened.

This matters in Flet specifically because
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) submits
to a shared thread pool, so two taps in quick succession genuinely overlap — and it never
retrieves the worker's future, so anything the worker raised surfaces nowhere. The fix is
the ordinary one: hold a `threading.Lock` across the whole `with travel(...)` block, or
travel only on one thread. The same 8 runs with a lock gave A 2001 / B 1980 and a real clock
after each block, 8 times out of 8.

**Freezing the clock does not stall the UI.** asyncio schedules on `time.monotonic()`, which
time-machine does not patch: on desktop, an `asyncio.sleep(0.3)` inside a frozen block took
0.301 s of real time and the loop's own `loop.time()` advanced 0.301 s while `time.time()`
sat at `1000000000.0`. Flet 0.86.5's Python side reads the wall clock in seven places, and
every one of them is patched while travelling. Three are plumbing: `messaging/session.py:207`
computes a disconnected session's expiry from `datetime.now(timezone.utc)`,
`messaging/protocol.py:194` attaches `datetime.datetime.now().astimezone().tzinfo` to a naive
`datetime` on its way to the client — a fallback the msgpack encoder only reaches when
`astimezone()` on that `datetime` raises — and `auth/authorization_service.py:203` compares
an OAuth token's expiry against `time.time()`. The other four are user-visible: the
`default_factory=lambda: datetime.now()` defaults on `DatePicker.current_date`,
`DateRangePicker.current_date` and `CupertinoDatePicker.value`, plus `TimePicker.value`,
whose factory is the same call followed by `.time()`. Built
inside a trip to 1969-07-20 20:17:40 UTC on desktop, `ft.DatePicker().current_date` came back
`1969-07-20 21:17:40`, so a picker opened during a trip opens on the destination date.
No clock read is on the ordinary repaint path, which is why the
[example](examples/frozen-clock) can redraw through a trip.

## Android notes

- **There is no readable time-zone database, so `ZoneInfo(...)` fails.** Python's
  `TZPATH` in Flet's Android build is the standard Unix list —
  `/usr/share/zoneinfo:/usr/lib/zoneinfo:/usr/share/lib/zoneinfo:/etc/zoneinfo`, read out of
  `_sysconfig_vars__android_aarch64-linux-android.json` in serious_python_android 4.5.1's
  `stdlib.zip` — and on an Android 14 arm64 emulator **none of those four directories
  exists**. What the platform has instead is bionic's own format: a single 429,558-byte
  `tzdata` file at `/system/usr/share/zoneinfo/tzdata` and again under
  `/apex/com.android.tzdata/etc/tz/`, which `zoneinfo` cannot read because it opens
  `<TZPATH>/<key>` as a TZif file. Reproduced the exact shape on desktop by pointing
  `PYTHONTZPATH` at a directory that does not exist: `ZoneInfo("Europe/Paris")` raises
  `ZoneInfoNotFoundError: 'No time zone found with key Europe/Paris'`.
- **That only bites the destination forms that name an IANA zone.** In the same
  no-database run, `travel("2001-09-09 01:46:40+00:00")`, `travel("2001-09-09 01:46:40")`,
  `travel(1000000000.0)` and `travel(datetime(..., tzinfo=timezone.utc))` all worked. It is
  your own `ZoneInfo(...)` call that fails, before time-machine sees it. **The fix is the
  pure-Python [`tzdata`](https://pypi.org/project/tzdata/) package** — `zoneinfo` falls back
  to it when the filesystem has nothing, verified by installing it into the same broken-path
  run and watching `ZoneInfo("Europe/Paris")` construct. It ships as a 348,168-byte
  `py2.py3-none-any` wheel, so it resolves for a mobile target without a recipe:

  ```toml
  dependencies = ["flet", "time-machine", "tzdata"]
  ```
- **The extension links nothing but the interpreter and bionic.** `DT_NEEDED` is exactly
  `libm.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` on all ten Android slices,
  with no `SONAME`, no `RPATH`, no `RUNPATH` and no `libc++_shared` — the source is one C
  file, not C++. Every `PT_LOAD` segment carries 16 KB alignment, which Android 15 requires.
  arm64-v8a and x86_64 are `ELF64`; armeabi-v7a and the legacy `x86` slice are genuine
  `ELF32`/`ARM` and `ELF32`/`i386` builds rather than stubs. Each slice exports exactly one
  symbol, `PyInit__time_machine`.
- **The native half is small, and smaller than the Python half.** The extension is 8,596
  bytes on armeabi-v7a, 13,424 on x86_64 and 14,608 on arm64-v8a (cp314), against 31,466
  bytes of Python and 4,731 of `dist-info` — 28.8% of a 50,805-byte unpacked wheel. All ten
  Android slices are stripped: no `.symtab` and no `.debug_*` section on any of them, with
  `.text` running 3,348 to 5,028 bytes.

## iOS notes

- **Whether iOS itself carries a time-zone database is not established here, so ship
  `tzdata`.** `TZPATH` is the same four-entry Unix list. A booted iPhone 16 simulator
  (iOS 18.6) does resolve `/usr/share/zoneinfo` → `/var/db/timezone/zoneinfo` →
  `/var/db/timezone/tz/2026c.1.0/zoneinfo`, but **that is the host Mac's database, not one
  iOS ships**: the iOS 18.6 `RuntimeRoot` contains no `zoneinfo` directory anywhere under
  it, and `stat` on `Europe/Paris` returns the same device:inode inside the simulator as on
  the host. A simulator run therefore proves nothing about a phone, and no physical device
  was available for this page. The `tzdata` package from the Android note is the portable
  answer and costs 348 KB.
- **The extensions are `MH_DYLIB`, which is what Flet 0.86 needs.** `otool -hv` reports
  filetype `DYLIB` (not `BUNDLE`) on all nine iOS slices, so the *Unsupported mach-o
  filetype (only MH_OBJECT and MH_DYLIB can be linked)* failure at app link time does not
  arise here. Besides each extension's own install name, `otool -L` lists exactly two
  dependencies on every slice: `@rpath/Python.framework/Python` and
  `/usr/lib/libSystem.B.dylib`.
- **The same code is five times the file size, and none of that is more code.** The cp314
  device slice is 70,384 bytes against 14,608 on Android arm64-v8a, but its `__text` section
  is 4,872 bytes against Android's 5,028 — the difference is Mach-O's 16 KB segment
  alignment (32,768 for `__TEXT`, 16,384 each for `__DATA_CONST`, `__DATA` and `__LINKEDIT`)
  plus a 171-entry symbol table. Unpacked, the iOS device wheel is 106,571 bytes against
  50,805, and the x86_64 simulator slice is the smallest iOS build, 21,240 bytes of
  extension on cp314.

## Things to know

- **`time.ctime()` and `time.asctime()` do not follow the trip, and they sit one line away
  from things that do.** Frozen at 2001-09-09, `time.strftime("%Y")` returned `2001` while
  `time.ctime()` returned the real `Thu Aug 20 10:30:13 2026` in the same block. CPython's
  `ctime()` reads the clock without going through the `time` module at all — rebinding
  `time.time` by hand leaves it on the real date — so there is no method pointer for
  time-machine to swap. Anything logging or rendering through `ctime` is quietly telling the
  truth while the rest of your app is not, and neither name appears in upstream's
  [unmocked time sources](https://time-machine.readthedocs.io/en/latest/usage.html#unmocked-time-sources)
  note, which lists NumPy's `np.datetime64("now")` and SQLite.
- **Two more real-clock leaks**, measured in one desktop sweep frozen at 1969-07-20:
  SQLite's `CURRENT_TIMESTAMP` (SQLite's own C clock, and the one upstream documents) and
  the `st_mtime` a file gets when written (the kernel's). In the other direction, a
  `logging` record's `created`, `uuid.uuid1()`'s embedded timestamp and `date.today()` all
  **do** follow. 10 of 13 readings moved — 9 on Android, where `uuid.uuid1()` drops out for a
  reason that has nothing to do with this wheel (see below). The
  [example](examples/frozen-clock) is that sweep with a button on it.
- **`time.monotonic()`, `time.perf_counter()`, `time.process_time()` and
  `time.thread_time()` are never patched**, by design — they measure elapsed time, not dates.
  If you are freezing the clock to test a timeout, check which clock the timeout is written
  against first; `asyncio`, `threading.Event.wait` and most retry libraries use the
  monotonic one and will not notice your trip at all.
- **The
  [escape hatch](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.escape_hatch)
  only works while you are travelling.** `time_machine.escape_hatch` reaches the *saved*
  pointers, so off a trip
  `escape_hatch.datetime.datetime.now()` and `escape_hatch.time.time()` both raise
  `ValueError: Not currently time-travelling.` — `escape_hatch.is_travelling()` is the
  safe thing to call first, and plain `time.time()` is already the real clock.
- **A naive destination means different things depending on its type.** With the default
  [`naive_mode`](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.naive_mode)
  (`MIXED`), a naive `datetime` **object** is treated as UTC, while a naive
  **string** is parsed and left naive, which `.timestamp()` then reads as *local* time. On a
  machine at UTC+2, `travel(datetime(2001, 9, 9, 1, 46, 40))` and
  `travel("2001-09-09 01:46:40")` landed two hours apart. Set
  `time_machine.naive_mode = time_machine.NaiveMode.ERROR` if you would rather be told.
- **Only a `datetime` destination can change the
  [time zone](https://time-machine.readthedocs.io/en/latest/usage.html#timezone-mocking);
  a string never does.** time-machine sets `os.environ["TZ"]` and calls `tzset()` when the
  destination is a `datetime` carrying a `ZoneInfo` or `timezone.utc`, and restores both on
  exit — measured:
  `time.tzname` went `('CET', 'CEST')` → `('NZST', 'NZDT')` → `('CET', 'CEST')` around a trip
  to a `ZoneInfo("Pacific/Auckland")` instant, with `TZ` back to unset afterwards. The same
  instant as the string `"2001-09-09 01:46:40+00:00"` left `TZ` untouched, because the
  string branch never derives a zone name. That environment mutation is process-wide like
  everything else here.
- **A patched clock call costs about 200 ns more than an unpatched one**, because each one
  is a round trip back into Python: import `time_machine`, look up an attribute, call it.
  Measured on desktop over 200,000 calls, repeated, on both CPython 3.12.13 and 3.14.6:
  `time.time()` 27–29 ns unpatched against 221–237 ns patched, and `datetime.now()`
  209–237 ns against 512–528 ns. The surcharge is near-constant, so the *multiple* depends
  entirely on what you are calling — about 8× for `time.time()`, about 2.4× for
  `datetime.now()`, which was already doing more work. Entering and leaving a trip is cheap
  by comparison: a `travel().start()` + `stop()` round trip is 0.83–0.89 µs. None of that
  matters for a test; it matters if you are tempted to leave a trip running under a hot
  loop.
- **`import time_machine` pulls in 84 modules and costs about 15 ms on desktop, and 12–13 ms
  of that is `unittest` and `inspect`** — dragged in because `travel()` can decorate a
  `unittest.TestCase`. Measured on a bare CPython 3.14.6 (`python -c`, no virtualenv):
  `sys.modules` goes from 33 entries to 117, and the import takes 15.0–17.0 ms warm, 25–27 ms
  on the first import of a cold session; 3.12.13 is 32 → 111 and about 13 ms. Take the
  before- and after-counts from the *same* interpreter — inside a `uv` virtualenv the bare
  count is 47, not 33, because the venv's site hook is already loaded. That is a real slice
  of app start-up spent on a test framework, and one more reason not to ship this in a
  release build. Importing it patches nothing on its own.
- **`uuid.uuid1()` clamps when you travel backwards, and Android clamps sooner than the
  desktop does.** CPython's pure-Python `uuid1()` keeps a `_last_timestamp` and refuses to
  emit a lower one, so a trip to an earlier date than the last one gets that previous value
  plus one tick. Verified identically on 3.12.13 and 3.14.6: 2038 → 2000 → 1969 reported
  `2038-01-19T03:14:07` all three times, while the same three ascending each reported their
  own destination. *Which* calls count as "the last one" is platform-dependent, because
  `uuid1()` only takes that Python path when the `_uuid` C extension is unavailable —
  time-machine sets `uuid._generate_time_safe = None` for the duration of a trip precisely
  to force it. **serious_python_android 4.5.1 ships no `_uuid` at all**: no `lib_uuid.so` in
  any of the three `jniLibs` ABI directories, no `PyInit__uuid` in `libpython3.14.so`, and
  nothing matching `uuid` in the payload but `uuid.pyc`. So on Android the Python path is the
  only path, one `uuid.uuid1()` call before you travel pins `_last_timestamp` to today, and
  every backwards trip after that clamps — including the first. iOS ships `_uuid.fwork`, with
  `PyInit__uuid` in it, so iOS behaves like the desktop and the clamp only shows up between
  trips. Confirmed in a **built app** on 2026-08-20, not just in the pub-cache
  package: the example's own APK contains no `_uuid` entry of any kind and its
  `lib/arm64-v8a/libpython3.14.so` yields zero matches for `PyInit__uuid`, while the same
  example's iOS bundle ships `Frameworks/_uuid.framework/_uuid`. The clamping *behaviour* that
  follows from it was reproduced on desktop by setting `uuid._generate_time_safe = None`; the
  asymmetry itself is now measured.
- **`travel()` refuses to start when freezegun is active**, raising
  `RuntimeError("time-machine cannot start when freezegun is active.")`. Pick one.
- **There is no `time_machine.__version__`.** Use
  `importlib.metadata.version("time-machine")` if you want to print which build is on the
  device; it returns `3.2.0` for these wheels.
- **`time_machine/cli.py` ships and cannot run on a device.** It is 12,764 bytes of the
  31,466-byte Python half — 41% — and it imports `tokenize_rt` at module level, which is the
  `cli` extra and is not installed. `import time_machine` never touches it, so this is dead
  payload rather than a hazard; `[tool.flet.cleanup] package_files` is the lever if you want
  it gone. Match `**time_machine/cli.pyc`, not the `.py` — serious_python's
  `bin/package_command.dart` runs `compileall -b` and deletes the `.py` files before it
  applies these globs (checked in 4.5.1). **That glob has not been verified against a build
  here**; check with
  `unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l /tmp/sp.zip | grep time_machine`
  before relying on it.
- **The Python half is byte-identical to upstream's sdist.** `__init__.py`, `__main__.py`,
  `cli.py` and `py.typed` hash the same in the cp312 Android arm64 wheel, the cp314 iOS
  device wheel and `time_machine-3.2.0.tar.gz`, so nothing about the mobile build changes
  the package's behaviour.

## Build notes (maintainers)

The recipe is `meta.yaml` and nothing else — a name, a version and a build number, with no
patches, no `build.sh`, no `requirements`, no `script_env`, no `platforms` key and no
`excluded_arches`. That shape is worth recording because it is earned rather than lucky:
upstream's whole `setup.py` is
`setup(ext_modules=[Extension(name="_time_machine", sources=["src/_time_machine.c"])])`
behind a PyPy guard — no `define_macros`, no `include_dirs`, no `libraries` — and the C file
carries its own `PY_VERSION_HEX` checks instead of asking the build system for anything.
There is nothing for a cross build to get wrong.

One packaging detail with no other home: the wheel declares a `pytest11` entry point
(`time_machine = time_machine`), so **pytest auto-loads this package as a plugin** wherever
it is installed — including the on-device recipe-tester app. That is harmless today (the
plugin registers a marker and a fixture) but it means the package is imported before any
test runs, so an import-time failure on device would show up as a pytest collection error
rather than as a failing test.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **Which functions the extension patches.** The list of nine in the opening section is read
  from `src/_time_machine.c`'s `_time_machine_patch()`, and it is what
  [Things to know](#things-to-know) prices. Upstream adding `time.monotonic` or removing
  `datetime.utcnow` (deprecated since 3.12, and the module fails to import if the attribute
  is missing) would invalidate several bullets at once. The cheap check is that
  `_time_machine_patch()` still makes exactly nine `ml_meth =` assignments.
- **That no clock symbol has appeared in the import table.** The "does not touch libc" claim
  rests on the undefined-symbol lists being 16/17 entries on Android and 14/15 on iOS, with
  zero clock-related names. A release that started calling `clock_gettime` directly would break
  the mental model this page is built on without failing any test.
- **The thread-interleaving table in [Threading](#threading).** It is a property of
  `traveller_stack` being a module-level list with a LIFO `pop()`; upstream making that
  thread-local — which would be a fix, not a regression — would turn that whole section into
  a historical note.
- **The overhead figures**, which are desktop measurements rather than estimates. The
  ~200 ns surcharge follows from the patched function doing an import and a Python call per
  invocation; a release that caches the module reference in the extension would move it a
  lot.
- **`Requires-Dist` still being empty of unconditional entries.** [Install](#install) tells
  people nothing comes along with this package; upstream promoting `python-dateutil` out of
  its extra would make that false without failing anything.
- **The extension filename.** It must keep a CPython ABI tag; an untagged `NAME.so` gets no
  `.soref`, is not relocated into `jniLibs`, and becomes a silent `ModuleNotFoundError` on
  device. Note the two spellings already in play — `_time_machine.cpython-312.so` on the
  3.12 Android wheels and `_time_machine.cpython-31X-<triplet>.so` on the 3.13 and 3.14 ones
  — so a check must match the prefix, not the exact suffix.
- **`otool -hv` reporting `DYLIB` on every iOS slice.** Forge's `MH_BUNDLE` → `MH_DYLIB`
  conversion landed in 2026-07; wheels published before it are the class of breakage that
  only appears at app link time, never in the recipe's own tests.
- **Whether serious_python has started shipping `_uuid` on Android.** Still no, as of the
  4.5.1 payload built on 2026-08-20 — verified against a real APK, see
  [Things to know](#things-to-know). Re-check on each serious_python bump. The
  [Things to know](#things-to-know) claim about `uuid.uuid1()` clamping from the first trip
  is a property of the runtime, not of this wheel: `grep -r uuid` over
  `serious_python_android`'s `jniLibs` and `assets/*.zip` finding only `uuid.pyc` is what
  makes it true, and a future release adding the extension would quietly restore the
  desktop behaviour.
- **Whether upstream has started publishing mobile wheels.** The 3.2.0 release is 78 files
  with no Android, iOS or `py3-none-any` tag among them, which is what makes a bare
  `time-machine` resolve from this index; the day that changes, this recipe may stop being
  needed. Note that upstream has moved on — PyPI's newest is 3.4.0 — so a bump has releases
  waiting for it and the page's measurements are all against 3.2.0.

`tests/test_time_machine.py` is a single `test_basic` that freezes the clock at
2020-04-12 12:00 UTC, asserts the year, month, day and hour of
`datetime.now(timezone.utc)`, and then checks the real clock is not simultaneously 2020 and
the 12th. It has a docstring, in line with the repo's convention, and no version assertion.
That last assertion catches more than it looks like it does: run the same trip with
`start()` and no `stop()`, and `datetime.now()` stays pinned at 2020-04-12, so both halves
of the `or` are false and the assert fires — checked by running exactly that. What it cannot
see is a restore that lands on some clock other than the real one. The narrowness generally
is the thing to fix, and this page names exactly what would close the gaps, in rough order
of value:

- **`time.monotonic()` unchanged across a trip**, which is what the
  [Things to know](#things-to-know) claim about timeouts rests on and is a one-line assert.
- **A reading that must *not* follow** — `time.ctime()` is the cheapest — since a build
  where the patch somehow reached further than documented would pass every test there is.
- **`tick=False` giving two identical reads and `tick=True` giving two different ones**,
  which pins the destination arithmetic to the device rather than to a desktop.
- **The escape hatch**, both directions: real time inside a trip, `ValueError` outside one.
- **`time.localtime()` and `time.strftime()`**, the two patched functions nothing currently
  touches — and on Android they are the ones nearest the missing time-zone database.

The thread-interleaving behaviour is deliberately not on that list: two threads racing on a
shared stack is a poor fit for a CI test that must never flake.
