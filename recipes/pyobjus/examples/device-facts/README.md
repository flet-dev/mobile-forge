# pyobjus device facts

**iOS only.** There is no Android wheel for pyobjus, so on Android or on your desktop this app is
a single card saying so and pointing at [pyjnius](https://pyjnius.readthedocs.io/en/latest/).
Build it for iOS and it fills with numbers.

One screen of iOS platform facts read through [`pyobjus.autoclass`](https://pyobjus.readthedocs.io/en/latest/api.html#pyobjus.autoclass),
with every value printed next to a **second, independent reading of the same thing** — so the app
itself says whether the two agree instead of asking you to trust one number. Nothing here needs a
permission or an `Info.plist` usage string, and every figure is checkable against the phone in
your hand.

What it demonstrates:

- **Identity, cross-checked against raw `objc_msgSend`.** `UIDevice.currentDevice` gives
  `systemName`, `systemVersion` and `model` through pyobjus; the same three selectors go out again
  through `ctypes` and `libobjc`, which is the route CPython's own `platform.ios_ver()` takes in
  `_ios_support`. Each row prints `same`, `DIFFERS`, or `unchecked` when one side had nothing to
  say — off iOS both sides come back empty, because UIKit is not loaded in the process and
  `autoclass` resolves names over the images that are. This is also the block where the
  property-versus-method ambiguity is unavoidable: `currentDevice` is declared as a *class*
  property in UIKit's header, and pyobjus surfaces class properties as callables — verified on
  Foundation's identically-shaped `NSProcessInfo.processInfo`, not on UIKit, so the app resolves
  both spellings rather than betting on one.
- **The machine, cross-checked against the stdlib.** `NSProcessInfo.processInfo()` gives
  `physicalMemory` against `os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')`,
  `processorCount` against `os.cpu_count()`, and `systemUptime` against `time.monotonic()` — read
  back to back, so the printed difference is the cost of the calls between them. Beside those,
  `isLowPowerModeEnabled()` with parentheses and every property above it without any, which is the
  whole rule in one line. The block closes with `NSThread.isMainThread` as read inside the
  worker, while the header line prints the same property as read inside `main()`.
- **Storage, tied back to Flet.** `NSFileManager.URLsForDirectory_inDomains_(14, 1)` is
  `NSApplicationSupportDirectory` in `NSUserDomainMask`, and Flet documents
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  as the `data` subdirectory of exactly that, so the app joins one to the other and reports
  whether they match. Then `temporaryDirectory.path` against `tempfile.gettempdir()`, and
  `NSBundle.mainBundle()`'s `bundlePath` and `bundleIdentifier` beside `sys.prefix` — Python's own
  view of where it is living inside the bundle. Teaches the parenthesis rule concretely: `count`
  and `path` take none, `objectAtIndex_(i)` does, and the NSArray in between supports neither
  `len()` nor iteration nor `[0]`.
- **What a call costs — three numbers, not one.** The slider picks 200 to 20,000 iterations and
  the screen times a selector returning a primitive (`NSString.length()`), a selector returning an
  object (`NSDate.date()`) and a property read (`NSProcessInfo.systemUptime`). The middle one runs
  seventeen to twenty times the first on a Mac, because every returned object is wrapped with a
  walk over its runtime class — that ratio is what decides whether polling in a loop is viable, and
  polling is the only way to watch a value change from Python here. The last `NSDate` that came
  back is printed as its offset from `time.time()`, so the loop is visibly returning real data
  rather than being optimised away.
- **Argument types, demonstrated live.** The same `fileExistsAtPath_` call is made with a `str`
  (converted to an NSString for you), with an explicit `NSString`, and with `bytes` — which does
  not crash but raises pyobjus's misleading *you've passed … as delegate* error, printed on
  screen. The fourth spelling, a bare `int`, is described and deliberately **not** run: it is
  boxed into an `NSNumber`, the receiver sends that `NSNumber` a string selector, and the uncaught
  Objective-C exception aborts the process with no Python traceback and no Flet crash screen. See
  the [recipe README](../../README.md#things-to-know).

A `DIFFERS` verdict is information, not a failure. The two sources really are different code
paths, and where they disagree that is the fact worth knowing.

Every class the app uses is bound once, at import, and never through an inline `autoclass()`
again. That is not tidiness: `autoclass` hands back an *instance* of the wrapper it builds the
first time a name is asked for and the wrapper *class* itself on every later call, and only the
instance resolves `@property` names to values — so a second inline
`autoclass('NSThread').isMainThread` yields an `ObjcProperty` object rather than a `bool`. Binding
once also skips the class walk the uncached call pays for. Every reader after that is wrapped
individually, because pyobjus raises its own `ObjcException` for some mistakes and a plain
`TypeError` or `AttributeError` for others, and an unhandled exception in a Flet handler ends the
session with a crash screen.

The header line is entirely computed on device: the pyobjus and Python versions,
[`page.platform`](https://flet.dev/docs/controls/page/#flet.Page.platform), `pyobjus.dev_platform`
— the `sys.platform` value baked into the extension when it was compiled, so `ios` from this index
and `darwin` from a Mac build — the basename of the file `pyobjus.pyobjus` was really loaded from,
and `NSThread.isMainThread`. That last one is the slot where the pyjnius screen prints
`FLET_JNI_READY`, and it is the fact anyone calling UIKit has to know.

The run happens in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread),
driven from the slider's `on_change_end` so it fires once per gesture rather than once per pixel.
Disabling the slider is not on its own enough to keep two runs from overlapping — that only queues
the new state for the client, and `run_thread` submits to a shared pool — so the handler reads
`disabled` back as its guard. It ends in an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update does
not reach background threads.

`pyproject.toml` keeps `[project] dependencies` at `flet` alone and puts `pyobjus` under
`[tool.flet.ios] dependencies`, which `flet build` appends only for iOS targets. `uv` never sees
pyobjus at all — `uv lock` on this file resolves 52 packages, none of them pyobjus — and that is
the point: a desktop `flet run` shows the iOS-only card instead of a half-true screen built on
PyPI's macOS wheel, and an Android build is never asked to resolve a wheel that does not exist.
`requires-python` is `>=3.12`, the floor of the Python versions pyobjus has wheels for on Flet's
mobile index.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or simulator:

```bash
# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
