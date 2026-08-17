"""Ask this device what it knows about time zones, and where a day is not 24 hours."""

import datetime
import importlib.metadata
import os
import platform
import time
import zoneinfo

import flet as ft
import pendulum

INSTANT = "2026-03-29T00:30:00Z"

ZONES = (
    "UTC",
    "Europe/Paris",
    "America/New_York",
    "Asia/Kolkata",
    "Pacific/Chatham",
    "Australia/Sydney",
)

BASE_ZONE = "Europe/Paris"
BASE = pendulum.datetime(2026, 3, 25, 12, 0, tz=BASE_ZONE)
MAX_DAYS = 240

# Every place pendulum's Unix branch looks for a system zone, in the order it
# tries them. Which of these exist is the whole answer to "why UTC?" below.
PROBES = (
    "/etc/timezone",
    "/etc/sysconfig/clock",
    "/etc/conf.d/clock",
    "/etc/localtime",
    "/usr/local/etc/localtime",
)

# Six ISO-8601 shapes, three of which datetime.fromisoformat also reads and three
# of which it rejects outright, then two inputs that raise — the second one
# through a bare ValueError rather than ParserError.
INPUTS = (
    "2026-03-29T01:30:00Z",
    "20260329T013000Z",
    "2026-W14-1",
    "2026-089",
    "P3DT4H5M",
    "2007-03-01T13:00:00Z/2008-05-11T15:30:00Z",
    "the day after tomorrow",
    "",
)

ZONE_WEIGHTS = (5, 6, 2)

PARSE_WEIGHTS = (7, 3, 7)


def version():
    """pendulum's version, or a placeholder if its metadata is unreachable.

    `pendulum.__version__` still answers but is deprecated and goes away in 3.4,
    and its replacement reads the `dist-info` directory — which is a packaging
    artefact rather than something the package carries, so on a phone it is worth
    treating as a question the device answers instead of a given.
    """
    try:
        return importlib.metadata.version("pendulum")
    except Exception:
        return "unreported"


def implementations():
    """Which module the parser and the calendar helpers actually came from.

    Both are imported from the Rust extension under a `try/except ImportError`
    with a pure-Python twin behind it, so a broken extension degrades silently
    and every answer on this screen stays correct. Reading `__module__` is the
    only way to tell which one ran. They can disagree: `helpers` additionally
    refuses the extension when `struct.calcsize("P") == 4`, which is every 32-bit
    Android ABI.
    """
    return (
        pendulum.parsing.parse_iso8601.__module__,
        pendulum.helpers.precise_diff.__module__,
    )


def present(paths):
    """The paths in `paths` that exist, or a dash when none of them do."""
    found = [path for path in paths if os.path.exists(path)]
    return ", ".join(found) if found else "—"


def local_lines():
    """Three answers to "what zone is this device in", from three sources.

    pendulum reads configuration files; `datetime.astimezone()` goes through
    libc, which on both mobile platforms has its own database that has nothing to
    do with `zoneinfo`; `time.tzname` is the C library's own naming. On a desktop
    all three agree, so the disagreement is the interesting output.
    """
    here = pendulum.now()
    clock = datetime.datetime.now().astimezone()
    return (
        f"pendulum.now(): {here.timezone_name} ({here.strftime('%z')})",
        f"device clock via libc: {clock.tzname()} ({clock.strftime('%z')})",
        f"time.tzname: {' / '.join(time.tzname)}",
        (
            f"TZ={os.environ.get('TZ') or 'unset'} · "
            f"config files present: {present(PROBES)}"
        ),
        f"TZPATH directories present: {present(zoneinfo.TZPATH)}",
    )


def zone_rows():
    """One fixed instant in six zones, each answer checked a second way.

    pendulum parses the literal and converts with `in_timezone`; the check
    re-does it with nothing but the standard library, so a wrong conversion shows
    up as a mismatch rather than as a plausible-looking time. The instant is 30
    minutes before Paris springs forward, so Paris is still on +01:00 while New
    York has been on -04:00 for three weeks.
    """
    moment = pendulum.parse(INSTANT)
    plain = datetime.datetime.fromisoformat(INSTANT.replace("Z", "+00:00"))
    rows = []
    for name in ZONES:
        theirs = moment.in_timezone(name).strftime("%Y-%m-%d %H:%M %z")
        check = plain.astimezone(zoneinfo.ZoneInfo(name)).strftime("%Y-%m-%d %H:%M %z")
        rows.append((name, theirs, "ok" if theirs == check else "DIFFERS"))
    return rows


def parse_rows():
    """Every input in INPUTS through `pendulum.parse`, with the type it returned.

    The type is half the point: the same call hands back a `DateTime`, a
    `Duration` or an `Interval` depending on the string. The catch is the other
    half — `parse("")` raises a plain `ValueError`, so a handler that only caught
    `ParserError` would crash the session on an empty text field.
    """
    rows = []
    for text in INPUTS:
        try:
            parsed = pendulum.parse(text)
            rows.append((repr(text), type(parsed).__name__, str(parsed)))
        except Exception as error:
            rows.append((repr(text), type(error).__name__, str(error)))
    return rows


