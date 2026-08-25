# pyobjus device facts

**iOS only.** There is no Android wheel for pyobjus, so on Android or on your desktop this app is
a single card saying so and pointing at [pyjnius](https://pyjnius.readthedocs.io/en/latest/).
Build it for iOS and it fills with numbers.

One screen of iOS platform facts read through
[`pyobjus.autoclass`](https://pyobjus.readthedocs.io/en/latest/api.html#pyobjus.autoclass), with
every value printed next to a **second, independent reading of the same thing** — so the app
itself says whether the two agree instead of asking you to trust one number. Nothing here needs a
permission or an `Info.plist` usage string, and every figure is checkable against the phone in
your hand.

What it demonstrates:

- **Identity, cross-checked against raw `objc_msgSend`.** `UIDevice.currentDevice` gives
  `systemName`, `systemVersion` and `model` through pyobjus; the same three selectors go out again
  through `ctypes` and `libobjc`, which is the route CPython's own `platform.ios_ver()` takes in
  `_ios_support`. Each row prints `same`, `DIFFERS`, or `unchecked` when one side had nothing to
  say.
- **The machine, cross-checked against the stdlib.** `NSProcessInfo.processInfo()` gives
  `physicalMemory` against `os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')`,
  `processorCount` against `os.cpu_count()`, and `systemUptime` against `time.monotonic()` — read
  back to back, so the printed difference is the cost of the calls between them. The block closes
  with `NSThread.isMainThread` as read inside the worker, while the header line prints the same
  property as read inside `main()`.
- **Storage, tied back to Flet.** `NSFileManager.URLsForDirectory_inDomains_(14, 1)` is
  `NSApplicationSupportDirectory` in `NSUserDomainMask`, and Flet documents
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  as the `data` subdirectory of exactly that, so the app joins one to the other and reports
  whether they match. Then `temporaryDirectory.path` against `tempfile.gettempdir()`, and
  `NSBundle.mainBundle()`'s `bundlePath` and `bundleIdentifier` beside `sys.prefix` — Python's own
  view of where it is living inside the bundle.
- **What a call costs — three numbers, not one.** The slider picks 200 to 20,000 iterations and
  the screen times a selector returning a primitive (`NSString.length()`), a selector returning an
  object (`NSDate.date()`) and a property read (`NSProcessInfo.systemUptime`). The last `NSDate`
  that came back is printed as its offset from `time.time()`, so the loop is visibly returning
  real data rather than being optimised away.
- **Argument types, demonstrated live.** The same `fileExistsAtPath_` call is made with a `str`,
  with an explicit `NSString`, and with `bytes`, whose misleading error is printed on screen. The
  fourth spelling, a bare `int`, is described and deliberately **not** run: it aborts the process
  outright. See the [recipe README](../../README.md#things-to-know).

A `DIFFERS` verdict is information, not a failure. The two sources really are different code
paths, and where they disagree that is the fact worth knowing.

`src/device.py` holds every Objective-C, `ctypes` and timing call and hands back finished lines of
text; `src/main.py` places them and drives the slider. The run happens in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), fired from
the slider's `on_change_end` so it goes once per gesture rather than once per pixel, and ends in
an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach background threads.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or simulator:

```bash
# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
