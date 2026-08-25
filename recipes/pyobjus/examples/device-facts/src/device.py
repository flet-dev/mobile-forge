"""iOS platform facts read through the Objective-C runtime, each beside a second one.

Every value on screen is produced here and handed back as finished lines of text.
Composing "X via pyobjus, Y via the stdlib — same or DIFFERS" is part of reading the
fact, not part of drawing it, so main.py only has to place the lines.
"""

import ctypes
import ctypes.util
import os
import platform
import sys
import tempfile
import time

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


def agreement(left, right):
    """Verdict for a pair of readings, where a missing side is not a disagreement."""
    if left is None or right is None:
        return "unchecked"
    return "same" if left == right else "DIFFERS"


def attempt(reader, *args):
    """Run one reader, returning its value beside the message to print instead.

    The net is broad because pyobjus raises its own `ObjcException` for some
    mistakes and a plain `TypeError` or `AttributeError` for others, and an
    unhandled exception in a Flet handler ends the session with a crash screen.
    Only the first line of the message is kept.
    """
    try:
        return reader(*args), None
    except Exception as error:
        first = str(error).splitlines()[0] if str(error) else ""
        return None, f"{type(error).__name__}: {first}"


def objc_runtime():
    """Bind libobjc's two lookup entry points with ctypes — no pyobjus in this reader.

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


def identity_lines():
    """One line per identity string: the pyobjus reading, the ctypes one, the verdict.

    Off iOS both sides come back empty, and the rows read `unchecked` rather
    than `DIFFERS`: UIKit is not loaded in the process, and neither reader can
    resolve a class that is not there. Each half is attempted separately so one
    of them failing still prints the other.
    """
    through_pyobjus, pyobjus_error = attempt(read_identity)
    through_ctypes, ctypes_error = attempt(read_identity_native)
    lines = [message for message in (pyobjus_error, ctypes_error) if message]
    for field in IDENTITY:
        left = through_pyobjus.get(field) if through_pyobjus else None
        right = through_ctypes.get(field) if through_ctypes else None
        lines.append(
            f"UIDevice.currentDevice.{field} = {left!r} via pyobjus · "
            f"{right!r} via objc_msgSend · {agreement(left, right)}"
        )
    return lines


def machine_lines():
    """NSProcessInfo's numbers, each next to the stdlib reading of the same thing.

    The two uptimes are read back to back, so the printed difference is the cost
    of the calls between them and nothing else. `isLowPowerModeEnabled()` takes
    parentheses and the four properties above it do not, which is the whole
    property-versus-selector rule in one block.
    """
    info = NSProcessInfo.processInfo()
    try:
        physical = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        # Not defined on every platform. A missing second reading has to leave
        # the row unchecked rather than claim a disagreement.
        physical = None
    memory = info.physicalMemory
    cpus = info.processorCount
    uptime = info.systemUptime
    monotonic = time.monotonic()
    python_os = f"{platform.system()} {platform.release()}"
    return [
        f"physicalMemory: {memory} via NSProcessInfo, {physical} via os.sysconf — "
        f"{agreement(memory, physical)}",
        f"processorCount: {cpus} via NSProcessInfo, {os.cpu_count()} via "
        f"os.cpu_count() — {agreement(cpus, os.cpu_count())}",
        f"systemUptime: {uptime:.6f} s, time.monotonic() {monotonic:.6f} s — they "
        f"differ by {(uptime - monotonic) * 1e6:+.0f} µs",
        f"operatingSystemVersionString: {text(info.operatingSystemVersionString)!r}, "
        f"platform says {python_os!r}",
        f"isLowPowerModeEnabled(): {bool(info.isLowPowerModeEnabled())} — a selector, "
        f"so it takes parentheses; the four values above are properties and do not",
        f"NSThread.isMainThread in the page.run_thread worker: {NSThread.isMainThread}",
    ]


def storage_lines():
    """Where the app may write, from Foundation and from Flet's own environment.

    This block is where the parenthesis rule bites in ordinary code: `count` and
    `path` take none, `objectAtIndex_(i)` does, and the NSArray in between
    supports neither `len()` nor iteration nor `[0]`.
    """
    manager = NSFileManager.defaultManager()
    urls = manager.URLsForDirectory_inDomains_(
        NS_APPLICATION_SUPPORT_DIRECTORY, NS_USER_DOMAIN_MASK
    )
    support = text(urls.objectAtIndex_(0).path) if urls.count else None
    expected = os.path.join(support, "data") if support else None
    storage_data = os.getenv("FLET_APP_STORAGE_DATA")
    temp = text(manager.temporaryDirectory.path)
    bundle = NSBundle.mainBundle()
    return [
        f"NSApplicationSupportDirectory: {support!r} ({urls.count} URL(s) returned)",
        f"FLET_APP_STORAGE_DATA: {storage_data!r} — Flet documents it as the data "
        f"subdirectory of the line above, so {agreement(expected, storage_data)}",
        f"temporaryDirectory.path: {temp!r}, tempfile.gettempdir() "
        f"{tempfile.gettempdir()!r} — {agreement(temp, tempfile.gettempdir())}",
        f"NSBundle.mainBundle(): bundlePath {text(bundle.bundlePath)!r}, "
        f"bundleIdentifier {text(bundle.bundleIdentifier)!r}",
        f"sys.prefix: {sys.prefix!r}",
    ]


def timing_lines(count):
    """Time the three shapes of pyobjus call, and prove the objects coming back live.

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
    per_object = (time.perf_counter() - start) / count * 1e6
    # Read against the clock here rather than after the third loop: the point is
    # that the objects coming out of that loop are live, and a later comparison
    # would only be measuring how long the timing after it took.
    skew = (last.timeIntervalSince1970() - time.time()) * 1e3

    start = time.perf_counter()
    for _ in range(count):
        _ = info.systemUptime
    attribute = (time.perf_counter() - start) / count * 1e6

    return [
        f"{count} × NSString.length() — {primitive:.1f} µs per call (a selector "
        f"returning a primitive)",
        f"{count} × NSDate.date() — {per_object:.1f} µs per call "
        f"({per_object / primitive:.0f}× as much: every returned object is wrapped, "
        f"class walk included)",
        f"{count} × NSProcessInfo.systemUptime — {attribute:.1f} µs per call "
        f"(a property read)",
        f"the last NSDate that came back reads {skew:+.1f} ms against time.time()",
    ]


