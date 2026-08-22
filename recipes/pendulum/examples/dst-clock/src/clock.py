"""Everything this example asks pendulum, returned as plain values for the UI."""

import datetime
import importlib.metadata
import os
import time
import zoneinfo

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
BASE_LABEL = BASE.strftime("%Y-%m-%d %H:%M")
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
    build.
    """
    return (
        pendulum.parsing.parse_iso8601.__module__,
        pendulum.helpers.precise_diff.__module__,
    )


def zone_count():
    """How many named zones resolve here.

    `pendulum.tz.timezones()` is `zoneinfo.available_timezones()` under a cache:
    the `tzdata` wheel's list plus whatever the OS keeps under `TZPATH`, so the
    two platforms may legitimately answer differently.
    """
    return len(pendulum.tz.timezones())


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
