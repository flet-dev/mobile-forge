"""Read iOS platform facts through the Objective-C runtime, each beside a second reading."""

import ctypes
import ctypes.util
import os
import platform
import sys
import tempfile
import time

import flet as ft

pyobjus = None
IMPORT_ERROR = None
UIDevice = None

# Every class is bound once, here. autoclass() hands back an *instance* of the
# wrapper it builds the first time a name is asked for, and the wrapper class
# itself on every later call — and only the instance resolves @property names to
# values, so a second inline autoclass("NSThread").isMainThread yields the
# ObjcProperty descriptor instead of a bool. Binding once also skips the
# quarter-millisecond class walk that the first call pays for.
try:
    import pyobjus
    from pyobjus import autoclass

    NSBundle = autoclass("NSBundle")
    NSDate = autoclass("NSDate")
    NSFileManager = autoclass("NSFileManager")
    NSProcessInfo = autoclass("NSProcessInfo")
    NSString = autoclass("NSString")
    NSThread = autoclass("NSThread")
except Exception as error:
    # Binding the classes here means the import is not the only thing in this
    # block that can fail, so the sentinel has to cover both — see
    # blocked_reason().
    pyobjus = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

if pyobjus is not None:
    try:
        UIDevice = autoclass("UIDevice")
    except Exception:
        # autoclass resolves names with objc_getClass, over the images already
        # loaded in the process. UIKit is one of them in an iOS app and is not
        # one on a Mac, so this is the expected outcome off device.
        UIDevice = None

LEVELS = [200, 1000, 5000, 20000]
NS_APPLICATION_SUPPORT_DIRECTORY = 14
NS_USER_DOMAIN_MASK = 1
IDENTITY = ("systemName", "systemVersion", "model")


def text(value):
    """Turn an NSString wrapper into a Python str.

    `UTF8String()` answers with `str` for some receiver classes and `bytes` for
    others — the same selector, decided by the object's runtime class — so the
    isinstance check is not defensive padding. Formatting an NSString directly
    is never right: `str(ns)` prints `<NSTaggedPointerString object at 0x…>`.
    """
    if value is None:
        return None
    decoded = value.UTF8String()
    return decoded.decode() if isinstance(decoded, bytes) else decoded


def value_of(owner, name):
    """Read `name` off an Objective-C wrapper whichever way pyobjus exposed it.

    An `@property` arrives already evaluated and a plain selector arrives as a
    callable, and which one a given name is depends on the Objective-C header
    rather than on anything visible from Python. `UIDevice.currentDevice` is a
    class property in UIKit's header but reaches Python as a callable, while
    `systemName` on the instance reaches it as a string — so both spellings are
    resolved instead of guessed. Guessing wrong raises `TypeError: 'int' object
    is not callable` one way and returns an ObjcMethod the other.
    """
    value = getattr(owner, name)
    return value() if callable(value) else value


def objc_runtime():
    """Bind libobjc's three entry points with ctypes — a reader with no pyobjus in it.

    This is the route CPython's own `platform.ios_ver()` takes (`_ios_support`
    in the standard library), so the identity block gets checked against the
    stdlib's mechanism rather than against pyobjus twice.
    """
    library = ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib"
    objc = ctypes.CDLL(library)
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return objc


def objc_text(objc, class_name, *selectors):
    """Send a chain of no-argument selectors from ctypes and read the answer as text.

    `objc_msgSend`'s return type is re-declared mid-chain because it changes:
    every hop but the last returns an `id`, and `UTF8String` returns a
    `const char *`. A null anywhere — an unknown class, a nil return — ends the
    chain as `None` rather than as a crash.
    """
    objc.objc_msgSend.restype = ctypes.c_void_p
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    target = objc.objc_getClass(class_name.encode())
    for selector in selectors:
        if not target:
            return None
        target = objc.objc_msgSend(target, objc.sel_registerName(selector.encode()))
    if not target:
        return None
    objc.objc_msgSend.restype = ctypes.c_char_p
    answer = objc.objc_msgSend(target, objc.sel_registerName(b"UTF8String"))
    return answer.decode() if answer else None


