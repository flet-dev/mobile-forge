# pyjnius

[`pyjnius`](https://pyjnius.readthedocs.io/en/latest/) calls Java from Python through JNI. On a
phone that means the whole Android framework is reachable from your app code —
`android.os.Build`, `BatteryManager`, `SensorManager`, `ConnectivityManager`, Bluetooth, the
clipboard, anything with a Java API — without writing a Flutter plugin for it. Give it a class
name and it reflects over the class, hands you a Python object with the same methods and fields,
and converts the values in both directions.

**This is an Android-only package, and deliberately so.** JNI has no iOS counterpart, and the
gate is enforced twice: this recipe declares `platforms: [android]`, and the
[`flet-libpyjni`](../flet-libpyjni) recipe behind it refuses any non-Android SDK outright. The
iOS answer is a different package with a different API,
[`pyobjus`](https://pyobjus.readthedocs.io/en/latest/), which binds the Objective-C runtime
instead — see [Other considerations](#other-considerations). Flet's own write-up of the pair is
[Tap into native Android and iOS APIs with Pyjnius and Pyobjus](https://flet.dev/blog/tap-into-native-android-and-ios-apis-with-Pyjnius-and-pyobjus/).

Every Python file in the wheel is byte-identical to upstream's sdist except one line in
`jnius/env.py` (a link-time library list), so [upstream's documentation](https://pyjnius.readthedocs.io/en/latest/quickstart.html)
applies unchanged. What this page adds is the Flet side: what the runtime hands you before your
first call, and which parts of pyjnius do not survive the trip. Everything below about Flet was
read off Flet 0.86.5, which pins serious_python 4.5.1.

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
target is Android, which is exactly the scope pyjnius has.

Leave it in `[project]` instead and your iOS build stops at *Could not find a version that
satisfies the requirement pyjnius*, while on desktop `uv` quietly installs PyPI's macOS, Linux or
Windows build — a library that starts its own JVM and needs a JDK on the machine — so `flet run`
exercises something no device will ever run.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`device-facts`](examples/device-facts) — Android identity, battery and sensors read through
  JNI, each checked against a second source.

## Usage in a Flet app

```python
import os

import flet as ft

# Gate the import, not the first call: `import jnius` is itself the first JNI call.
if os.getenv("FLET_JNI_READY") == "1":
    from jnius import autoclass


def main(page: ft.Page):
    build = autoclass("android.os.Build")
    page.add(ft.Text(f"{build.MANUFACTURER} {build.MODEL}"))


if __name__ == "__main__":
    ft.run(main)
```

`FLET_JNI_READY` is the runtime's own signal, exported by serious_python only when the JNI bridge
loaded, and [`autoclass`](https://pyjnius.readthedocs.io/en/latest/api.html#jnius.autoclass) is
the whole API surface you need behind it. That load is best-effort by design, so it is possible to
be running with `jnius` importable and nothing behind it — and that case is a crash rather than an
exception, which is why the gate goes on the `import` statement and not on the first
`autoclass()`; the first bullet under [Things to know](#things-to-know) has the mechanism. Print
the variable's value on screen while you are developing: it is the fastest way to tell "the bridge
is missing" from "my class name is wrong".

### Reaching your Activity

Anything that needs a `Context` — system services, battery, sensors, the clipboard — starts from
the holder class serious_python parks in the environment:

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

### Threading

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

### Release builds

R8 renames classes while pyjnius looks them up by name, so a release build would otherwise
resolve nothing — and both halves of the fix already ship. serious_python's own
`consumer-rules.pro` keeps `com.flet.serious_python_android.**`, and flet-cli writes
`-keep class com.flet.serious_python_android.** { *; }` plus `-keepnames class * { *; }` as
`android_proguard_rules` defaults.

Add rules for your own classes with
[`[tool.flet.android] proguard_rules`](https://flet.dev/docs/publish/android/), which appends.
Setting `proguard_default_rules = false` drops the defaults entirely, including the
serious_python keep, and the symptom is the one written into that file as a comment —
`type object 'C.f' has no attribute 'mActivity'`.

### App size

The arm64-v8a wheel is 196 KB compressed and 517 KB unpacked; armeabi-v7a is 182 KB and 359 KB.
The extension is about 90% of that. It is small enough that an app bundle, split APKs and a
narrowed [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
are decisions about the rest of your app rather than about this package.

2,362 bytes of the payload are `NativeInvocationHandler.java` and its `.class`, which ship into
the app and are never used — serious_python's junk-file cleanup strips `.c`, `.h`, `.pyi`, `.pyx`
and friends, but neither `.java` nor `.class`. Not worth chasing; mentioned so a payload audit
does not look wrong.

### Other considerations

**A desktop `flet run` does not exercise this package at all.** `uv` never sees pyjnius, because
it is not in `[project] dependencies`, so a desktop run takes whichever branch your app has for a
missing `FLET_JNI_READY` — that branch is what you are testing, not the JNI code behind it. Every
class name, every signature and every conversion has to be validated on an Android device or
emulator.

**There is no iOS wheel.** Use [`pyobjus`](https://pyobjus.readthedocs.io/en/latest/) there — it
has its own [recipe](../pyobjus) in this repository, gated the mirror-image way at
`platforms: [ios]`. It is **not** a drop-in: it binds the Objective-C runtime, so the class
names, the calling convention and the frameworks are all different. An app that needs native APIs
on both platforms writes two backends behind one interface of its own and declares them per
platform:

```toml
[tool.flet.android]
dependencies = ["pyjnius"]

[tool.flet.ios]
dependencies = ["pyobjus"]
```

## Things to know

- **If the JNI bridge never loaded, the first call is not an exception — and the first call is
  `import jnius`.** `libpyjni`'s `Android_JNI_GetEnv` dereferences its cached `JavaVM` pointer
  unconditionally, and that pointer is assigned only in `JNI_OnLoad`. serious_python's
  `System.loadLibrary("pyjni")` is explicitly best-effort, so it is possible to be running with
  `jnius` importable and no bridge behind it. Importing is already too late: `jnius/__init__.py`
  does `from .reflect import *` at module scope, and `reflect.py`'s first class definition binds
  `java.lang.Class` through `MetaJavaClass`, whose `resolve_class` calls `get_jnienv()` at
  class-creation time — so the JNI env is acquired while the `import` statement is still running.
  Gate the **import** on `FLET_JNI_READY`, not the first `autoclass()`, and show a message
  instead; a `try/except` around either will not save you.
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
  the Java side has to come from a Flutter plugin or AAR you add to the app — which works because pyjnius routes every class name through the *application's* `ClassLoader` rather than `JNIEnv->FindClass`, whose loader on a natively-attached thread sees only framework classes. That is what makes your own APK's classes and a plugin's reachable at all, not just `android.*`.
- **Nested classes need a `$`, and the outer class does not expose them.** `autoclass` replaces
  every `.` with `/` to build the JNI path, so `android.os.Build.VERSION` asks for
  `android/os/Build/VERSION` and raises `NoClassDefFoundError`. `Build.VERSION.SDK_INT` is not how
  you spell it either: `reflect.py` builds a class's attributes out of its constructors, methods
  and fields and never calls `getDeclaredClasses`, so a nested class is not an attribute of the
  outer one. Write `autoclass('android.os.Build$VERSION').SDK_INT`,
  `autoclass('android.provider.Settings$Secure')`.
- **A class name the loader cannot resolve does not come back as a clean Python error.**
  `PyJni_FindClass` catches the `ClassNotFoundException`, clears it and returns `NULL`;
  [`find_javaclass`](https://pyjnius.readthedocs.io/en/latest/api.html) wraps that `NULL` in a
  `Class` object, and `autoclass` immediately calls `getConstructors()` on it. `autoclass`'s own
  `if c is None` guard cannot fire, because `find_javaclass` hands back a `Class` instance
  whichever way the lookup went — the `NULL` is buried inside its `LocalRef`. What ART does with a
  JNI call on a null object is not established here — treat a wrong class name as something to
  avoid rather than something to catch.
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
- **Errors arrive in two different shapes.** A Java-side throw is a
  [`JavaException`](https://pyjnius.readthedocs.io/en/latest/api.html) (an `Exception` subclass)
  carrying `.classname`, `.innermessage` and `.stacktrace`, and its `str()` is the whole Java
  stack trace. A member that does not exist is a plain `AttributeError`. An argument list that
  matches no overload is a `JavaException` listing the available signatures. Catch broad
  `Exception` around anything driven by user input — an unhandled exception in a Flet handler ends
  the session with a crash screen.
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

## Build notes (maintainers)

### Recipe shape

The extension does not talk to ART directly. `jnius.jnius` leaves exactly two non-CPython,
non-libc symbols undefined — `PyJni_AndroidGetJNIEnv` and `PyJni_FindClass` — and picks them up
from `libpyjni.so`, a 5–8 KB shared library listed in its `DT_NEEDED` under that bare soname.
`patches/mobile.patch` carries a 77-line preamble on what those two entry points do and why the
recipe needs them; `flet-libpyjni` builds the library, and `requirements.host` is what turns it
into a `Requires-Dist` so that a bare `pyjnius` resolves both wheels.

What has no home in the patch is the runtime contract on the far side of the wheel. None of it
lives in this repository and nothing in a green build of *this* recipe exercises any of it, yet
every consumer-facing claim above rests on it:

- Flet's Android build flattens `libpyjni.so` out of the wheel's `opt/lib/` into
  `jniLibs/<abi>/libpyjni.so` — both the name the bare `DT_NEEDED` wants and the name
  `System.loadLibrary("pyjni")` resolves.
- serious_python makes that `System.loadLibrary` call from Java, over a method channel, **before
  the interpreter starts**. The ordering is the whole point: it is the only way to run
  `libpyjni`'s `JNI_OnLoad`, where the `JavaVM` and the app `ClassLoader` are cached, because the
  `dlopen` behind `dart:ffi` never triggers it. It exports `FLET_JNI_READY=1` on success and
  swallows the failure otherwise, so apps without pyjnius do not pay for a missing library.
- serious_python's `onAttachedToActivity` sets `MAIN_ACTIVITY_HOST_CLASS_NAME`, and its
  `consumer-rules.pro` plus flet-cli's `android_proguard_rules` defaults are what make release
  builds work.

### Upgrade hazards

Most of the consumer-facing claims above are about *Flet*, not about pyjnius, so a Flet bump
invalidates as much as a pyjnius one. Re-read the checklist below on either.

**Re-test the `Cython <3.1` ceiling on a bump rather than carrying it forward.** Nothing in the
repository records why it is there and nothing exercises it, so it survives bumps by inertia. A
desktop build proves nothing about it either — the cross build is where Cython's output has to
compile against the NDK sysroot.

### Re-verification checklist

- **The three serious_python contracts.** That `serious_python_android`'s `run()` still makes the
  `System.loadLibrary("pyjni")` call and still exports `FLET_JNI_READY`; that
  `onAttachedToActivity` still sets `MAIN_ACTIVITY_HOST_CLASS_NAME`; and that the R8 keeps still
  ship. The page above tells app authors to rely on all three.
- **The relocation contract.** The extension is matched by
  `Regex("""\.(cpython-[^/]+|abi3)\.so$""")` and renamed to `libjnius-jnius.so`, and
  `libpyjni.so` is flattened out of `opt/lib/` into the same `jniLibs/<abi>/` directory by a copy
  task that keeps only the basename. A built APK of the example confirms both, per ABI:
  `lib/arm64-v8a/libjnius-jnius.so` (482,424 B) beside `lib/arm64-v8a/libpyjni.so` (7,480 B),
  with `jnius/jnius.soref` left behind in `assets/sitepackages.zip`. Both halves have to keep
  holding: the mangling regex has to keep matching the cp312 slice's *short*
  `jnius.cpython-312.so` name as well as the `cpython-31X-<triplet>` form the 3.13 and 3.14 legs
  emit, and `libpyjni.so` has to keep landing under exactly that basename, since it is resolved
  both by a bare `DT_NEEDED` and by `System.loadLibrary`.
- **That nothing needs `extract_packages`, which is a grep result over six Python files.** The
  wheel is fourteen files — one extension, six Python modules, a Java source and its `.class`,
  and five metadata files — and across all of them the only uses of `__file__`,
  `importlib.resources` and `pkg_resources` are inside `jnius/__init__.py`'s
  `sys.platform == 'win32'` branch and inside `jnius_config.get_classpath()`, which on Android is
  dead code. There is no `getsource` anywhere either, so Flet's default compile-to-`.pyc` is safe.
  Re-run both greps rather than assuming: upstream adding a data file, or moving anything in
  `jnius_config` out from behind `get_classpath()`, changes the answer.
- **That a bare `pyjnius` still resolves per slice, and still does not on iOS.** Upstream
  publishes 49 files for this version — macOS, manylinux, Windows and an sdist — and not one
  carries an `android` or `ios` platform tag, so this index is the only source. Measured one
  resolve per slice the way `flet build` does it
  (`pip install --only-binary :all: --extra-index-url https://pypi.flet.dev`): arm64-v8a,
  armeabi-v7a and x86_64 all resolve on Python 3.12, 3.13 and 3.14, and the legacy 32-bit
  `android_24_x86` slice resolves on 3.12 only. The three iOS slice tags — device, arm64 simulator
  and x86_64 simulator — must keep failing with *Could not find a version that satisfies the
  requirement pyjnius*, which is what the Android-only claim at the top of the page rests on.
- **16 KB alignment.** Every `.so` in both wheels reports 16 KB (`0x4000`) alignment on all of its
  `PT_LOAD` segments, which is what Android's 16 KB page-size devices need.
- **Sizes and the file count are measured**, from the cp314 arm64-v8a and armeabi-v7a wheels.
  Re-measure them in decimal KB — `du` reports binary units — rather than adjusting by eye.
  `libpyjni.so` is built per ABI, so its figure moves independently of the wheel's.

### Coverage gaps

`tests/test_pyjnius.py` skips itself off-device and asserts one thing on it. That single assert is
load-bearing: `autoclass('android.os.Build')` succeeding proves the `.so` resolved `libpyjni.so`,
that `JNI_OnLoad` ran, and that class resolution through the app `ClassLoader` works.

It covers nothing else the page promises — not the conversions, not the `Activity` handle, not
release-mode R8, not the claim that `PythonJavaClass` cannot work. Those rest on reading the code
and on running the [`device-facts`](examples/device-facts) example, not on a green test run.
