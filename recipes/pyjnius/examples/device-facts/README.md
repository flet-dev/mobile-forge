# pyjnius device facts

**Android only.** There is no iOS wheel for pyjnius, so on iOS or on your desktop this app is a
single card saying so and pointing at [pyobjus](https://pyobjus.readthedocs.io/en/latest/). Build
it for Android and it fills with numbers.

One screen of Android platform facts read through [`jnius.autoclass`](https://pyjnius.readthedocs.io/en/latest/api.html#jnius.autoclass),
with every value printed next to a **second, independent reading of the same thing** — so the app
itself says whether the two agree instead of asking you to trust one number. Nothing here needs a
permission, and every figure is checkable against the phone in your hand.

What it demonstrates:

- **Identity, cross-checked against libc.** `android.os.Build` (MANUFACTURER, MODEL, DEVICE) and
  `android.os.Build$VERSION` (RELEASE, SDK_INT) come through ART reflection; the `ro.*` system
  properties Android fills those constants from come through `ctypes` and bionic's
  `__system_property_get`, which never touches the JVM. Each row prints `same`, `DIFFERS`, or
  `unchecked` when one of the two sides had nothing to say — a property this app may not read is
  not a disagreement. The values are the ones under Settings → About phone. The block is also
  where the `$` shows up:
  `android.os.Build.VERSION` is *not* how you spell a nested class, and the mistake produces a
  `NoClassDefFoundError` for `android/os/Build/VERSION`.
- **The machine, cross-checked against the stdlib.** `Runtime.availableProcessors()` against
  `os.cpu_count()`, `System.getProperty("os.version")` against `os.uname().release`, plus ART's
  own heap numbers, which have no Python equivalent and are shown for what they are.
- **Battery, cross-checked against a second Android API.** This is the block that needs a
  `Context`, so it is where the right way to get one is shown — `MAIN_ACTIVITY_HOST_CLASS_NAME`
  names a holder class inside Flet's own plugin, not kivy's `org.kivy.android.PythonActivity`
  that most pyjnius snippets on the web reach for. Charge and charging state come from
  `BatteryManager.getIntProperty` / `isCharging()`, then again from `level`/`scale`/`status` in
  the sticky `ACTION_BATTERY_CHANGED` broadcast, fetched by passing a null receiver to
  `registerReceiver`. The percentage is checkable against the status bar, and
  `adb shell dumpsys battery set level 42` moves it under the next run.
- **What a JNI round-trip costs.** The slider picks 200 to 20,000 calls to
  `System.currentTimeMillis()` — about the cheapest call there is, static and with no arguments —
  and the screen reports the total and the per-call figure. That is the number to weigh before
  polling something in a loop, which on Android is the only way to watch a value change from
  Python. The last value that came back is printed as its offset from `time.time()`, so the loop
  is visibly returning real data rather than being optimised away.
- **Sensors, enumerated.** `SensorManager.getSensorList(Sensor.TYPE_ALL)` with name, vendor, type
  id and full-scale range — checkable against the emulator's *Virtual sensors* panel. The app
  says on screen that *subscribing* to one is not possible: a `SensorEventListener` means
  implementing a Java interface from Python, and the Java helper class that path needs ships as a
  loose `.class` file in site-packages and never reaches the APK's `classes.dex`. That blocks
  every Python implementation of a Java interface, not just sensors — no callbacks, no
  `BroadcastReceiver`, no `Runnable` posted to the main `Looper` — which is why every value on
  this screen is polled, and why the battery block reads the sticky broadcast with a null
  receiver instead of registering one. See the
  [recipe README](../../README.md#things-to-know) for the mechanism.

A `DIFFERS` verdict is information, not a failure. The two sources really are different code
paths, and where they disagree that is the fact worth knowing.

`src/device.py` holds the JNI work and `src/main.py` only the screen, and the gate is why that
split runs in that order: the `FLET_JNI_READY` check and the `import jnius` behind it are the
first two statements `device.py` executes, so `from device import ...` is what arms them. The
[recipe README](../../README.md#things-to-know) has the mechanism — importing pyjnius is itself
the process's first JNI call, so a check inside `main()` would already be too late. The
variable's value is in the header line where you can see it.

Every reader is wrapped individually, because pyjnius raises `JavaException` for a Java-side
throw but a plain `AttributeError` for a member that does not exist, and an unhandled exception
in a Flet handler ends the session with a crash screen.

The header line is entirely computed on device: pyjnius and Python versions,
[`page.platform`](https://flet.dev/docs/controls/page/#flet.Page.platform), `FLET_JNI_READY`, the
basename of the file `jnius.jnius` was really loaded from — `libjnius-jnius.so`, because Flet
relocates every extension into `jniLibs/<abi>/` under a mangled name — and both
`MAIN_ACTIVITY_HOST_CLASS_NAME` and `MAIN_ACTIVITY_CLASS_NAME`, so you can see the holder class
pyjnius reaches for *and* your own Activity behind it.

The run happens in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread),
driven from the slider's `on_change_end` so it fires once per gesture rather than once per pixel.
Disabling the slider is not on its own enough to keep two runs from overlapping — that only queues
the new state for the client, and `run_thread` submits to a shared pool — so the handler reads
`disabled` back as its guard. It ends in an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update does
not reach background threads.

`pyproject.toml` keeps `[project] dependencies` at `flet` alone and puts `pyjnius` under
`[tool.flet.android] dependencies`, which `flet build` appends only for Android targets. `uv` never
sees pyjnius at all, and that is the point: a desktop `flet run` shows the Android-only card, and
an iOS build is never asked to resolve a wheel that does not exist. `requires-python` is `>=3.12`,
the floor of the Python versions pyjnius has wheels for on Flet's mobile index.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator:

```bash
uv run flet build apk
```
