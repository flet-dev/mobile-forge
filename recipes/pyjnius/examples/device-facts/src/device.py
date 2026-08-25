"""Android platform facts read through JNI, each beside a second, independent reading."""

import ctypes
import os
import platform
import sys
import time

# The import is what has to be gated, not the first autoclass(): pyjnius
# resolves java.lang.Class while jnius/reflect.py executes, so the process's
# first JNI call happens inside `import jnius` — before any line of app code
# gets to run a check. Importing this module is therefore the gate.
JNI_READY = os.getenv("FLET_JNI_READY") == "1"
jnius = None
IMPORT_ERROR = None

if JNI_READY:
    try:
        import jnius
        from jnius import autoclass
    except Exception as error:
        IMPORT_ERROR = f"{type(error).__name__}: {error}"

PROP_VALUE_MAX = 92
MIB = 1024 * 1024
LEVELS = [200, 1000, 5000, 20000]
ACTIVITY_HOST_FALLBACK = "com.flet.serious_python_android.PythonActivity"

# Each android.os.Build constant next to the system property Android fills it from.
IDENTITY = (
    ("Build.MANUFACTURER", "ro.product.manufacturer"),
    ("Build.MODEL", "ro.product.model"),
    ("Build.DEVICE", "ro.product.device"),
    ("Build.VERSION.RELEASE", "ro.build.version.release"),
    ("Build.VERSION.SDK_INT", "ro.build.version.sdk"),
)


def describe(error):
    """One line for an exception: its type and the first line of its message.

    A `JavaException` carries the whole Java stack trace in its message, so only
    the first line is worth putting on a phone screen.
    """
    first = str(error).splitlines()[0] if str(error) else ""
    return f"{type(error).__name__}: {first}"


def attempt(reader, *args):
    """Run one reader, returning either its value or the message to print instead.

    Every block gets this because the two failures pyjnius produces do not look
    alike: a Java-side throw arrives as `JavaException`, but a member that does
    not exist is a plain `AttributeError` — and an unhandled exception in a Flet
    handler ends the session with a crash screen.
    """
    try:
        return reader(*args), None
    except Exception as error:
        return None, describe(error)


def verdict(left, right):
    """`same`, `DIFFERS`, or `unchecked` when one of the two sides had nothing to say.

    A property this app is not allowed to read is not a disagreement.
    """
    if left is None or right is None:
        return "unchecked"
    return "same" if left == right else "DIFFERS"


def blocked_reason():
    """Why this screen cannot run, or None if it can.

    The `FLET_JNI_READY` check is not politeness. serious_python calls
    `System.loadLibrary("pyjni")` before starting the interpreter and sets this
    variable only if that succeeded; without it libpyjni's `JNI_OnLoad` never
    ran, and the first JNI call reads a JavaVM pointer that was never assigned.
    That is a crash with no Python exception to catch, which is why the variable
    is read at the top of this module, ahead of `import jnius`.
    """
    if not JNI_READY:
        return (
            "FLET_JNI_READY is not set, so serious_python's "
            'System.loadLibrary("pyjni") did not run and jnius was never '
            "imported.\n"
            "That is the expected state off Android: there is no iOS wheel for "
            "pyjnius — the iOS counterpart is pyobjus — and a desktop run has "
            "no JNI behind it either."
        )
    if jnius is None:
        return f"FLET_JNI_READY is set but pyjnius did not import — {IMPORT_ERROR}."
    return None


def extension_origin():
    """Basename of the file `jnius.jnius` was really loaded from.

    Flet moves every extension into `jniLibs/<abi>/` under a mangled name, so on
    device this is `libjnius-jnius.so` and not a path inside the app. Which
    attribute survives that move varies, hence the fallback.
    """
    module = sys.modules.get("jnius.jnius")
    if module is None:
        return "not loaded"
    origin = getattr(module, "__file__", None) or getattr(
        module.__spec__, "origin", None
    )
    return os.path.basename(origin) if origin else "unknown"


def banner(platform_name):
    """The header line: versions, the JNI flag, and the two names the bridge hangs off."""
    return (
        f"pyjnius {jnius.__version__} · Python {platform.python_version()} · "
        f"{platform_name} · FLET_JNI_READY={os.getenv('FLET_JNI_READY')} · "
        f"{extension_origin()} · activity host "
        f"{os.getenv('MAIN_ACTIVITY_HOST_CLASS_NAME')} → "
        f"{os.getenv('MAIN_ACTIVITY_CLASS_NAME')}"
    )


