# pendulum DST clock

One screen that answers "what does this phone actually know about time zones?" and then
makes the answer uncomfortable. Four blocks under a self-describing header: what the device
thinks its own zone is, asked three independent ways; one fixed instant rendered into six
zones with every conversion checked against the standard library; a slider that walks a
Paris noon across a DST transition and prints the hours that really elapsed; and a table of
ISO-8601 strings run through `pendulum.parse` with the type each one came back as. Every
input is a literal, so the only variable is the device.

What it demonstrates:

- **The local-zone disagreement, which is the whole reason this example exists.** The first
  block prints `pendulum.now()`'s zone and offset next to `datetime.datetime.now()
  .astimezone()`, which takes its offset from the C library rather than from `zoneinfo`, and
  next to `time.tzname`. Underneath it lists which of the five files pendulum's Unix branch
  looks for actually exist on this device, and which of `zoneinfo`'s four search directories
  do. On a desktop all three answers agree and the paths are there; on a phone they are
  expected not to be, and the screen says so rather than the docs guessing. When none of them
  is found, `pendulum.now()` warns once on stderr — where a Flet app shows nothing — and
  returns UTC, which is why every other call in this app names the zone it wants. The
  [recipe README](../../README.md#things-to-know) has the rest of that story.
- **How many named zones this device can resolve.** One bold number, `len(pendulum.tz
  .timezones())`, which is `zoneinfo.available_timezones()` under a `functools.cache`. It is
  the `tzdata` wheel's list plus whatever the OS keeps under `TZPATH`, so the two platforms
  may legitimately print different numbers — and the line above it says which `TZPATH`
  directories were found, which is how you tell which case you are in.
- **Six zones, each answer computed twice.** `2026-03-29T00:30:00Z` goes through
  `pendulum.parse` and then `.in_timezone(...)`, and every row is re-derived with nothing but
  `datetime.fromisoformat` and `zoneinfo.ZoneInfo`; the third column says `ok` or `DIFFERS`.
  The instant is 30 minutes before Paris springs forward, so Paris is still on `+01:00`
  while New York has been on `-04:00` for three weeks, and `Pacific/Chatham` puts a
  quarter-hour offset (`+13:45`) on screen so the formatting is exercised too.
- **"Adding a day is not adding 24 hours", as two numbers that differ.** The slider picks 1
  to 240 days from a fixed `2026-03-25 12:00` in Europe/Paris. Each release prints
  `.add(days=N)`, `base + datetime.timedelta(days=N)`, the hours that really elapsed against
  the nominal `N × 24`, and how far apart the two results landed. At N=4 that reads 95 hours
  against a nominal 96 with the two results an hour apart; from N=214 the span has crossed
  both transitions and the two agree again. The `+` is **pendulum's own** — `DateTime`
  overrides `__add__` to add `delta.total_seconds()` — and it means the reverse of what the
  same expression means on a stdlib aware datetime, where `+` keeps the wall clock and so
  agrees with `.add(days=N)`. Subclassing `datetime.datetime` is what makes the line compile
  either side of a port; overriding `__add__` is what makes it change answer.
- **What `pendulum.parse` hands back, type included.** Eight literals: an RFC-3339 `Z`
  string, the basic form `20260329T013000Z`, an ISO week date, an ordinal date, an ISO
  duration and an interval — returning `DateTime`, `Duration` and `Interval` respectively —
  then two that raise. The second of those is the empty string, which raises a plain
  `ValueError` rather than the `ParserError` you would think to catch; every call sits inside
  a broad `except Exception`, because an unhandled exception in a Flet handler crashes the
  session.
- **Which implementation actually ran.** The header carries
  `pendulum.parsing.parse_iso8601.__module__` and `pendulum.helpers.precise_diff.__module__`.
  Both are imported from the Rust extension behind a `try/except ImportError` with a working
  pure-Python twin, so a dead extension changes no answer on this screen — reading those two
  names is the only way to tell. They are allowed to disagree: on 32-bit Android the helpers
  half refuses the extension on purpose, so `armeabi-v7a` should report
  `pendulum._pendulum` for the parser and `pendulum._helpers` for the helpers. That is why
  it is the **parser** name that answers "did the extension load?" — the helpers name says
  `pendulum._helpers` on `armeabi-v7a` whether the extension loaded or not.
- **A version string that cannot crash the header.** `pendulum.__version__` is deprecated
  and goes away in 3.4, so the header uses `importlib.metadata.version("pendulum")` — which
  reads the `dist-info` directory, a packaging artefact rather than part of the package. It
  is wrapped in `try/except Exception` with a short fallback, so the screen renders either
  way and the device run reports which it got.

The slider is the only thing that recomputes, and it is bound to
[`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
gesture means one run, with
[`on_change`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change) doing nothing
but re-captioning the thumb. The work stays on the UI thread deliberately: it is a handful
of date operations, it writes no file and two runs cannot conflict, so
[`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) would add
only its two failure modes — swallowed exceptions and no auto-update — and buy nothing.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

A simulator run cannot settle the two questions this example exists to ask: it resolves
`/etc/localtime` and `/usr/share/zoneinfo` against the host Mac, so both the local zone and
the zone count come back looking like a desktop's. Read those two lines off a real device,
or label them as the simulator's.

`pyproject.toml` pins both `flet` and `pendulum`, which is the combination that was
verified. `requires-python` stays at `>=3.10`, which every pin here satisfies — checked the
way a consumer meets it, by copying that `pyproject.toml` alone into an empty directory and
running `uv lock` there (56 packages, `tzdata` among them without being asked for).
