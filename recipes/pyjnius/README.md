# pyjnius

[`pyjnius`](https://pyjnius.readthedocs.io/en/latest/) calls Java from Python through JNI. On a
phone that means the whole Android framework is reachable from your app code —
`android.os.Build`, `BatteryManager`, `SensorManager`, `ConnectivityManager`, Bluetooth, the
clipboard, anything with a Java API — without writing a Flutter plugin for it. Give it a class
name and it reflects over the class, hands you a Python object with the same methods and fields,
and converts the values in both directions.

**This is an Android-only package, and deliberately so.** There is no iOS wheel on this index and
there will not be one: JNI has no iOS counterpart. The iOS answer is a different package with a
different API, [`pyobjus`](https://pyobjus.readthedocs.io/en/latest/), which binds the
Objective-C runtime instead — see [iOS notes](#ios-notes). Flet's own write-up of the pair is
[Tap into native Android and iOS APIs with Pyjnius and Pyobjus](https://flet.dev/blog/tap-into-native-android-and-ios-apis-with-Pyjnius-and-pyobjus/).

Every Python file in the wheel is byte-identical to upstream's sdist except one line in
`jnius/env.py` (a link-time library list), so [upstream's documentation](https://pyjnius.readthedocs.io/en/latest/quickstart.html)
applies unchanged. What is worth knowing is how the bridge is wired under Flet, and which parts of
pyjnius do not survive the trip. Everything below about the Flet side was read off Flet 0.86.5,
which pins serious_python 4.5.1.

## Install

```toml
# pyproject.toml
[project]
dependencies = [
    "flet",
]

[tool.flet.android]
dependencies = [
    "pyjnius",
]
```

Put it under [`[tool.flet.android]`](https://flet.dev/docs/publish/#app-dependencies) rather than
in `[project] dependencies`. `flet build` appends that table to your dependencies only when the
target is Android, which is exactly the scope pyjnius has; leave it in `[project]` and your iOS
build stops at *Could not find a version that satisfies the requirement pyjnius*, while on desktop
`uv` quietly installs PyPI's macOS, Linux or
Windows build — a library that starts its own JVM and needs a JDK on the machine — so `flet run`
exercises something no device will ever run.

Nothing else to configure. `flet-libpyjni` — the JNI shim the extension links against — is a
`Requires-Dist` of the wheel and comes along on its own: resolving the way `flet build` does
(`pip install --only-binary :all: --extra-index-url https://pypi.flet.dev`) for Android arm64-v8a
on Python 3.14, with only `pyjnius` asked for, downloaded the pyjnius wheel **and** a matching
`flet_libpyjni-…-android_24_arm64_v8a.whl`.

A bare `pyjnius` really does resolve from this index on every Android slice. Upstream publishes 49
files for this version — macOS, manylinux, Windows and an sdist — and not one carries an `android`
or `ios` platform tag, so there is nothing on PyPI a mobile target can select. Measured, one
resolve per slice: arm64-v8a, armeabi-v7a and x86_64 all resolve on Python 3.12, 3.13 and 3.14,
and the legacy 32-bit `android_24_x86` slice resolves on 3.12 only. The three iOS slice tags —
device, arm64 simulator and x86_64 simulator — all come back with *Could not find a version that
satisfies the requirement pyjnius*, so guard the import in app code and let a desktop or iOS run
say so on screen rather than raise.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. The wheel is fourteen files — one extension, six Python modules, a Java source
and its `.class`, and five metadata files — and across all of them the only uses of `__file__`,
`importlib.resources` and `pkg_resources` are inside `jnius/__init__.py`'s `sys.platform ==
'win32'` branch and inside `jnius_config.get_classpath()`, which on Android is dead code (see
[Things to know](#things-to-know)). There is no `getsource` anywhere, so Flet's default
compile-to-`.pyc` is safe, and the extension carries a CPython ABI tag on every slice, so it runs
straight out of Android's relocated `jniLibs`.

Release builds need no extra ProGuard/R8 configuration either — Flet already writes the keep rules
pyjnius needs. See [Android notes](#android-notes) for what happens if you switch them off.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`device-facts`](examples/device-facts) — Android identity, battery and sensors read through
  JNI, each checked against a second source.

## Threading

Any thread can call into Java, and pyjnius attaches it to the JVM for you: `get_jnienv()` calls
`AttachCurrentThread` on every single call. What it never does under Flet is detach. pyjnius ships
an auto-detach hook — it monkey-patches `threading.Thread.run` to call
[`jnius.detach()`](https://pyjnius.readthedocs.io/en/latest/api.html#jnius.detach) in a `finally`
— but `jnius/__init__.py` guards it with `if "ANDROID_ARGUMENT" in os.environ`, and that variable
comes from python-for-android. Flet does not set it: it appears nowhere in serious_python 4.5.1 or
in the Flet 0.86.5 tree.

In practice that means:

- Work handed to [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
  is fine. Those threads come from a shared, long-lived pool, so the set of attached threads is
  bounded by the pool.
- A `threading.Thread` you start yourself and let die should end with `jnius.detach()`.

The two Flet-side rules apply as everywhere else: `run_thread` never retrieves the worker's
future, so an exception raised in a worker surfaces nowhere at all — wrap the body — and
auto-update does not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Android notes

The extension does not talk to ART directly. `jnius.jnius` leaves exactly two non-CPython,
non-libc symbols undefined — `PyJni_AndroidGetJNIEnv` and `PyJni_FindClass` — and picks them up
from `libpyjni.so`, a 5–8 KB shared library listed in its `DT_NEEDED` under that bare soname
and shipped by the `flet-libpyjni` wheel. Flet's Android build flattens it out of the wheel's
`opt/lib/` into `jniLibs/<abi>/libpyjni.so`, which is both the name the bare `DT_NEEDED` wants and
the name `System.loadLibrary("pyjni")` resolves.

That `System.loadLibrary` call is the part you get for free. serious_python makes it from Java,
over a method channel, **before the interpreter starts** — which is the only way to run
`libpyjni`'s `JNI_OnLoad`, because the `dlopen` behind `dart:ffi` never triggers it. `JNI_OnLoad`
caches two things: the `JavaVM`, and the application's `ClassLoader`, taken from
`ActivityThread.currentApplication().getClassLoader()`.

The `ClassLoader` half is why `PyJni_FindClass` exists at all. `JNIEnv->FindClass` takes its loader
from the current native call frame, and a thread attached from native code has no frame, so it
falls back to the system loader, which only sees framework classes. Routing every caller-supplied
class name through the app's loader instead means classes from your own APK and from Flutter
plugins are reachable, not just `android.*`.

When that load succeeds serious_python exports **`FLET_JNI_READY=1`** into the interpreter's
environment. Check it before touching `jnius`, and put its value on screen:

```python
if os.getenv("FLET_JNI_READY") == "1":
    from jnius import autoclass
```

The load is best-effort by design — it is wrapped in a `catch` so that apps without pyjnius do not
pay for a missing library — and if it did not happen there is nothing to catch on the Python side.
See [Things to know](#things-to-know).

To reach your app's `Activity`, ask for the holder class serious_python parks in the environment:

```python
import os
from jnius import autoclass

activity = autoclass(os.getenv("MAIN_ACTIVITY_HOST_CLASS_NAME")).mActivity
context = activity.getApplicationContext()
```

`MAIN_ACTIVITY_HOST_CLASS_NAME` is set to `com.flet.serious_python_android.PythonActivity`, a
seven-line class inside the Flet plugin whose only member is a static `mActivity`. It is **not**
kivy's `org.kivy.android.PythonActivity`, which is what most pyjnius material on the web reaches
for and which does not exist in a Flet app. `MAIN_ACTIVITY_CLASS_NAME` is set alongside it and
names your real Activity class.

**Release builds work as-is.** R8 renames classes while pyjnius looks them up by name, so this
would otherwise break; both halves of the fix already ship. serious_python's own
`consumer-rules.pro` keeps `com.flet.serious_python_android.**`, and flet-cli writes
`-keep class com.flet.serious_python_android.** { *; }` plus `-keepnames class * { *; }` as
`android_proguard_rules` defaults. Add rules for your own classes with
`[tool.flet.android] proguard_rules`, which appends; setting `proguard_default_rules = false`
drops the defaults entirely, including the serious_python keep, and the symptom is the one written
into that file as a comment — `type object 'C.f' has no attribute 'mActivity'`.

ABI coverage differs by Python version: Python 3.12 ships four Android slices including the legacy
32-bit `android_24_x86`, while 3.13 and 3.14 ship three (arm64-v8a, armeabi-v7a, x86_64). Every
`.so` in both wheels reports 16 KB (`0x4000`) alignment on all of its `PT_LOAD` segments, which is
what Android's 16 KB page-size devices need.

## iOS notes

There is no iOS wheel, and this is a gate rather than a gap: the recipe declares
`platforms: [android]`, and `flet-libpyjni`'s build script refuses any other SDK outright. The
package index for pyjnius contains twenty-two files and not one mentions iOS.

Use [`pyobjus`](https://pyobjus.readthedocs.io/en/latest/) there — it has its own recipe in this
repository, gated the mirror-image way at `platforms: [ios]`. It is **not** a drop-in: it binds
the Objective-C runtime, so the class names, the calling convention and the frameworks are all
different. An app that needs native APIs on both platforms writes two backends behind one
interface of its own and declares them per platform:

```toml
[tool.flet.android]
dependencies = ["pyjnius"]

[tool.flet.ios]
dependencies = ["pyobjus"]
```

Everything in [Android notes](#android-notes) — `libpyjni`, `JNI_OnLoad`, the app `ClassLoader`,
`FLET_JNI_READY`, `PythonActivity.mActivity` — is an Android-runtime concept with no iOS analogue.

## Things to know

- **If the JNI bridge never loaded, the first call is not an exception — and the first call is
  `import jnius`.** `libpyjni`'s `Android_JNI_GetEnv` dereferences its cached `JavaVM` pointer
  unconditionally, and that pointer is assigned only in `JNI_OnLoad`. serious_python's
  `System.loadLibrary("pyjni")` is explicitly best-effort, so it is possible to be running with
  `jnius` importable and no bridge behind it. Importing is already too late: `jnius/__init__.py`
  does `from .reflect import *` at module scope, and `reflect.py`'s first class definition binds
  `java.lang.Class` through `MetaJavaClass`, whose `resolve_class` calls `get_jnienv()` at
  class-creation time — so the JNI env is acquired while the `import` statement is still running. Gate the **import** on
  `FLET_JNI_READY`, not the first `autoclass()`, and show a message instead; a `try/except` around
  either will not save you.
- **`PythonJavaClass` and `@java_method` — every listener and callback — cannot work in a Flet
  app.** Implementing a Java interface from Python goes through
  `autoclass('org.jnius.NativeInvocationHandler')`, and that class ships in the wheel only as
  `jnius/src/org/jnius/NativeInvocationHandler.class` inside site-packages. Android loads DEX, not
  `.class` files, and nothing in Flet or serious_python dexes it or puts `jnius/src` on a
  classpath — the only code that would is `jnius_config.get_classpath()`, which belongs to the
  JVM-starting backend Android never uses. Read out of a built APK of the
  [`device-facts`](examples/device-facts) example: the class is there as
  `jnius/src/org/jnius/NativeInvocationHandler.class` inside `assets/sitepackages.zip`, and
  `classes.dex` contains no `org/jnius` type at all. Where you would register a listener, poll
  instead: read state on demand
  (`BatteryManager.getIntProperty`, `SensorManager.getSensorList`, a sticky broadcast via
  `registerReceiver(None, filter)`) and drive refreshes from Flet. If you truly need a callback,
  the Java side has to come from a Flutter plugin or AAR you add to the app.
- **Nested classes need a `$`, and the outer class does not expose them.** `autoclass` replaces
  every `.` with `/` to build the JNI path, so `android.os.Build.VERSION` asks for
  `android/os/Build/VERSION` and raises `NoClassDefFoundError`. `Build.VERSION.SDK_INT` is not how
  you spell it either: `reflect.py` builds a class's attributes out of its constructors, methods
  and fields and never calls `getDeclaredClasses`, so a nested class is not an attribute of the
  outer one. Write `autoclass('android.os.Build$VERSION').SDK_INT`,
  `autoclass('android.provider.Settings$Secure')`.
- **A class name the loader cannot resolve does not come back as a clean Python error.**
  `PyJni_FindClass` catches the `ClassNotFoundException`, clears it and returns `NULL`;
  `find_javaclass` wraps that `NULL` in a `Class` object, and `autoclass` immediately calls
  `getConstructors()` on it. `autoclass`'s own `if c is None` guard cannot fire, because
  `find_javaclass` hands back a `Class` instance whichever way the lookup went — the `NULL` is
  buried inside its `LocalRef`. What ART does with a JNI call on a null object is not established
  here — treat a wrong class name as something to avoid rather than something to catch.
- **Values come back typed, so you rarely need `cast()`.** A Java `String` arrives as `str`,
  `boolean` as `bool`, `int`/`long` as `int`, `String[]` as `list[str]`, `null` as `None`; an
  object declared as `Object` — a collection element, a `getSystemService` result — arrives as the
  wrapper for its *runtime* class, with that class's methods on it. `java.util.List`, `Map`,
  `Map$Entry`, `Collection`, `Iterator` and `java.lang.Iterable`, `Comparable`, `AutoCloseable`
  are in `jnius.protocol_map`, so a `List` is directly iterable. Public instance fields read
  and write.
  The exception is `byte[]`, which comes back as a `jnius.ByteArray`.
- **Never `cast()` to `java.lang.Object`.** pyjnius's `java.lang.Object` is a hand-written stub
  with two methods, `getClass` and `hashCode` — not even `toString` — so casting to it throws the
  whole API away and every call after it is an `AttributeError`. `java.lang.Class` is the same
  kind of stub. Cast to the concrete class you mean to call, if at all.
- **Errors arrive in two different shapes.** A Java-side throw is a `JavaException` (an
  `Exception` subclass) carrying `.classname`, `.innermessage` and `.stacktrace`, and its `str()`
  is the whole Java stack trace. A member that does not exist is a plain `AttributeError`. An
  argument list that matches no overload is a `JavaException` listing the available signatures.
  Catch broad `Exception` around anything driven by user input — an unhandled exception in a Flet
  handler ends the session with a crash screen.
- **`autoclass()` is expensive once per class and free afterwards.** It walks the constructors,
  the entire class hierarchy, every method and every field, with `include_protected` and
  `include_private` both defaulting to true — then caches, so `autoclass(x) is autoclass(x)`. Do
  it at import or in a worker thread, not inside a redraw.
- **Two stray top-level modules come with the wheel.** `top_level.txt` reads
  `jnius / jnius_config / setup_sdist`, so `import setup_sdist` succeeds in your app. Both are
  upstream's own packaging, byte-identical to the sdist, and 5,582 bytes of namespace noise between
  them. Do not call `jnius_config`: only the JVM-starting backends read it, and only they set its
  `vm_running` flag — so on Android its getters are meaningless, and `set_classpath` and friends
  neither raise nor take effect, they silently do nothing.
- **Size.** The arm64-v8a wheel is 196 KB compressed and 517 KB unpacked; armeabi-v7a is 182 KB
  and 359 KB. The extension is about 90% of that, and `libpyjni.so` behind it is another 7,480
  bytes on arm64-v8a — it is built per ABI, so 5,480 on armeabi-v7a, 6,692 on x86 and 7,320 on
  x86_64. 2,362 bytes are `NativeInvocationHandler.java` and `.class`, which ship into the
  app payload and are never used — serious_python's junk-file cleanup strips `.c`, `.h`, `.pyi`,
  `.pyx` and friends, but neither `.java` nor `.class`. Not worth chasing; mentioned so a payload
  audit does not look wrong.

## Build notes (maintainers)

The patch carries its own 77-line preamble covering all four hunks, so what is left here is what a
bump can silently invalidate. This recipe is unusual in that most of the consumer-facing claims
above are about *Flet*, not about pyjnius, so a Flet bump invalidates as much as a pyjnius one.

- **Re-test the `Cython <3.1` ceiling on a bump rather than carrying it forward.** Nothing in the
  repository records why it is there and nothing exercises it, so it survives bumps by inertia. A
  desktop build proves nothing about it either — the cross build is where Cython's output has to
  compile against the NDK sysroot.
- **The whole bridge lives outside this recipe.** `libpyjni.so` comes from `flet-libpyjni`, and
  the `System.loadLibrary("pyjni")` that runs its `JNI_OnLoad` comes from serious_python, which
  Flet pins. Nothing in a green build of *this* recipe exercises either. After a serious_python
  bump, re-check that `serious_python_android`'s `run()` still makes the `loadLibrary` call and
  still exports `FLET_JNI_READY`, and that `onAttachedToActivity` still sets
  `MAIN_ACTIVITY_HOST_CLASS_NAME` — the README tells app authors to rely on all three.
- **`tests/test_pyjnius.py` skips itself off-device and asserts one thing on it.** That single
  assert is load-bearing: `autoclass('android.os.Build')` succeeding proves the `.so` resolved
  `libpyjni.so`, that `JNI_OnLoad` ran, and that class resolution through the app `ClassLoader`
  works. It does not cover anything the Things-to-know list promises about conversions, the
  `Activity` handle, or release-mode R8.
- **Re-check the relocation contract on a serious_python bump.** The extension is matched by
  `Regex("""\.(cpython-[^/]+|abi3)\.so$""")` and renamed to `libjnius-jnius.so`, and
  `libpyjni.so` is flattened out of `opt/lib/` into the same `jniLibs/<abi>/` directory by a copy
  task that keeps only the basename. A built APK of the example confirms both, per ABI:
  `lib/arm64-v8a/libjnius-jnius.so` (482,424 B) beside `lib/arm64-v8a/libpyjni.so` (7,480 B),
  with `jnius/jnius.soref` left behind in `assets/sitepackages.zip`. Both halves have to keep
  holding: the mangling regex has to
  keep matching the cp312 slice's *short* `jnius.cpython-312.so` name as well as the
  `cpython-31X-<triplet>` form the 3.13 and 3.14 legs emit, and `libpyjni.so` has to keep landing
  under exactly that basename, since it is resolved both by a bare `DT_NEEDED` and by
  `System.loadLibrary`.
- **The claim that nothing needs `extract_packages` is a grep over the wheel's six Python files.**
  Re-run it on a bump rather than assuming: upstream adding a data file, or moving anything in
  `jnius_config` out from behind `get_classpath()`, changes the answer.
- **Sizes and the file count are measured**, from the cp314 arm64-v8a and armeabi-v7a wheels.
  Re-measure them rather than adjusting by eye.