def application_context():
    """The app's Context, via the Activity serious_python parks for exactly this.

    `MAIN_ACTIVITY_HOST_CLASS_NAME` names a holder class inside the Flet plugin
    whose static `mActivity` field is your Activity. It is not kivy's
    `org.kivy.android.PythonActivity`, which is what most pyjnius snippets on the
    web reach for and which does not exist in a Flet app.
    """
    host = os.getenv("MAIN_ACTIVITY_HOST_CLASS_NAME") or ACTIVITY_HOST_FALLBACK
    return autoclass(host).mActivity.getApplicationContext()


def property_reader():
    """Bind libc's __system_property_get — the way to read a property with no JVM in it."""
    getter = getattr(ctypes.CDLL("libc.so"), "__system_property_get")
    getter.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    getter.restype = ctypes.c_int
    return getter


def read_properties():
    """The five identity properties, straight out of libc.

    A zero length means the property does not exist or this app is not allowed
    to read it, which is not the same as it being empty — reporting it as a value
    would make the row below claim ART and libc disagree when only one of them
    answered. `None` is what marks the row unchecked instead.
    """
    getter = property_reader()
    values = {}
    for _, name in IDENTITY:
        buffer = ctypes.create_string_buffer(PROP_VALUE_MAX)
        length = getter(name.encode(), buffer)
        values[name] = buffer.value.decode() if length > 0 else None
    return values


def read_identity():
    """The same five facts through ART reflection.

    `android.os.Build$VERSION` has to be spelled with a `$`. pyjnius turns the
    name it is given straight into a JNI path, so `android.os.Build.VERSION`
    asks the class loader for `android/os/Build/VERSION`, which does not exist.
    """
    build = autoclass("android.os.Build")
    version = autoclass("android.os.Build$VERSION")
    return {
        "Build.MANUFACTURER": build.MANUFACTURER,
        "Build.MODEL": build.MODEL,
        "Build.DEVICE": build.DEVICE,
        "Build.VERSION.RELEASE": version.RELEASE,
        "Build.VERSION.SDK_INT": str(version.SDK_INT),
    }


def identity_lines():
    """The five identity facts, the ART reading beside the libc one, with a verdict each.

    The two sides are read separately on purpose: folding them into one reader
    would let a failure on either side erase the other's values, and half an
    answer is still worth printing.
    """
    java, java_error = attempt(read_identity)
    native, native_error = attempt(read_properties)
    lines = []
    for field, prop in IDENTITY:
        left = java.get(field) if java else None
        right = native.get(prop) if native else None
        left_text = repr(left) if left is not None else "unavailable"
        right_text = repr(right) if right is not None else "unavailable"
        lines.append(
            f"{field} = {left_text} · {prop} = {right_text} · {verdict(left, right)}"
        )
    return lines, " · ".join(m for m in (java_error, native_error) if m) or None


def machine_lines():
    """ART's view of the machine, next to the stdlib's view of the same machine."""
    runtime = autoclass("java.lang.Runtime").getRuntime()
    system = autoclass("java.lang.System")
    cpus_java, cpus_python = runtime.availableProcessors(), os.cpu_count()
    kernel_java, kernel_python = system.getProperty("os.version"), os.uname().release
    # Round before subtracting, so the three heap figures add up as printed.
    total = round(runtime.totalMemory() / MIB, 1)
    free = round(runtime.freeMemory() / MIB, 1)
    return [
        f"processors: {cpus_java} via Runtime, {cpus_python} via os.cpu_count()"
        f" — {verdict(cpus_java, cpus_python)}",
        f"kernel: {kernel_java!r} via System.getProperty, {kernel_python!r} via"
        f" os.uname() — {verdict(kernel_java, kernel_python)}",
        f"ART heap: {total} MiB claimed = {round(total - free, 1)} MiB used +"
        f" {free} MiB free, ceiling {runtime.maxMemory() / MIB:.1f} MiB",
    ]


