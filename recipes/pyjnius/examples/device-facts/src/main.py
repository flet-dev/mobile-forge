"""Read Android platform facts through JNI, each beside a second, independent reading."""

import ctypes
import os
import platform
import sys
import time

import flet as ft

# The import is what has to be gated, not the first autoclass(): pyjnius
# resolves java.lang.Class while jnius/reflect.py executes, so the process's
# first JNI call happens inside `import jnius` — before any line of this file
# gets to run a check.
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


def application_context():
    """The app's Context, via the Activity serious_python parks for exactly this.

    `MAIN_ACTIVITY_HOST_CLASS_NAME` names a holder class inside the Flet plugin
    whose static `mActivity` field is your Activity. It is not kivy's
    `org.kivy.android.PythonActivity`, which is what most pyjnius snippets on the
    web reach for and which does not exist in a Flet app.
    """
    host = os.getenv("MAIN_ACTIVITY_HOST_CLASS_NAME") or ACTIVITY_HOST_FALLBACK
    return autoclass(host).mActivity.getApplicationContext()


def read_runtime():
    """ART's view of the machine, next to the stdlib's view of the same machine."""
    runtime = autoclass("java.lang.Runtime").getRuntime()
    system = autoclass("java.lang.System")
    return {
        "cpus_java": runtime.availableProcessors(),
        "cpus_python": os.cpu_count(),
        "kernel_java": system.getProperty("os.version"),
        "kernel_python": os.uname().release,
        "heap_max": runtime.maxMemory(),
        "heap_total": runtime.totalMemory(),
        "heap_free": runtime.freeMemory(),
    }


def read_battery(context):
    """Charge and charging state twice: from BatteryManager, then from the sticky broadcast.

    The two really are separate sources. `getIntProperty` asks the battery
    service for a value now; `ACTION_BATTERY_CHANGED` is the last broadcast the
    system posted, fetched without registering anything by passing a null
    receiver — which is also the shape any "read Android state on demand"
    answer takes here, since a real BroadcastReceiver would need a Java class
    this app cannot supply.
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
    charging_states = (
        battery_manager.BATTERY_STATUS_CHARGING,
        battery_manager.BATTERY_STATUS_FULL,
    )
    return {
        "service_percent": service.getIntProperty(
            battery_manager.BATTERY_PROPERTY_CAPACITY
        ),
        "service_charging": bool(service.isCharging()),
        "broadcast_percent": round(100 * level / scale) if scale > 0 else -1,
        "broadcast_charging": status in charging_states,
        "plugged": plugged,
    }


def read_sensors(context):
    """Name, vendor, type id and full-scale range for every sensor the device admits to."""
    context_class = autoclass("android.content.Context")
    sensor_class = autoclass("android.hardware.Sensor")
    manager = context.getSystemService(context_class.SENSOR_SERVICE)
    return [
        (
            sensor.getName(),
            sensor.getVendor(),
            sensor.getType(),
            sensor.getMaximumRange(),
        )
        for sensor in manager.getSensorList(sensor_class.TYPE_ALL)
    ]


def time_calls(count):
    """Time `count` JNI round-trips, and check the value that comes back against Python's clock.

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
    return {
        "count": count,
        "elapsed": elapsed,
        "per_call_us": elapsed / count * 1e6,
        "skew_ms": java_millis - time.time() * 1000,
    }


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


def attempt(reader, *args):
    """Run one reader, returning either its value or the message to print in its place.

    Every block gets this because the two failures pyjnius produces do not look
    alike: a Java-side throw arrives as `JavaException`, but a member that does
    not exist is a plain `AttributeError`, and an unhandled exception in a Flet
    handler ends the session with a crash screen. Only the first line is kept —
    a `JavaException` carries the whole Java stack trace in its message.
    """
    try:
        return reader(*args), None
    except Exception as error:
        first = str(error).splitlines()[0] if str(error) else ""
        return None, f"{type(error).__name__}: {first}"


def identity_row(field, prop, java_values, native_values):
    """One identity line: the ART reading, the libc reading, and whether they agree."""
    java = java_values.get(field) if java_values else None
    native = native_values.get(prop) if native_values else None
    if java is None or native is None:
        verdict = "unchecked"
    else:
        verdict = "same" if java == native else "DIFFERS"
    java_text = repr(java) if java is not None else "unavailable"
    native_text = repr(native) if native is not None else "unavailable"
    return f"{field} = {java_text} · {prop} = {native_text} · {verdict}"