def read_identity():
    """UIDevice's three identity strings, through pyobjus."""
    if UIDevice is None:
        raise RuntimeError("UIDevice is not reachable — UIKit is not in this process")
    device = value_of(UIDevice, "currentDevice")
    return {name: text(value_of(device, name)) for name in IDENTITY}


def read_identity_native():
    """The same three strings sent straight to objc_msgSend from ctypes."""
    objc = objc_runtime()
    return {
        name: objc_text(objc, "UIDevice", "currentDevice", name) for name in IDENTITY
    }


def read_machine():
    """NSProcessInfo's numbers, each next to the stdlib reading of the same thing.

    The two uptimes are read back to back so their difference is the cost of
    the calls between them and nothing else. `SC_PHYS_PAGES` is not defined on
    every platform, hence the guard: a missing second reading has to leave the
    row unchecked rather than claim a disagreement.
    """
    info = NSProcessInfo.processInfo()
    try:
        physical = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        physical = None
    return {
        "memory_objc": info.physicalMemory,
        "memory_python": physical,
        "cpus_objc": info.processorCount,
        "cpus_python": os.cpu_count(),
        "uptime_objc": info.systemUptime,
        "uptime_python": time.monotonic(),
        "os_version": text(info.operatingSystemVersionString),
        "python_os": f"{platform.system()} {platform.release()}",
        "low_power": bool(info.isLowPowerModeEnabled()),
        "main_thread": NSThread.isMainThread,
    }


def read_storage():
    """Where the app may write, from Foundation and from Flet's own environment.

    This block is where the property-versus-method rule bites in ordinary code:
    `count` and `path` take no parentheses, `objectAtIndex_(i)` does, and the
    NSArray in between supports neither `len()` nor iteration nor `[0]`.
    """
    manager = NSFileManager.defaultManager()
    urls = manager.URLsForDirectory_inDomains_(
        NS_APPLICATION_SUPPORT_DIRECTORY, NS_USER_DOMAIN_MASK
    )
    bundle = NSBundle.mainBundle()
    return {
        "support": text(urls.objectAtIndex_(0).path) if urls.count else None,
        "support_count": urls.count,
        "storage_data": os.getenv("FLET_APP_STORAGE_DATA"),
        "temp_objc": text(manager.temporaryDirectory.path),
        "temp_python": tempfile.gettempdir(),
        "bundle_path": text(bundle.bundlePath),
        "bundle_id": text(bundle.bundleIdentifier),
        "prefix": sys.prefix,
    }


def time_calls(count):
    """Time the three shapes of pyobjus call, and check the objects coming back are real.

    They are not one number. A selector returning a primitive is a message send
    and a conversion; a selector returning an object additionally builds a full
    wrapper for the returned instance, walking its class; a property read skips
    the method-lookup half. The gap between the first two is what decides
    whether polling something in a loop is viable, and polling is how you watch
    anything change from Python here.
    """
    sample = NSString.stringWithUTF8String_(b"pyobjus")
    info = NSProcessInfo.processInfo()

    start = time.perf_counter()
    for _ in range(count):
        sample.length()
    primitive = (time.perf_counter() - start) / count * 1e6

    last = None
    start = time.perf_counter()
    for _ in range(count):
        last = NSDate.date()
    returned_object = (time.perf_counter() - start) / count * 1e6
    # Read against the clock here rather than after the third loop: the point is
    # that the objects coming out of that loop are live, and a later comparison
    # would only be measuring how long the timing after it took.
    skew = (last.timeIntervalSince1970() - time.time()) * 1e3

    start = time.perf_counter()
    for _ in range(count):
        _ = info.systemUptime
    attribute = (time.perf_counter() - start) / count * 1e6

    return {
        "count": count,
        "primitive_us": primitive,
        "object_us": returned_object,
        "attribute_us": attribute,
        "skew_ms": skew,
    }