def battery_lines(context):
    """Charge and charging state twice: from BatteryManager, then from the sticky broadcast.

    The two really are separate sources. `getIntProperty` asks the battery
    service for a value now; `ACTION_BATTERY_CHANGED` is the last broadcast the
    system posted, fetched without registering anything by passing a null
    receiver — which is also the shape any "read Android state on demand" answer
    takes here, since a real BroadcastReceiver would need a Java class this app
    cannot supply.
    """
    context_class = autoclass("android.content.Context")
    battery_manager = autoclass("android.os.BatteryManager")
    intent = autoclass("android.content.Intent")
    intent_filter = autoclass("android.content.IntentFilter")

    service = context.getSystemService(context_class.BATTERY_SERVICE)
    sticky = context.registerReceiver(
        None, intent_filter(intent.ACTION_BATTERY_CHANGED)
    )
    level = sticky.getIntExtra(battery_manager.EXTRA_LEVEL, -1)
    scale = sticky.getIntExtra(battery_manager.EXTRA_SCALE, -1)
    status = sticky.getIntExtra(battery_manager.EXTRA_STATUS, -1)
    plugged = sticky.getIntExtra(battery_manager.EXTRA_PLUGGED, -1)

    service_percent = service.getIntProperty(battery_manager.BATTERY_PROPERTY_CAPACITY)
    broadcast_percent = round(100 * level / scale) if scale > 0 else -1
    service_charging = bool(service.isCharging())
    broadcast_charging = status in (
        battery_manager.BATTERY_STATUS_CHARGING,
        battery_manager.BATTERY_STATUS_FULL,
    )
    return [
        f"charge: {service_percent}% via BatteryManager.getIntProperty,"
        f" {broadcast_percent}% via level/scale in the sticky"
        f" ACTION_BATTERY_CHANGED — {verdict(service_percent, broadcast_percent)}",
        f"charging: {service_charging} via isCharging(), {broadcast_charging} via"
        f" EXTRA_STATUS — {verdict(service_charging, broadcast_charging)}"
        f"  (EXTRA_PLUGGED = {plugged})",
    ]


def sensor_lines(context):
    """Name, vendor, type id and full-scale range for every sensor the device admits to."""
    context_class = autoclass("android.content.Context")
    sensor_class = autoclass("android.hardware.Sensor")
    manager = context.getSystemService(context_class.SENSOR_SERVICE)
    sensors = manager.getSensorList(sensor_class.TYPE_ALL)
    return [
        f"{len(sensors)} sensors listed by polling. Subscribing to one needs a "
        "SensorEventListener, which means implementing a Java interface from "
        "Python — see the README for why that is not available here."
    ] + [
        f"{sensor.getName()} · {sensor.getVendor()} · type {sensor.getType()}"
        f" · range {sensor.getMaximumRange():.6g}"
        for sensor in sensors
    ]


def timing_lines(count):
    """Time `count` JNI round-trips, and check the value that came back against Python's clock.

    `System.currentTimeMillis()` is about the cheapest call there is — static, no
    arguments, one long returned — so this measures the floor of a round-trip
    rather than the cost of any particular API. That floor is the number worth
    knowing before polling something in a loop, which on Android is the only way
    to watch a value change from Python.
    """
    system = autoclass("java.lang.System")
    java_millis = 0
    start = time.perf_counter()
    for _ in range(count):
        java_millis = system.currentTimeMillis()
    elapsed = time.perf_counter() - start
    return [
        f"{count} × System.currentTimeMillis() took {elapsed * 1e3:.1f} ms"
        f" — {elapsed / count * 1e6:.1f} µs per round-trip",
        f"the value that came back reads {java_millis - time.time() * 1000:+.1f} ms"
        " against time.time(), so the loop is returning real data",
    ]


def read_all(calls):
    """Every block on this screen, as `(lines, error)` pairs ready to print.

    Meant to run off the UI thread. Each block carries its own error rather than
    one error for the screen, because the readers are independent code paths and
    one of them failing says nothing about the rest.
    """
    context, context_error = attempt(application_context)

    def needs_context(reader):
        """Run a reader that requires a Context, or report why there is none."""
        if context is None:
            return None, context_error
        return attempt(reader, context)

    return {
        "identity": identity_lines(),
        "machine": attempt(machine_lines),
        "battery": needs_context(battery_lines),
        "timing": attempt(timing_lines, calls),
        "sensors": needs_context(sensor_lines),
    }
