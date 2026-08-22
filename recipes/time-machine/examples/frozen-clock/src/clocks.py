"""The trip, and the thirteen ways of reading the time it does or does not move.

`main.py` owns the screen. Everything that actually touches time-machine or a clock
lives here and returns plain values, so the UI never has to know which reading came
from CPython, from SQLite or from the kernel.
"""

import calendar
import datetime as dt
import logging
import os
import sqlite3
import tempfile
import time
import uuid

try:
    import time_machine
except Exception as error:  # the wheel may be missing or fail to load
    time_machine = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

AVAILABLE = time_machine is not None

DESTINATIONS = {
    "1969": "1969-07-20 20:17:40+00:00",
    "2000": "2000-01-01 00:00:00+00:00",
    "2038": "2038-01-19 03:14:07+00:00",
}

WHY = {
    "1969": "Apollo 11 touchdown - a negative unix timestamp",
    "2000": "the Y2K rollover",
    "2038": "2**31 - 1 seconds, where a 32-bit time_t runs out",
}

UUID_NOTE = (
    "uuid.uuid1() reads 'elsewhere' after a trip to a date earlier than the last "
    "one: CPython keeps the highest timestamp it has emitted and refuses to go back."
)

INSTANT_S = 5.0

DAY_S = 86400.0

UUID_EPOCH_100NS = 0x01B21DD213814000  # 100ns ticks from 1582-10-15 to the unix epoch

STARTED_MONOTONIC = time.monotonic()

_trip = None
_traveller = None


def library_line():
    """One line saying whether the wheel loaded, for the top of the screen."""
    if not AVAILABLE:
        return f"time-machine absent - {IMPORT_ERROR}"
    return "time-machine loaded - patches CPython's clock functions in place"


def travelling():
    """True while a trip is in progress, and False when the package is absent."""
    return AVAILABLE and time_machine.escape_hatch.is_travelling()


def start_trip(key, tick):
    """Travel to the named destination, replacing a trip already running.

    `travel()` keeps one process-wide stack rather than per-thread state, so
    starting a second trip on top of the first would make the exit order matter;
    stopping first keeps the stack one deep.
    """
    global _trip, _traveller
    if not AVAILABLE:
        raise RuntimeError("time-machine is not installed")
    stop_trip()
    _trip = time_machine.travel(DESTINATIONS[key], tick=tick)
    _traveller = _trip.start()


def stop_trip():
    """End the running trip, if any, and forget it."""
    global _trip, _traveller
    if _trip is not None:
        _trip.stop()
        _trip, _traveller = None, None


def shift_hour():
    """Push the trip an hour further on without leaving it."""
    if _traveller is None:
        raise RuntimeError("not travelling")
    _traveller.shift(dt.timedelta(hours=1))


def real_time():
    """The device's own clock, whatever the app's clock currently says.

    `escape_hatch` reaches the saved C function pointers, so it only works while
    patched - off a trip it raises `ValueError: Not currently time-travelling`,
    and plain `time.time()` is already the real thing.
    """
    if travelling():
        return time_machine.escape_hatch.time.time()
    return time.time()


def scratch_dir():
    """Flet's temp storage on device, the OS temp directory anywhere else.

    Android has no `/tmp`, so `tempfile`'s own fallback is the working directory;
    the env var is the only portable answer on a phone.
    """
    return os.getenv("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()


def sqlite_now():
    """`CURRENT_TIMESTAMP`, read inside SQLite's C library rather than Python's."""
    connection = sqlite3.connect(":memory:")
    try:
        stamp = connection.execute("select current_timestamp").fetchone()[0]
    finally:
        connection.close()
    return (
        dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=dt.timezone.utc)
        .timestamp()
    )


def file_mtime():
    """The mtime the kernel stamps on a file created right now."""
    path = os.path.join(scratch_dir(), "time-machine-probe")
    with open(path, "wb") as handle:
        handle.write(b"probe")
    try:
        return os.stat(path).st_mtime
    finally:
        os.remove(path)


def today_epoch():
    """`date.today()` as the epoch of the local midnight that starts it.

    Reading the local date as if it were UTC puts this row up to 36 hours from the
    reference west of Greenwich - far enough that a US phone classified the 2038
    destination `elsewhere`. `mktime` converts, it does not read a clock, so it is
    not patched.
    """
    return time.mktime(dt.date.today().timetuple())


def ctime_epoch():
    """`time.ctime()` parsed back to an epoch.

    Parsing is unpatched - `strptime` and `mktime` convert, they do not read a
    clock - so the number this returns is whatever `ctime()` itself believed.
    """
    return time.mktime(time.strptime(time.ctime()))