def argument_lines():
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
    as_object = manager.fileExistsAtPath_(NSString.stringWithUTF8String_(path.encode()))
    return [
        f"fileExistsAtPath_({path!r}) = {manager.fileExistsAtPath_(path)} — a str is "
        f"converted to an NSString for you",
        f"…the same path as an explicit NSString = {as_object}",
        f"…the same path as bytes = {as_bytes}",
        "…the same path as an int would not raise at all: it is boxed into an "
        "NSNumber, the receiver sends that NSNumber a string selector, and the "
        "uncaught Objective-C exception aborts the process. No traceback, no crash "
        "screen, nothing to catch — so check argument types in Python before the call.",
    ]


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


def header(platform_name):
    """The line that describes this build rather than this phone.

    `dev_platform` is the `sys.platform` value baked into the extension when it
    was compiled — `ios` from Flet's index, `darwin` from a Mac build — and
    `NSThread.isMainThread` here is read inside `main()`, where the machine
    block reads the same property inside a worker.
    """
    return (
        f"pyobjus {pyobjus.__version__} · Python {platform.python_version()} · "
        f"{platform_name} · dev_platform={pyobjus.dev_platform} · "
        f"{extension_origin()} · NSThread.isMainThread in main() "
        f"{NSThread.isMainThread}"
    )


def blocked_reason():
    """Why this screen cannot run, or None if it can.

    A class that failed to resolve counts as blocked just as much as a failed
    import does: every row below is built from names bound in that one block,
    so a half-bound module has to end up here rather than reach `main()` and
    raise `NameError`, where nothing renders it and the session ends on a crash
    screen instead of this card.
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


def read_all(count):
    """Every block on the screen, as finished lines of text.

    Each block runs behind its own net so that one unreachable class cannot
    blank the rest of the screen — UIKit is exactly that case off device.
    """
    blocks = {
        "identity": (identity_lines,),
        "machine": (machine_lines,),
        "storage": (storage_lines,),
        "timing": (timing_lines, count),
        "arguments": (argument_lines,),
    }
    result = {}
    for name, call in blocks.items():
        lines, message = attempt(*call)
        result[name] = lines if message is None else [message]
    return result