def blocked_reason():
    """Why this screen cannot run, or None if it can.

    The `FLET_JNI_READY` check is not politeness. serious_python calls
    `System.loadLibrary("pyjni")` before starting the interpreter and sets this
    variable only if that succeeded; without it libpyjni's `JNI_OnLoad` never
    ran, and the first JNI call reads a JavaVM pointer that was never assigned.
    That is a crash with no Python exception to catch, which is why the variable
    is read at the top of this file, ahead of `import jnius` — that import is
    itself the first JNI call.
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


def main(page: ft.Page):
    """Android facts read through JNI, each printed next to a second reading of the same thing.

    The slider picks how many JNI round-trips to time; releasing it re-reads
    every block, because battery and heap move between runs. Nothing here needs
    a permission and every value is checkable against the phone: Settings >
    About phone for the identity block, the status bar for the battery one.
    """
    pending = LEVELS[-1]

    def render(result):
        """Fill every row from one result dict.

        The two identity readings are kept apart on purpose: folding them into
        one reader would let a failure on either side erase the other's values,
        and half an answer is still worth printing.
        """
        java_values, java_error = result["identity_java"]
        native_values, native_error = result["identity_native"]
        identity_rows.controls = [
            ft.Text(message, size=12, color=ft.Colors.ERROR)
            for message in (java_error, native_error)
            if message
        ] + [
            ft.Text(
                identity_row(field, prop, java_values, native_values),
                size=12,
                selectable=True,
            )
            for field, prop in IDENTITY
        ]

        runtime, error = result["runtime"]
        if error:
            machine.value = error
        else:
            # Subtract the rounded figures so the three numbers on the line add up
            # as printed.
            total = round(runtime["heap_total"] / MIB, 1)
            free = round(runtime["heap_free"] / MIB, 1)
            machine.value = (
                f"processors: {runtime['cpus_java']} via Runtime, "
                f"{runtime['cpus_python']} via os.cpu_count() — "
                f"{'same' if runtime['cpus_java'] == runtime['cpus_python'] else 'DIFFER'}\n"
                f"kernel: {runtime['kernel_java']!r} via System.getProperty, "
                f"{runtime['kernel_python']!r} via os.uname() — "
                f"{'same' if runtime['kernel_java'] == runtime['kernel_python'] else 'DIFFER'}\n"
                f"ART heap: {total} MiB claimed = {round(total - free, 1)} MiB used + "
                f"{free} MiB free, ceiling {runtime['heap_max'] / MIB:.1f} MiB"
            )

        power, error = result["battery"]
        if error:
            battery.value = error
        else:
            battery.value = (
                f"charge: {power['service_percent']}% via "
                f"BatteryManager.getIntProperty, {power['broadcast_percent']}% via "
                f"level/scale in the sticky ACTION_BATTERY_CHANGED — "
                f"{'same' if power['service_percent'] == power['broadcast_percent'] else 'DIFFER'}\n"
                f"charging: {power['service_charging']} via isCharging(), "
                f"{power['broadcast_charging']} via EXTRA_STATUS — "
                f"{'same' if power['service_charging'] == power['broadcast_charging'] else 'DIFFER'}"
                f"  (EXTRA_PLUGGED = {power['plugged']})"
            )

        cost, error = result["timing"]
        if error:
            calls.value = error
        else:
            calls.value = (
                f"{cost['count']} × System.currentTimeMillis() took "
                f"{cost['elapsed'] * 1e3:.1f} ms — {cost['per_call_us']:.1f} µs per "
                f"round-trip; the value that came back reads "
                f"{cost['skew_ms']:+.1f} ms against time.time()"
            )
            caption.value = f"{cost['count']} JNI round-trips"

        sensors, error = result["sensors"]
        if error:
            # Without this the previous run's count stays on screen, asserting a
            # tally over the top of the error that says nothing was read.
            sensor_note.value = ""
            sensor_rows.controls = [ft.Text(error, size=12, color=ft.Colors.ERROR)]
        else:
            sensor_rows.controls = [
                ft.Text(
                    f"{name} · {vendor} · type {type_id} · range {maximum:.6g}",
                    size=12,
                    selectable=True,
                )
                for name, vendor, type_id, maximum in sensors
            ]
            sensor_note.value = (
                f"{len(sensors)} sensors listed by polling. Subscribing to one needs a "
                "SensorEventListener, which means implementing a Java interface from "
                "Python — see the README for why that is not available here."
            )

    def run():
        """Read every block off the device and fill the screen. Runs off the UI thread.

        `page.run_thread` never looks at what the worker raised, so a failure
        here would leave the screen frozen on the previous run's numbers with
        nothing to show for it. Each reader carries its own error, and the outer
        `except` covers the formatting that turns them into rows; the explicit
        `page.update()` is what makes any of it appear.
        """
        try:
            context, context_error = attempt(application_context)
            render(
                {
                    "identity_java": attempt(read_identity),
                    "identity_native": attempt(read_properties),
                    "runtime": attempt(read_runtime),
                    "timing": attempt(time_calls, pending),
                    "battery": (
                        (None, context_error)
                        if context is None
                        else attempt(read_battery, context)
                    ),
                    "sensors": (
                        (None, context_error)
                        if context is None
                        else attempt(read_sensors, context)
                    ),
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
        caption.value = f"{LEVELS[int(workload.value)]} JNI round-trips"

    page.appbar = ft.AppBar(title=ft.Text("Android device facts"), center_title=True)
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
                        f"pyjnius {jnius.__version__} · Python "
                        f"{platform.python_version()} · {page.platform.value} · "
                        f"FLET_JNI_READY={os.getenv('FLET_JNI_READY')} · "
                        f"{extension_origin()} · activity host "
                        f"{os.getenv('MAIN_ACTIVITY_HOST_CLASS_NAME')} → "
                        f"{os.getenv('MAIN_ACTIVITY_CLASS_NAME')}",
                        size=11,
                        selectable=True,
                    ),
                    ft.Text(
                        "identity: ART vs libc", size=12, weight=ft.FontWeight.BOLD
                    ),
                    identity_rows := ft.Column(spacing=2),
                    ft.Text("machine", size=12, weight=ft.FontWeight.BOLD),
                    machine := ft.Text(size=12, selectable=True),
                    ft.Text("battery", size=12, weight=ft.FontWeight.BOLD),
                    battery := ft.Text(size=12, selectable=True),
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
                    ft.Text("sensors", size=12, weight=ft.FontWeight.BOLD),
                    sensor_note := ft.Text(size=12),
                    sensor_rows := ft.Column(spacing=2),
                ],
            ),
        )
    )

    preview()
    start()


if __name__ == "__main__":
    ft.run(main)