def strftime_epoch():
    """`time.strftime()` in ctime's own format, parsed back the same way.

    Deliberately identical output to the row above it: the two differ only in which
    C function CPython calls, and they disagree during a trip.
    """
    return time.mktime(time.strptime(time.strftime("%a %b %d %H:%M:%S %Y")))


# (label, probe, how close the reading has to be to count as the same clock)
PROBES = (
    ("time.time()", time.time, INSTANT_S),
    ("time.time_ns()", lambda: time.time_ns() / 1e9, INSTANT_S),
    (
        "time.clock_gettime(REALTIME)",
        lambda: time.clock_gettime(time.CLOCK_REALTIME),
        INSTANT_S,
    ),
    (
        "datetime.now(utc)",
        lambda: dt.datetime.now(dt.timezone.utc).timestamp(),
        INSTANT_S,
    ),
    ("date.today()", today_epoch, DAY_S),
    ("time.gmtime()", lambda: float(calendar.timegm(time.gmtime())), INSTANT_S),
    ("time.localtime()", lambda: time.mktime(time.localtime()), INSTANT_S),
    ("time.strftime()", strftime_epoch, INSTANT_S),
    ("time.ctime()", ctime_epoch, INSTANT_S),
    ("uuid.uuid1()", lambda: (uuid.uuid1().time - UUID_EPOCH_100NS) / 1e7, INSTANT_S),
    (
        "logging record",
        lambda: logging.LogRecord("p", 20, "p", 0, "", None, None).created,
        INSTANT_S,
    ),
    ("sqlite CURRENT_TIMESTAMP", sqlite_now, INSTANT_S),
    ("file st_mtime", file_mtime, INSTANT_S),
)


def stamp(epoch):
    """An epoch rendered in UTC, short enough for a phone-width column."""
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def classify(epoch, app_ref, real_ref, tolerance):
    """Say whether a reading agrees with the app's clock or the device's.

    Both references are sampled once per sweep, so a ticking trip does not slowly
    push every row out of tolerance the way a fixed destination would.
    `date.today()` is compared with a day of slack instead of five seconds because
    it lands on midnight and the references do not.
    """
    if abs(epoch - app_ref) <= tolerance:
        return "followed"
    if abs(epoch - real_ref) <= tolerance:
        return "real clock"
    return "elsewhere"


def sweep():
    """Read every probe once and classify each against the two clocks.

    Returns the display rows and a `(followed, total, stragglers)` tuple. Each
    probe is called inside try/except because a destination outside a platform's
    `time_t` range fails per-reading rather than per-app.
    """
    app_ref = time.time()
    real_ref = real_time()
    rows, followed, stragglers = [], 0, []
    for label, probe, tolerance in PROBES:
        try:
            epoch = probe()
        except Exception as error:
            rows.append((label, f"{type(error).__name__}", "failed"))
            continue
        verdict = classify(epoch, app_ref, real_ref, tolerance)
        if verdict == "followed":
            followed += 1
        else:
            stragglers.append(label)
        rows.append((label, stamp(epoch), verdict))
    return rows, (followed, len(PROBES), stragglers)


def summarise(totals, is_travelling):
    """One line naming how many readings moved and which ones stayed behind."""
    followed, total, stragglers = totals
    if not is_travelling:
        return f"Not travelling - all {total} readings are the device's real clock."
    if not stragglers:
        return f"All {total} readings followed the trip."
    return (
        f"{followed}/{total} readings followed the trip. "
        f"Did not move: {', '.join(stragglers)}."
    )


def faces():
    """The two clock-face strings and the monotonic uptime line, for the tick loop.

    `datetime.now()` can raise at a destination this platform's `time_t` cannot
    hold, so the app face reports the exception name rather than taking the
    session down with it.
    """
    try:
        app = dt.datetime.now().strftime("%H:%M:%S")
    except Exception as error:
        app = type(error).__name__
    real = dt.datetime.fromtimestamp(real_time()).strftime("%H:%M:%S")
    uptime = (
        "time.monotonic() since launch: "
        f"{time.monotonic() - STARTED_MONOTONIC:,.1f} s - never patched"
    )
    return app, real, uptime


def thread_reading():
    """What a worker thread sees, next to what the device's clock says.

    Called from a background thread on purpose: the patch lives in a struct every
    thread shares, so this reads the destination rather than the real date.
    """
    seen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    return f"worker thread read {seen} UTC - the device clock says {stamp(real_time())}"
