# pyobjus

[`pyobjus`](https://pyobjus.readthedocs.io/en/latest/) calls Objective-C from Python. On a phone
that means the whole iOS runtime is reachable from your app code — `NSProcessInfo`, `NSFileManager`,
`NSLocale`, `NSTimeZone`, `NSBundle`, `UIDevice`, anything with an Objective-C class — without
writing a Flutter plugin for it. Give it a class name and it resolves the class through
`objc_getClass`, hands you a Python object carrying that class's selectors and properties, and
converts the values in both directions.

**This is an iOS-only package, and deliberately so.** There is no Android wheel on this index and
there will not be one: the recipe is gated `platforms: [ios]`, and Objective-C has no Android
counterpart. The Android answer is a different package with a different API,
[`pyjnius`](https://pyjnius.readthedocs.io/en/latest/), which binds Java through JNI and has
[its own recipe in this repository](../pyjnius). Flet's own write-up of the pair is
[Tap into native Android and iOS APIs with Pyjnius and Pyobjus](https://flet.dev/blog/tap-into-native-android-and-ios-apis-with-Pyjnius-and-pyobjus/).

The Python half of the wheel is upstream's, so [upstream's tutorials](https://pyobjus.readthedocs.io/en/latest/core_tutorials.html)
apply. What is worth knowing is how the extension is wired under Flet, and where pyobjus's own API
surprises you. Everything below about the Flet side was read off Flet 0.86.5, which pins
serious_python 4.5.1.

## Install

```toml
# pyproject.toml
[project]
dependencies = [
    "flet",
]

[tool.flet.ios]
dependencies = [
    "pyobjus",
]
```

Put it under [`[tool.flet.ios]`](https://flet.dev/docs/publish/#app-dependencies) rather than in
`[project] dependencies`. `flet build` appends that table to your dependencies only when the
target is iOS, which is exactly the scope pyobjus has; leave it in `[project]` and your Android
build stops at *Could not find a version that satisfies the requirement pyobjus*, while on desktop
`uv` quietly installs PyPI's macOS build — which does work, but only halfway (see
[Things to know](#things-to-know)) — so `flet run` exercises something no device will run.

Because the package is installed for one target and not the others, guard the import in app code
and let a desktop or Android run say so on screen rather than raise.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`device-facts`](examples/device-facts) — iOS identity, machine, storage and call costs read
  through the Objective-C runtime, each checked against a second source.

## Usage in a Flet app

Bind the class once at module level, then read a property and call a selector on the object it
hands back:

```python
import flet as ft
from pyobjus import autoclass

NSProcessInfo = autoclass("NSProcessInfo")


def main(page: ft.Page):
    info = NSProcessInfo.processInfo()   # a selector, so it takes parentheses
    cores = info.processorCount          # an @property, so it does not
    name = info.operatingSystemVersionString.UTF8String()
    if isinstance(name, bytes):          # UTF8String answers str for some receivers
        name = name.decode()
    page.add(ft.Text(f"{name} · {cores} cores"))
```

Three of those lines are decisions the API will not warn you about:
[`autoclass`](https://pyobjus.readthedocs.io/en/latest/api.html#pyobjus.autoclass) bound once
rather than called inline, a selector told apart from a property, and a return type that depends on
the receiver's runtime class. All three are in [Things to know](#things-to-know), which is worth
reading before the first call rather than after it.

### Storage

pyobjus writes nothing of its own, but
[`NSFileManager`](https://developer.apple.com/documentation/foundation/nsfilemanager) is the API
you will reach for through it, and the two directory questions have exact answers.

`NSFileManager.URLsForDirectory_inDomains_(14, 1)` — `NSApplicationSupportDirectory` in
`NSUserDomainMask`, the two constants spelled out in Foundation's `NSPathUtilities.h` — returns the
directory that
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is a `data` subdirectory of. Flet documents that relationship on
[`StoragePaths.get_application_support_directory`](https://flet.dev/docs/services/storagepaths/#flet.StoragePaths.get_application_support_directory),
and path_provider maps its `applicationSupport` to `applicationSupportDirectory` on Apple
platforms. Prefer the environment variable: one `os.getenv` rather than four selector calls, and
the same variable on both platforms. The [`device-facts`](examples/device-facts) example joins one
to the other and reports on screen whether they agree.

`NSFileManager.temporaryDirectory.path` and `tempfile.gettempdir()` matched exactly on a macOS run;
nothing here establishes that on a phone, so the example prints both rather than this page
promising it. Note the spelling — `temporaryDirectory` and `path` are properties and take no
parentheses, `NSFileManager.defaultManager()` is a selector and does.

### Threading

**Find out whether your app's Python is on the iOS main thread before you call UIKit — do not
assume it is.** serious_python's `runProgram` documents its `sync` flag as *"Set `sync` to `true`
to synchronously run Python program; otherwise the program starts in a new thread"*, so on that
documented default every pyobjus call is already on a worker thread — and which flag Flet passes is
not established on this page. A
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) worker is one
hop further out again. Rather than assert what a given Flet release does, the
[`device-facts`](examples/device-facts) example reads
[`NSThread`](https://developer.apple.com/documentation/foundation/nsthread)`.isMainThread` inside
`main()` and inside a `run_thread` worker and prints both — one line of app code, and the answer
for the version you actually shipped.

Foundation is fine off the main thread: a worker-thread probe on macOS read `NSProcessInfo`
properties, `NSDate` and `NSTimeZone` with no complaint. UIKit is where Apple's main-thread rule
applies, and pyobjus gives you no dispatch helper — it is a plain message-sending bridge, so
whatever you send goes out on whichever thread you are on. Keep UIKit work to read-only identity
queries and leave anything that draws to Flet.

The two Flet-side rules apply as everywhere else: `run_thread` never retrieves the worker's future,
so an exception raised in a worker surfaces nowhere at all — wrap the body — and auto-update does
not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Call cost

**Cost splits sharply by return type, and that split is what you design around.** Over 20,000
iterations on an M-series Mac: a primitive-returning selector (`NSString.length()`) 2.3–2.9 µs, a
property read 2.9–3.6 µs, and an object-returning selector (`NSDate.date()`) 41–58 µs — seventeen
to twenty times as much, because pyobjus builds a full wrapper, class walk included, for every
object that comes back.

Read the *ratio* and re-measure the absolutes: the spread is mostly the interpreter, not the
machine. The same loop on the same Mac gives 2.6–2.9 / 3.2–3.6 / 50–55 µs on CPython 3.12 and
2.4–2.5 / 3.1–3.3 / 41–42 µs on 3.13. Hoist objects out of loops and prefer primitive-returning
selectors and property reads inside them. The ratio also decides whether polling a value in a loop
is viable, and polling is the only way to watch something change from Python here — see the
delegate bullet below. The [`device-facts`](examples/device-facts) example re-measures all three on
the device you care about.

### App size

Approximately 260 KB compressed and 960 KB unpacked, some 750 KB of that the single extension.
Installed on the device it comes to about 1.1 MB, because pip byte-compiles the six Python modules
on the way in — which is also why the total moves a little with the compiling interpreter. Sizes
are decimal; `du -h` reports binary units and shows a smaller number for the same bytes.

There is no lever worth pulling. Almost all of it is one extension, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing to
remove, and [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
is an Android setting an iOS-only package never reaches.

### Other considerations

**A macOS `flet run` genuinely exercises pyobjus, which makes it a trap of its own.** PyPI ships
macOS universal2 wheels, so Foundation really works on your Mac — but only that half. UIKit classes
do not exist there (`autoclass('UIDevice')` raises *Unable to find class b'UIDevice'*), and
`dev_platform` — the build machine's `sys.platform` baked into the extension at compile time —
reads `darwin` rather than `ios`, which changes the struct-return path in pyobjus's own headers.
Keeping pyobjus out of `[project] dependencies` keeps that build off your desktop entirely, which
is the point of the `[tool.flet.ios]` table. Validate anything UIKit-shaped on a simulator or a
device.

An app that needs native APIs on both platforms writes two backends behind one interface of its own
and declares them per platform:

```toml
[tool.flet.android]
dependencies = ["pyjnius"]

[tool.flet.ios]
dependencies = ["pyobjus"]
```

[`pyjnius`](../pyjnius) is **not** a drop-in: it binds the JVM, so the class names, the calling
convention and the frameworks are all different. On this side the bridge is the process's own
Objective-C runtime, already up before your code runs, so the first `autoclass` can go out
immediately — there is no readiness flag to wait on the way the Android backend has one.

## Things to know

- **Passing an `int` where a selector wants an object kills the process.** This is the single most
  dangerous thing in the library. `convert_py_to_nsobject` boxes the int into an `NSNumber`, the
  receiver sends that `NSNumber` a string selector, and the resulting `NSInvalidArgumentException`
  is uncaught Objective-C: measured in an isolated subprocess,
  `NSFileManager.defaultManager().fileExistsAtPath_(7)` exits with signal 6 and
  `-[__NSCFNumber length]: unrecognized selector sent to instance …` on stderr. No Python
  traceback, nothing a `try/except` can reach, no process left to draw a Flet crash screen with.
  Pass a `str`, which converts correctly, or build the object explicitly
  (`NSString.stringWithUTF8String_`, `NSNumber.numberWithInt_`), and validate types in Python
  before the call. `bytes` does not crash but is just as wrong: it falls past every conversion
  branch into the delegate-construction path and raises *You've passed b'…' as delegate, but there
  is no @protocol methods declared*, which says nothing about the real mistake — it is only correct
  for `char *` parameters such as `stringWithUTF8String_`.
- **Bind each class once, at module level, and never call `autoclass` inline.** The first
  `autoclass('X')` in a process returns an *instance* of the wrapper it builds; every later call
  returns the wrapper *class* itself, because the cache stores the class and `autoclass` only
  instantiates it on the miss. Selectors work on both, `@property` names do not: on the instance
  they resolve to values, on the class you get the raw `ObjcProperty` object. Measured and
  deterministic — `[type(autoclass('NSThread').isMainThread).__name__ for _ in range(3)]` gives
  `['bool', 'ObjcProperty', 'ObjcProperty']`, while a reference bound once and read four times
  gives `bool` every time, and keeps giving `bool` after the inline calls. Binding once is also the
  cheaper spelling: an uncached `autoclass` cost 0.18–0.40 ms on an M-series Mac against 0.29 µs
  for a cached one.
- **A `@property` is a value, a selector is a callable, the Objective-C header decides which, and
  nothing in Python shows you.**
  [`NSProcessInfo`](https://developer.apple.com/documentation/foundation/nsprocessinfo)`.processInfo().processorCount`
  *is* an int, and `processorCount()` raises `TypeError: 'int' object is not callable`;
  `isLowPowerModeEnabled` on the same object is an `ObjcMethod` and needs its parentheses. A
  *class* property is a third case and lands on the callable side: `NSProcessInfo.processInfo` is
  declared `@property (class, readonly, strong)` in Foundation's header but arrives as an
  `ObjcMethod`, because pyobjus builds a class's property list from its *instance* properties and
  picks class properties up as metaclass methods — so
  [`UIDevice`](https://developer.apple.com/documentation/uikit/uidevice)`.currentDevice` wants
  parentheses too. Reads are live rather than snapshots: `systemUptime` read either side of a
  1.05 s sleep differed by 1.0551 s. In app code,
  `v = getattr(obj, name); v = v() if callable(v) else v`.
- **`UTF8String()` returns `str` for some receivers and `bytes` for others** — the same selector,
  decided by the object's runtime class. In one macOS process, `__NSCFString` receivers
  (`operatingSystemVersionString`, `hostName`, `NSLocale.localeIdentifier`) gave `str`, while
  `NSTaggedPointerString` and `Swift.__StringStorage` receivers (`processName`, the result of
  `stringWithUTF8String_`, `NSTimeZone.name`) gave `bytes`. Use a three-line helper —
  `v = ns.UTF8String(); return v.decode() if isinstance(v, bytes) else v` — and never format an
  NSString directly: `str(nsstring)` prints `<__main__.NSTaggedPointerString object at 0x…>`.
- **`NSArray` and `NSDictionary` are not Python containers.** There is no protocol map here as
  there is in pyjnius: on an `NSArray`, `len()`, `list()`, `[0]` and `iter()` all raise
  `TypeError`. What works is `a.count` — an int property, so no parentheses; `a.count()` raises
  `TypeError: 'int' object is not callable` — and `a.objectAtIndex_(i)`. Write
  `[a.objectAtIndex_(i) for i in range(a.count)]`.
- **Selector-to-name conversion is one rule with one exception.** Every `:` in the selector becomes
  `_`, the trailing one included: `stringWithUTF8String:` → `stringWithUTF8String_`,
  `URLsForDirectory:inDomains:` → `URLsForDirectory_inDomains_`. The exception is `class`, a Python
  keyword, exposed as `oclass` and mapped back to the `class` selector when the call goes out.
- **A `nil` object return arrives as `None`, cleanly**, for both selectors and properties —
  `objectForKey_` on a missing key, `NSFileManager.defaultManager().delegate`. Calling through it
  then gives an ordinary `AttributeError: 'NoneType' object has no attribute …`.
- **A struct return outside pyobjus's nine registered types raises `KeyError`.**
  `NSProcessInfo.processInfo().operatingSystemVersion` raises `KeyError: b'q'` from
  `objc_py_types.py`, whose type table is keyed by `str` while the encoding arrives as `bytes`.
  Only `NSRect`, `NSRange`, `NSPoint`, `NSSize`, `CCFRange`, `_NSRange`, `CGPoint`, `CGSize` and
  `CGRect` are pre-registered and therefore safe. Use the string-returning sibling where one exists
  — `operatingSystemVersionString` instead of `operatingSystemVersion`.
- **`import pyobjus` is expected to print two `dlopen` failures on iOS.** Its module init calls
  `pyobjc_internal_init()`, which `dlopen`s
  `/System/Library/Frameworks/Foundation.framework/Versions/Current/Foundation` and then a nonsense
  fallback under `/Groups`, `printf`-ing an error for each. iOS frameworks are flat — the iOS SDK's
  `Foundation.framework` has no `Versions/` directory — and all four strings are present in the
  shipped `.so`. On macOS that path does exist and the import is silent. Harmless either way,
  because Foundation is already loaded in any Flet iOS app, which is why `autoclass` works
  regardless. Worth knowing so two lines in `console.log` are not mistaken for a failure.
- **Do not reach for `load_framework(INCLUDE.X)` as a portable helper.** Those constants are
  hard-coded `/System/Library/Frameworks/<name>.framework` strings in
  [`dylib_manager`](https://pyobjus.readthedocs.io/en/latest/api.html), fed to
  `NSBundle.bundleWithPath_` — absolute macOS paths, not managed indirection. You should not need
  them: `autoclass` resolves names over the images already loaded in the process, and Foundation is
  certainly one, since pyobjus's own module init depends on it. UIKit is the interesting case, and
  the [`device-facts`](examples/device-facts) example's identity block is the on-screen check
  rather than a promise made here.
- **On device the module's `__file__` is a path nobody wrote.** serious_python turns every iOS
  extension into a framework and leaves a one-line marker where the `.so` was, so `pyobjus.pyobjus`
  reports `pyobjus.fwork`, with the binary itself inside `Frameworks/pyobjus.pyobjus.framework`.
  Nothing in this package reads that, but code of your own that locates files relative to a
  module's `__file__` will not find what it expects.
- **Delegates and `@protocol` callbacks are implemented, but nothing here proves they work on a
  phone.** pyobjus builds a delegate class at runtime with `objc_allocateClassPair` and routes
  callbacks through `forwardInvocation:`, and it does work on a desktop build: an
  `NSXMLParserDelegate` written in Python received every start-element and end-document callback
  for a small document. That is a macOS binary, not this wheel, and no test in this recipe
  exercises the path on device. Until one does, treat delegates as unproven on iOS and poll
  instead: read state on demand and drive refreshes from Flet. Polling is the shape the Android
  bridge wants too, for entirely different reasons, so an app carrying both backends can put one
  polling interface over the pair.
- **[`dereference()`](https://pyobjus.readthedocs.io/en/latest/api.html#pyobjus.dereference) is not
  pyjnius's `cast()`.** It reads C pointer and out-parameter values — a `ctypes.Structure`, a
  `CArray` with `return_count`, an `ObjcClassInstance` from an address. There is no cast because
  there is nothing to cast: a returned object already arrives wrapped as its *runtime* class, which
  is why an `id` return shows up as `__NSCFString` or `Swift.__SwiftDeferredNSArray` rather than as
  the declared type.

## Build notes (maintainers)

Much of what this page tells app authors is about *Flet*, not about pyobjus, so a Flet bump
invalidates as much as a pyobjus one. The patch carries its own preamble covering all five hunks;
`meta.yaml` carries no comments at all, so the notes below are the only record of why the recipe
has the shape it does.

### Recipe shape

`platforms: [ios]` is a gate rather than a gap — Objective-C has no Android counterpart, so there
is nothing to build there, and the gate is what stops CI attempting a slice that could only fail.

libffi comes in as `requirements.host: libffi` instead of upstream's own `ios-deps-install/` tree,
which its `setup.py` hard-requires and which only its CI script produces. forge promotes a host
requirement into `Requires-Dist` only when the name begins with `flet-`, so the host wheel stays
out of the metadata and libffi ends up *inside* the extension. That is what makes the wheel
self-contained, and no file in the recipe says so.

The wheel also installs a stray `objc_classes/objc_classes/` tree into site-packages — about 34 KB
of Objective-C sources with no runtime role. They sit under the wheel's `.data/data/` scheme root,
and serious_python installs with `pip install --target`, which maps that root onto site-packages
itself; its junk-file cleanup then strips the `.h` headers on the way in. Nothing there is a `.py`,
so nothing extra becomes importable. Not worth chasing, recorded so a payload audit does not look
wrong.

### Upgrade hazards

- **The build tag is load-bearing, not incidental.** Upstream now publishes its own iOS wheels, and
  pip prefers the build-tagged file over an untagged one at the same version — that is the only
  reason the forge wheel wins. Anything that drops or resets `build: number` hands iOS builds back
  to upstream's wheel, which fails at Flet's byte-compile step over its bundled Python 2 example
  scripts (`compile.packages` defaults to on). Re-check that hunk 4 of the patch still applies: it
  is what keeps that examples tree out.
- **A serious_python bump can move the extension.** `sync_site_packages.sh` loops over `so` and
  `dylib` and calls `create_xcframework_from_dylibs`, which cuts the path at the first `.` and
  translates `/` to `.` — so `pyobjus/pyobjus.cpython-312-iphoneos.so` becomes
  `pyobjus.pyobjus.framework` with `pyobjus/pyobjus.fwork` left behind. Both the naming rule and
  the marker are things this page tells app authors to expect.

### Re-verification checklist

- **Metadata and linkage.** `METADATA` must still carry no `Requires-Dist`, and libffi must still
  be inside the extension: `nm -a` shows `_ffi_call` and `_ffi_prep_cif` as defined text symbols
  (`T`) and `_ffi_closure_SYSV` as a local one (`t`) rather than as undefined references. Beside
  its own install name, `otool -L` on each slice should list exactly
  `@rpath/Python.framework/Python`, `/usr/lib/libobjc.A.dylib` and `/usr/lib/libSystem.B.dylib`.
- **The resolve matrix, recording which filename resolved.** One resolve per slice the way
  `flet build` does it — `pip download --only-binary :all: --platform <tag> --index-url
  https://pypi.org/simple --extra-index-url https://pypi.flet.dev` — for the device tag and both
  simulator tags on every supported Python; nine for nine at the last measurement. The filename
  matters as much as the exit status, because upstream publishes competing iOS wheels and a resolve
  that succeeds against *theirs* is a regression. Confirm at least one Android tag still fails with
  *Could not find a version that satisfies the requirement pyobjus*, which is what the Install
  section's import guard rests on.
- **Slice inventory and file type.** Three Python versions × device, arm64 simulator and x86_64
  simulator. Every slice must be an `MH_DYLIB` rather than an `MH_BUNDLE`, or serious_python's
  framework conversion will not take it as-is.
- **`__file__` and `getsource` audit.** Across the wheel's six Python modules the only use of
  `__file__`, `importlib.resources` or `pkg_resources` is in `dylib_manager.load_dylib`, on a
  branch reached only when `usr_path=False` is passed, and there is no `getsource` anywhere — which
  is why Flet's default compile-to-`.pyc` is safe. Re-audit before trusting that again.
- **Measured figures are measured.** Sizes and file counts come from the cp312 device wheel, the
  timings from 20,000-iteration loops on an M-series Mac against PyPI's macOS build — a different
  compilation from the shipped one. Re-measure rather than adjusting by eye, and treat the desktop
  timings as ratios rather than as device numbers.
- **Licensing.** pyobjus itself is MIT, read out of `dist-info/licenses/LICENSE` in the installed
  wheel, so it matches its own badge and Things to know carries no licence bullet. The statically
  linked libffi is the half nobody can discover from the metadata; its terms have not been read out
  of a forge wheel. Check `<dist-info>/licenses/` after the next build and add a
  `- **Licensing:** …` bullet only if what is in there is not permissive.

### Coverage gaps

`tests/test_pyobjus.py` is one test. Its single assert is load-bearing — `NSDate` through
`autoclass` succeeding proves the framework-ized extension loaded, that `pyobjc_internal_init` did
not abort the module, and that class resolution through `objc_getClass` works — but it covers
nothing this page promises about properties, conversions, UIKit reachability or the framework
marker. It also catches `(ImportError, Exception)` around the import and skips, so **any** failure
on device is recorded as a skip rather than a red run: a green mobile leg is not on its own evidence
that the extension loaded. Tightening that net is the cheapest improvement available here.

The delegate path is the obvious candidate for the next real test, and it is fragile in two ways a
bump could expose. Its dispatch still spells the dict iteration `delegate_register.iteritems()` — a
Python 2 leftover that survives only because Cython rewrites it, so a Cython change could turn it
into an `AttributeError` inside a `cdef` callback where nothing would surface it — and
`respondsToSelector:` is registered with the encoding `"v@::"`, a void return where a `BOOL` is
expected. Neither shows up in a build. Consumers are told the feature is unproven on iOS; the way
to change that is a device test, not an edit to this page.