def read_argument_types():
    """Show what pyobjus does with the two argument spellings that look interchangeable.

    A `str` where a selector wants an object is converted for you; `bytes` is
    not — it falls past every conversion branch into pyobjus's
    delegate-construction path and comes back complaining about @protocol
    methods, which says nothing about the real mistake. The third case is
    described on screen and deliberately not run: a bare `int` is boxed into an
    NSNumber, the receiver then sends that NSNumber a string selector, and the
    uncaught Objective-C exception aborts the process — no Python traceback, no
    Flet crash screen, nothing a try/except can reach.
    """
    manager = NSFileManager.defaultManager()
    path = os.getenv("FLET_APP_STORAGE_DATA") or tempfile.gettempdir()
    try:
        manager.fileExistsAtPath_(path.encode())
        as_bytes = "returned without raising"
    except Exception as error:
        as_bytes = f"{type(error).__name__}: {error}"
    return {
        "path": path,
        "as_str": manager.fileExistsAtPath_(path),
        "as_object": manager.fileExistsAtPath_(
            NSString.stringWithUTF8String_(path.encode())
        ),
        "as_bytes": as_bytes,
    }


def extension_origin():
    """Basename of the file `pyobjus.pyobjus` was really loaded from.

    On iOS serious_python turns every extension into a framework and leaves a
    one-line `.fwork` marker where the `.so` used to be, so this reads
    `pyobjus.fwork` on device rather than any path you wrote.
    """
    module = sys.modules.get("pyobjus.pyobjus")
    if module is None:
        return "not loaded"
    origin = getattr(module, "__file__", None) or getattr(
        module.__spec__, "origin", None
    )
    return os.path.basename(origin) if origin else "unknown"


def attempt(reader, *args):
    """Run one reader, returning either its value or the message to print in its place.

    Each block gets its own so that one unreachable class cannot blank the rest
    of the screen — UIKit is exactly that case off device. Only the first line
    of the message is kept, and the net is broad because pyobjus raises its own
    `ObjcException` for some mistakes and plain `TypeError`/`AttributeError`
    for others; an unhandled exception in a Flet handler ends the session with
    a crash screen.
    """
    try:
        return reader(*args), None
    except Exception as error:
        first = str(error).splitlines()[0] if str(error) else ""
        return None, f"{type(error).__name__}: {first}"


def identity_row(field, objc_values, native_values):
    """One identity line: the pyobjus reading, the ctypes reading, and whether they agree."""
    through_pyobjus = objc_values.get(field) if objc_values else None
    through_ctypes = native_values.get(field) if native_values else None
    if through_pyobjus is None or through_ctypes is None:
        verdict = "unchecked"
    else:
        verdict = "same" if through_pyobjus == through_ctypes else "DIFFERS"
    return (
        f"UIDevice.currentDevice.{field} = {through_pyobjus!r} via pyobjus · "
        f"{through_ctypes!r} via objc_msgSend · {verdict}"
    )


def agreement(left, right):
    """Verdict for a pair of readings, where a missing side is not a disagreement."""
    if left is None or right is None:
        return "unchecked"
    return "same" if left == right else "DIFFERS"


def blocked_reason():
    """Why this screen cannot run, or None if it can.

    A class that failed to resolve counts as blocked just as much as a failed
    import does: every row below is built from names bound in that one block,
    so a half-bound module has to end up here rather than reach `main()` and
    raise `NameError` at a walrus line, where nothing renders it and the
    session ends on a crash screen instead of this card.
    """
    if pyobjus is None:
        return (
            f"pyobjus is not usable here — {IMPORT_ERROR}.\n\n"
            "That is the expected state everywhere except iOS. There is no "
            "Android wheel for pyobjus and there will not be one — the Android "
            "answer is pyjnius, which binds Java instead — and on desktop this "
            "app never installs it, because its pyproject.toml declares "
            "pyobjus under [tool.flet.ios] dependencies rather than in "
            "[project] dependencies."
        )
    return None


