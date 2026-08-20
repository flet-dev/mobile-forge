"""Freeze this device's clock and see which readings follow and which do not."""

import asyncio
import calendar
import datetime as dt
import logging
import os
import platform
import sqlite3
import tempfile
import time
import uuid

import flet as ft

try:
    import time_machine
except Exception as error:  # the wheel may be missing or fail to load
    time_machine = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

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

ROW_WEIGHTS = (7, 8, 4)

INSTANT_S = 5.0

DAY_S = 86400.0

REFRESH_S = 0.25

UUID_EPOCH_100NS = 0x01B21DD213814000  # 100ns ticks from 1582-10-15 to the unix epoch

STARTED_MONOTONIC = time.monotonic()

UUID_NOTE = (
    "uuid.uuid1() reads 'elsewhere' after a trip to a date earlier than the last "
    "one: CPython keeps the highest timestamp it has emitted and refuses to go back."
)


def scratch_dir():
    """Flet's temp storage on device, the OS temp directory anywhere else.

    Android has no `/tmp`, so `tempfile`'s own fallback is the working
    directory; the env var is the only portable answer on a phone.
    """
    return os.getenv("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()


def travelling():
    """True while a trip is in progress, and False when the package is absent."""
    return time_machine is not None and time_machine.escape_hatch.is_travelling()


def real_time():
    """The device's own clock, whatever the app's clock currently says.

    `escape_hatch` reaches the saved C function pointers, so it only works
    while patched - off a trip it raises `ValueError: Not currently
    time-travelling`, and plain `time.time()` is already the real thing.
    """
    if travelling():
        return time_machine.escape_hatch.time.time()
    return time.time()


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

    Reading the local date as if it were UTC puts this row up to 36 hours from
    the reference west of Greenwich - far enough that a US phone classified the
    2038 destination `elsewhere`. `mktime` converts, it does not read a clock,
    so it is not patched.
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

    Deliberately identical output to the row above it: the two differ only in
    which C function CPython calls, and they disagree during a trip.
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

    Both references are sampled once per sweep, so a ticking trip does not
    slowly push every row out of tolerance the way a fixed destination would.
    `date.today()` is compared with a day of slack instead of five seconds
    because it lands on midnight and the references do not.
    """
    if abs(epoch - app_ref) <= tolerance:
        return "followed"
    if abs(epoch - real_ref) <= tolerance:
        return "real clock"
    return "elsewhere"


def sweep():
    """Read every probe once and classify each against the two clocks.

    Returns the display rows and a `(followed, total, stragglers)` tuple. Each
    probe is called inside try/except because a destination outside a
    platform's `time_t` range fails per-reading rather than per-app.
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


def table_row(values, size=11, weight=None):
    """One table row: a `Text` per value, laid out by the shared column weights."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, weight=weight, expand=column)
            for value, column in zip(values, ROW_WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """Drive a trip from the UI and show what the device's clocks say during it.

    Nothing here is bundled: every number on screen is read from this process
    while it runs. When `time_machine` is missing the app still works - the
    probe table reads the real clock and the header says what the import
    raised - because a crash screen would teach nothing.
    """
    trip = None
    traveller = None

    def stop_trip():
        """End the running trip, if any, and forget it."""
        nonlocal trip, traveller
        if trip is not None:
            trip.stop()
            trip, traveller = None, None

    def start_trip():
        """Travel to the selected destination, replacing a trip already running.

        `travel()` keeps one process-wide stack rather than per-thread state, so
        starting a second trip on top of the first would make the exit order
        matter; stopping first keeps the stack one deep.
        """
        nonlocal trip, traveller
        stop_trip()
        trip = time_machine.travel(DESTINATIONS[picker.selected[0]], tick=ticking.value)
        traveller = trip.start()

    def refresh():
        """Re-run the probe sweep and repaint the table, the verdict and the buttons."""
        rows, totals = sweep()
        table.controls = [
            table_row(("reading", "value (UTC)", "verdict"), weight=ft.FontWeight.BOLD),
            ft.Divider(height=1),
            *(table_row(row) for row in rows),
        ]
        live = travelling()
        verdict.value = summarise(totals, live)
        verdict.color = ft.Colors.TERTIARY if live else None
        travel_button.content = "Return" if live else "Travel"
        travel_button.icon = ft.Icons.HISTORY if live else ft.Icons.PLAY_ARROW
        travel_button.disabled = time_machine is None
        shift_button.disabled = traveller is None
        why.value = WHY[picker.selected[0]]

    def guard(work):
        """Run a handler body, turning any failure into a status line.

        An exception escaping a Flet event handler ends the session with a crash
        screen, which would hide exactly the platform differences this app is for.
        The repaint is guarded separately so it still runs after a failed tap,
        and so a reading this platform cannot render is a status line too.
        """
        try:
            work()
            status.value = ""
        except Exception as error:
            status.value = f"{type(error).__name__}: {error}"
        try:
            refresh()
        except Exception as error:
            status.value = f"{type(error).__name__}: {error}"
        page.update()

    def on_travel():
        """Toggle the trip: start one, or end the one already running."""

        def work():
            if time_machine is None:
                raise RuntimeError("time-machine is not installed")
            if travelling():
                stop_trip()
            else:
                start_trip()

        guard(work)

    def on_settings():
        """Apply a new destination or tick setting, restarting a live trip."""

        def work():
            if travelling():
                start_trip()

        guard(work)

    def on_shift():
        """Push the trip an hour further on without leaving it."""

        def work():
            if traveller is None:
                raise RuntimeError("not travelling")
            traveller.shift(dt.timedelta(hours=1))

        guard(work)

    def on_thread():
        """Read the clock from a pool thread to show the patch is process-wide.

        `page.run_thread` submits to a shared executor and never retrieves the
        worker's future, so the body carries its own try/except and ends with an
        explicit `page.update()` - auto-update does not reach background threads.
        """

        def worker():
            try:
                seen = dt.datetime.now(dt.timezone.utc)
                thread_line.value = (
                    f"worker thread read {seen.strftime('%Y-%m-%d %H:%M')} UTC "
                    f"- the device clock says {stamp(real_time())}"
                )
            except Exception as error:
                thread_line.value = f"{type(error).__name__}: {error}"
            page.update()

        page.run_thread(worker)

    async def tick_faces():
        """Repaint the two clock faces four times a second for the session's life.

        Only the faces are on this loop - the probe sweep opens a database and
        writes a file, which is far too much to do at this rate.
        """
        while True:
            try:
                app_face.value = dt.datetime.now().strftime("%H:%M:%S")
                real_face.value = dt.datetime.fromtimestamp(real_time()).strftime(
                    "%H:%M:%S"
                )
            except Exception as error:  # a destination this platform cannot hold
                app_face.value = type(error).__name__
            uptime.value = (
                "time.monotonic() since launch: "
                f"{time.monotonic() - STARTED_MONOTONIC:,.1f} s - never patched"
            )
            try:
                page.update()
            except Exception:  # the session is gone; nothing left to paint
                return
            await asyncio.sleep(REFRESH_S)

    library = (
        f"time-machine absent - {IMPORT_ERROR}"
        if time_machine is None
        else "time-machine loaded - patches CPython's clock functions in place"
    )
    page.appbar = ft.AppBar(title=ft.Text("frozen clock"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        library,
                        size=11,
                        color=ft.Colors.ERROR if time_machine is None else None,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} - {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            ft.Column(
                                expand=True,
                                spacing=0,
                                controls=[
                                    ft.Text("app clock", size=11),
                                    app_face := ft.Text(
                                        size=28, weight=ft.FontWeight.BOLD
                                    ),
                                ],
                            ),
                            ft.Column(
                                expand=True,
                                spacing=0,
                                controls=[
                                    ft.Text("device clock", size=11),
                                    real_face := ft.Text(size=28),
                                ],
                            ),
                        ]
                    ),
                    uptime := ft.Text(size=11),
                    ft.Divider(),
                    picker := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name))
                            for name in DESTINATIONS
                        ],
                        selected=["1969"],  # a set dies in msgpack
                        on_change=on_settings,
                    ),
                    why := ft.Text(size=11),
                    ft.Row(
                        wrap=True,
                        controls=[
                            travel_button := ft.Button("Travel", on_click=on_travel),
                            shift_button := ft.Button(
                                "+1 hour", icon=ft.Icons.FAST_FORWARD, on_click=on_shift
                            ),
                            ft.Button(
                                "Re-read", icon=ft.Icons.REFRESH, on_click=on_settings
                            ),
                            ft.Button(
                                "From a thread",
                                icon=ft.Icons.CALL_SPLIT,
                                on_click=on_thread,
                            ),
                            ticking := ft.Switch(
                                label="tick", value=True, on_change=on_settings
                            ),
                        ],
                    ),
                    status := ft.Text(size=11, color=ft.Colors.ERROR),
                    ft.Divider(),
                    table := ft.Column(spacing=4),
                    verdict := ft.Text(size=11),
                    thread_line := ft.Text(size=11),
                    ft.Text(UUID_NOTE, size=10, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
            ),
        )
    )

    guard(lambda: None)  # first paint, behind the same guard as a tap
    page.run_task(tick_faces)


if __name__ == "__main__":
    ft.run(main)
