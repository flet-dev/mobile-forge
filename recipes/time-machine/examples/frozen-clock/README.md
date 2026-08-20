# frozen clock

One screen that freezes this device's clock and then asks thirteen different ways of reading
the time what they think it is. Two clock faces tick side by side — the one the app sees and
the one the device actually has — and a table underneath classifies every reading as
*followed*, *real clock* or *elsewhere*, so you can see exactly how far
[`time_machine.travel()`](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.travel)
reaches on a phone.

Nothing is bundled and nothing is precomputed: every number on screen is read out of the
running process when you tap.

What it demonstrates:

- **What actually moves.** Frozen at Apollo 11's touchdown, measured on an Apple M4 desktop
  under CPython 3.14.6, **10 of the 13 readings follow**. Nine of them — `time.time()`,
  `time.time_ns()`, `time.clock_gettime(CLOCK_REALTIME)`, `datetime.now()`, `time.gmtime()`,
  `time.localtime()`, `time.strftime()`, `uuid.uuid1()` and a `logging` record's timestamp —
  report `1969-07-20 20:17` to the minute. The tenth, `date.today()`, has no time of day, so
  its row shows the local midnight that opens Apollo 11's day rendered in UTC:
  `1969-07-19 23:00` at UTC+2, `1969-07-20 07:00` at UTC-7. That is why it gets a day of
  slack instead of five seconds. **Expect 9 of 13 on Android**, where `uuid.uuid1()` joins
  the stragglers — see the last bullet.
- **What does not, which is the useful half.** Three readings stay in 2026 in the same
  sweep: **`time.ctime()`**, **SQLite's `CURRENT_TIMESTAMP`** and the **`st_mtime` a file
  gets when you write it**. `time.ctime()` sits directly under `time.strftime()` in the
  table, printing the same format from the same module, and they disagree — because
  time-machine swaps CPython's function pointer for `strftime` and CPython's `ctime`
  reads the system clock itself. The other two never went through Python at all: one is
  SQLite's C library, the other is the kernel.
- **That the patch is process-wide, not scoped to a thread.** *From a thread* runs a read
  inside [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread).
  Verified against a real `ThreadPoolExecutor`: while the trip is running, the worker
  reported `1969-07-20 20:17:40 UTC` and `2038-01-19 03:14:07 UTC`, and `2026-08-20` once
  the trip ended. If you were expecting the `with` block to fence off one thread, it does
  not.
- **That elapsed-time clocks are untouched.** The `time.monotonic()` line under the faces
  keeps counting through every trip. That is why the UI stays alive: asyncio schedules on
  the monotonic clock, and on desktop an `asyncio.sleep(0.3)` inside a frozen block still
  took 0.301 s of real time.
- **`tick=True` versus `tick=False`.** With the switch on, the frozen clock advances at the
  real rate from the destination — at the 1969 destination, where `time.time()` starts at
  `-14182940.0`, two reads across a real `sleep(0.25)` were `-14182940.0` and
  `-14182939.744955`, a delta of 0.2550 s. With it off, both reads are exactly
  `-14182940.0`. *+1 hour* calls
  [`Traveller.shift()`](https://time-machine.readthedocs.io/en/latest/usage.html#time_machine.Traveller.shift)
  to move the destination without leaving the trip.
- **Three destinations worth testing an app against.** 1969 is a negative unix timestamp,
  2000 is the Y2K rollover, and 2038-01-19 03:14:07 UTC is `2**31 - 1` seconds — the last
  second a 32-bit `time_t` can hold. Each probe is called inside its own `try`/`except`, so
  a destination a platform cannot represent shows up as one `failed` row rather than an
  empty screen.
- **One CPython quirk the table will show you.** Travel to a date *earlier* than the last
  destination and `uuid.uuid1()` stops following: `uuid` keeps the highest timestamp it
  has ever emitted and clamps anything lower to that value plus one tick. Measured
  identically on CPython 3.12.13 and 3.14.6 — 2038 then 2000 then 1969 gave
  `2038-01-19T03:14:07` all three times, while the same three in ascending order each
  reported their own destination. The app prints the reason under the table.
  **Android hits this on the very first trip.** That clamp only runs in `uuid1()`'s
  pure-Python branch, which the desktop and iOS take only while travelling — but
  serious_python_android 4.5.1 ships no `_uuid` extension at all (no `lib_uuid.so` in any
  `jniLibs` ABI directory, no `PyInit__uuid` in `libpython3.14.so`), so on Android it is the
  only branch. The opening sweep, before you travel, pins the timestamp to today, and every
  destination on this screen is in the past. Reproduced on desktop by setting
  `uuid._generate_time_safe = None` and running the app's own sweep: `uuid.uuid1()` reported
  `2026-08-20`, verdict `real clock`, and the summary line read 9/13.
- **Degrading instead of crashing.** The `time_machine` import is guarded. Without the wheel
  the header turns red and names what the import raised, *Travel* is disabled, and the
  probe table still runs against the real clock.

All the figures above are **desktop** measurements (Apple M4, macOS 26.6, CPython 3.14.6 and
3.12.13, time-machine 3.2.0 from PyPI). Running the app replaces them with the device's own.

## The point of the app is a warning

time-machine is a **testing** library. This app freezes a live Flet session's clock on
purpose, to show you what that does; a shipping app should not. The patch is a global swap
of CPython's clock function pointers, so it reaches every thread, every library and Flet's
own internals for as long as it is in place — and the *Return* button is the only thing that
puts it back. For app logic that needs a clock you can steer, inject one:

```python
def build(now=dt.datetime.now):
    ...
```

and hand the test a stub. Keep time-machine for tests, where it belongs.

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

It also runs on the desktop with `uv run flet run`, which is the fastest way to see the
table before committing to a build.