def main(page: ft.Page):
    """iOS facts read through the Objective-C runtime, each next to a second reading.

    The slider picks how many calls to time; releasing it re-reads every block,
    because uptime, low-power mode and the timings all move between runs.
    Nothing on this screen needs a permission or an Info.plist usage string,
    and every value is checkable against the phone: Settings > General > About
    for the identity block.
    """
    pending = LEVELS[-1]

    def render(result):
        """Fill every row from one result dict."""
        objc_values, objc_error = result["identity"]
        native_values, native_error = result["identity_native"]
        identity_rows.controls = [
            ft.Text(message, size=12, color=ft.Colors.ERROR)
            for message in (objc_error, native_error)
            if message
        ] + [
            ft.Text(
                identity_row(field, objc_values, native_values),
                size=12,
                selectable=True,
            )
            for field in IDENTITY
        ]

        info, error = result["machine"]
        if error:
            machine.value = error
        else:
            machine.value = (
                f"physicalMemory: {info['memory_objc']} via NSProcessInfo, "
                f"{info['memory_python']} via os.sysconf — "
                f"{agreement(info['memory_objc'], info['memory_python'])}\n"
                f"processorCount: {info['cpus_objc']} via NSProcessInfo, "
                f"{info['cpus_python']} via os.cpu_count() — "
                f"{agreement(info['cpus_objc'], info['cpus_python'])}\n"
                f"systemUptime: {info['uptime_objc']:.6f} s, time.monotonic() "
                f"{info['uptime_python']:.6f} s — they differ by "
                f"{(info['uptime_objc'] - info['uptime_python']) * 1e6:+.0f} µs\n"
                f"operatingSystemVersionString: {info['os_version']!r}, "
                f"platform says {info['python_os']!r}\n"
                f"isLowPowerModeEnabled(): {info['low_power']} — a selector, so it "
                f"takes parentheses; the four values above are properties and do not\n"
                f"NSThread.isMainThread in the page.run_thread worker: "
                f"{info['main_thread']}"
            )

        paths, error = result["storage"]
        if error:
            storage.value = error
        else:
            expected = (
                os.path.join(paths["support"], "data") if paths["support"] else None
            )
            storage.value = (
                f"NSApplicationSupportDirectory: {paths['support']!r} "
                f"({paths['support_count']} URL(s) returned)\n"
                f"FLET_APP_STORAGE_DATA: {paths['storage_data']!r} — Flet documents "
                f"it as the data subdirectory of the line above, so "
                f"{agreement(expected, paths['storage_data'])}\n"
                f"temporaryDirectory.path: {paths['temp_objc']!r}, "
                f"tempfile.gettempdir() {paths['temp_python']!r} — "
                f"{agreement(paths['temp_objc'], paths['temp_python'])}\n"
                f"NSBundle.mainBundle(): bundlePath {paths['bundle_path']!r}, "
                f"bundleIdentifier {paths['bundle_id']!r}\n"
                f"sys.prefix: {paths['prefix']!r}"
            )

        cost, error = result["timing"]
        if error:
            calls.value = error
        else:
            calls.value = (
                f"{cost['count']} × NSString.length() — {cost['primitive_us']:.1f} µs "
                f"per call (a selector returning a primitive)\n"
                f"{cost['count']} × NSDate.date() — {cost['object_us']:.1f} µs per call "
                f"({cost['object_us'] / cost['primitive_us']:.0f}× as much: every "
                f"returned object is wrapped, class walk included)\n"
                f"{cost['count']} × NSProcessInfo.systemUptime — "
                f"{cost['attribute_us']:.1f} µs per call (a property read)\n"
                f"the last NSDate that came back reads {cost['skew_ms']:+.1f} ms "
                f"against time.time()"
            )
            caption.value = f"{cost['count']} calls of each kind"

        args, error = result["arguments"]
        if error:
            arguments.value = error
        else:
            arguments.value = (
                f"fileExistsAtPath_({args['path']!r}) = {args['as_str']} — a str is "
                f"converted to an NSString for you\n"
                f"…the same path as an explicit NSString = {args['as_object']}\n"
                f"…the same path as bytes = {args['as_bytes']}\n"
                "…the same path as an int would not raise at all: it is boxed into "
                "an NSNumber, the receiver sends that NSNumber a string selector, and "
                "the uncaught Objective-C exception aborts the process. No traceback, "
                "no crash screen, nothing to catch — so check argument types in "
                "Python before the call."
            )

    def run():
        """Read every block and fill the screen. Runs off the UI thread.

        `page.run_thread` never retrieves the worker's future, so anything
        raised here would surface nowhere at all and leave the previous run's
        numbers on screen. Every reader carries its own error and the closing
        `page.update()` is what makes any of it appear.
        """
        try:
            render(
                {
                    "identity": attempt(read_identity),
                    "identity_native": attempt(read_identity_native),
                    "machine": attempt(read_machine),
                    "storage": attempt(read_storage),
                    "timing": attempt(time_calls, pending),
                    "arguments": attempt(read_argument_types),
                }
            )
        except Exception as error:
            caption.value = f"{type(error).__name__}: {error}"
        finally:
            workload.disabled = False
            page.update()

    def start():
        """Dispatch a re-read at the level the slider was released on.

        Bound to `on_change_end` so it fires once per gesture. The guard reads
        `disabled` back rather than trusting the assignment: disabling only
        queues the new state for the client, and `run_thread` submits to a
        shared pool, so a second release inside that window would put two
        workers on the same rows.
        """
        nonlocal pending
        if workload.disabled:
            return
        workload.disabled = True
        pending = LEVELS[int(workload.value)]
        page.update()
        page.run_thread(run)

    def preview():
        """Caption the level under the thumb while it is still moving."""
        caption.value = f"{LEVELS[int(workload.value)]} calls of each kind"

    page.appbar = ft.AppBar(title=ft.Text("iOS device facts"), center_title=True)
    blocked = blocked_reason()
    if blocked:
        page.add(
            ft.SafeArea(
                expand=True,
                content=ft.Card(
                    content=ft.Container(padding=16, content=ft.Text(blocked, size=13))
                ),
            )
        )
        return

    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"pyobjus {pyobjus.__version__} · Python "
                        f"{platform.python_version()} · {page.platform.value} · "
                        f"dev_platform={pyobjus.dev_platform} · "
                        f"{extension_origin()} · NSThread.isMainThread in main() "
                        f"{NSThread.isMainThread}",
                        size=11,
                        selectable=True,
                    ),
                    ft.Text(
                        "identity: pyobjus vs raw objc_msgSend",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                    ),
                    identity_rows := ft.Column(spacing=2),
                    ft.Text("machine", size=12, weight=ft.FontWeight.BOLD),
                    machine := ft.Text(size=12, selectable=True),
                    ft.Text("storage", size=12, weight=ft.FontWeight.BOLD),
                    storage := ft.Text(size=12, selectable=True),
                    caption := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    workload := ft.Slider(
                        value=len(LEVELS) - 1,
                        min=0,
                        max=len(LEVELS) - 1,
                        divisions=len(LEVELS) - 1,
                        on_change=preview,
                        on_change_end=start,
                    ),
                    calls := ft.Text(size=12, selectable=True),
                    ft.Text("argument types", size=12, weight=ft.FontWeight.BOLD),
                    arguments := ft.Text(size=12, selectable=True),
                ],
            ),
        )
    )

    preview()
    start()


if __name__ == "__main__":
    ft.run(main)