def crossing(days):
    """Add `days` to a fixed Paris noon two ways, and count the hours that passed.

    `.add(days=…)` moves the calendar and lets the wall clock stay put;
    `+ timedelta(days=…)` moves absolute time and lets the wall clock drift. The
    `+` is pendulum's own — it overrides `__add__` to add `total_seconds()` — and
    it is the reverse of what that expression means on a stdlib aware datetime,
    where `+` keeps the wall clock and so agrees with `.add(days=…)` instead.
    That inversion is the trap: the line survives a port between the two and
    quietly changes answer.
    """
    calendar = BASE.add(days=days)
    absolute = BASE + datetime.timedelta(days=days)
    elapsed = (calendar - BASE).total_seconds() / 3600
    return {
        "calendar": calendar.strftime("%Y-%m-%d %H:%M %z"),
        "absolute": absolute.strftime("%Y-%m-%d %H:%M %z"),
        "elapsed": elapsed,
        "nominal": days * 24,
        "apart": (absolute - calendar).total_seconds() / 3600,
    }


def table_row(values, weights, size=11):
    """One table row: a `Text` per value, sized by weight so columns line up."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Report what this device knows about zones, then prove one day is not 24 hours.

    Nothing here is asserted in prose: the header says which parser ran, the
    first block prints three independent answers for the local zone, the zone
    table checks every conversion against the standard library, and the slider
    turns "adding a day is not adding 24 hours" into two numbers that differ.
    """

    def show_days():
        """Caption the slider's position while the thumb is still moving."""
        caption.value = f"{int(span.value)} days from {BASE.strftime('%Y-%m-%d %H:%M')}"

    def run_crossing():
        """Recompute the crossing for the day count the slider was released on.

        Bound to `on_change_end` rather than `on_change` so one gesture means one
        recomputation. It stays on the UI thread deliberately: the work is a
        handful of date operations, it writes nothing, and a background thread
        would only add the two failure modes `page.run_thread` carries.
        """
        days = int(span.value)
        result = crossing(days)
        show_days()
        elapsed, nominal = result["elapsed"], result["nominal"]
        short = nominal - elapsed
        if short:
            verdict = f"{abs(short):g} h {'short of' if short > 0 else 'over'} nominal"
        else:
            verdict = "the two agree"
        added.value = f".add(days={days}) → {result['calendar']}"
        shifted.value = f"+ timedelta(days={days}) → {result['absolute']}"
        apart = result["apart"]
        elapsed_row.value = (
            f"{elapsed:g} h really elapsed against a nominal {days} × 24 = "
            f"{nominal:g} h — {verdict}; the two results are {apart:g} h apart"
        )

    parser_module, helpers_module = implementations()
    page.appbar = ft.AppBar(title=ft.Text("pendulum DST clock"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"pendulum {version()} · Python {platform.python_version()} · "
                        f"{page.platform.value} · parser {parser_module} · "
                        f"helpers {helpers_module}",
                        size=11,
                        selectable=True,
                    ),
                    ft.Text(
                        f"{len(pendulum.tz.timezones())} named zones resolvable here",
                        size=11,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Divider(),
                    ft.Text("what this device thinks its own zone is", size=11),
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(line, size=11, selectable=True)
                            for line in local_lines()
                        ],
                    ),
                    ft.Divider(),
                    ft.Text(f"{INSTANT} seen from six zones", size=11),
                    ft.Column(
                        spacing=4,
                        controls=[
                            table_row(
                                ("zone", "local time", "vs stdlib"), ZONE_WEIGHTS
                            ),
                            ft.Divider(height=1),
                            *(table_row(row, ZONE_WEIGHTS) for row in zone_rows()),
                        ],
                    ),
                    ft.Divider(),
                    caption := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    span := ft.Slider(
                        value=4,
                        min=1,
                        max=MAX_DAYS,
                        divisions=MAX_DAYS - 1,
                        on_change=show_days,
                        on_change_end=run_crossing,
                    ),
                    added := ft.Text(size=12),
                    shifted := ft.Text(size=12),
                    elapsed_row := ft.Text(size=12),
                    ft.Divider(),
                    ft.Text("pendulum.parse, and what it hands back", size=11),
                    ft.Column(
                        spacing=4,
                        controls=[
                            table_row(("input", "type", "result"), PARSE_WEIGHTS, 10),
                            ft.Divider(height=1),
                            *(
                                table_row(row, PARSE_WEIGHTS, 10)
                                for row in parse_rows()
                            ),
                        ],
                    ),
                ],
            ),
        )
    )

    run_crossing()


if __name__ == "__main__":
    ft.run(main)
