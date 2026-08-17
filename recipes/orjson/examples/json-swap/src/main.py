"""Time orjson against the stdlib json on this device, then show where they disagree."""

import datetime
import json
import platform
import sys
import time

import flet as ft
import orjson

SIZES = (1, 5, 20, 50, 137, 500, 1000, 2000)

TIMING_WEIGHTS = (3, 3, 3, 4)

CASE_WEIGHTS = (4, 5, 5)

FRAME_MS = 16.7

BIG_DIGITS = "12345678901234567890123"


def make_document(records):
    """Build an API-shaped document with `records` entries.

    Deterministic, so the same slider position produces the same bytes on every
    device and two phones can be compared directly. The shape is chosen to
    exercise the parts of a document where the two libraries could differ: an
    accented string (orjson never escapes it, json escapes it by default),
    floats, bools, nulls, a nested object and a list.
    """
    return {
        "generated": "2026-08-17T12:30:05.123456",
        "label": "café — edge fleet",
        "records": [
            {
                "id": f"rec-{index:05d}",
                "name": f"Naïve sensor {index % 97}",
                "value": 1.5 + (index % 1000) / 8.0,
                "ratio": index / 7.0,
                "enabled": bool(index % 3),
                "note": None if index % 5 else "seuil dépassé",
                "position": {
                    "lat": 48.8566 + index / 10000.0,
                    "lon": 2.3522 - index / 10000.0,
                },
                "tags": [f"tag-{index % 7}", f"zone-{index % 4}"],
            }
            for index in range(records)
        ],
    }


def fastest(work, reps):
    """Best of `reps` calls of `work`, in microseconds, plus its last result."""
    best, result = None, None
    for _ in range(reps):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1_000_000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, result


def ratio(quick, slow):
    """How many times faster `quick` is than `slow`, from the displayed values.

    Both arguments are already rounded to what the table prints, so the ratio a
    reader computes from the two columns is the one shown. A rounded-to-zero
    numerator would make that division meaningless rather than merely imprecise.
    """
    return f"{slow / quick:.1f}x faster" if quick else "too fast to time"


def native_origin():
    """Where the import system found the native module, as a short name.

    Read through `__spec__.origin` with `__file__` first, because neither is
    dependable: Flet relocates native extensions out of site-packages, and the
    attribute a relocated module ends up with varies by platform and by package —
    on Android it can be missing altogether.
    """
    module = orjson.orjson
    origin = getattr(module, "__file__", None) or getattr(
        getattr(module, "__spec__", None), "origin", None
    )
    return origin.rsplit("/", 1)[-1] if origin else "unreported"


def json_speedups():
    """Whether this runtime's `json` has its C speedups, as a short name.

    Without `_json` the stdlib falls back to pure Python and every ratio below
    grows for a reason that has nothing to do with orjson. Read off `sys.modules`
    because that module name is the same on every Python version, where the
    attributes the accelerators are bound to are not.
    """
    return "C" if "_json" in sys.modules else "pure Python"


def describe(work):
    """Run `work` and say what it produced, or which exception it raised.

    Every case in the divergence table is a call one library refuses, so the
    catch is the point rather than a precaution. It is deliberately broad: these
    raise plain `TypeError` and `ValueError` rather than anything library-shaped,
    and Flet turns an unhandled exception in an event handler into a crashed
    session.
    """
    try:
        return repr(work())
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def divergences():
    """The fixed list of documented json/orjson disagreements, as label and calls.

    Each entry is computed on the device when the table is built, so a row that
    stopped being true here would show its new answer instead of this list's
    expectation.
    """
    moment = datetime.datetime(2026, 8, 17, 12, 30, 5, 123456)
    return (
        (
            'dumps {1: "a"}',
            lambda: json.dumps({1: "a"}),
            lambda: orjson.dumps({1: "a"}),
        ),
        (
            'dumps {1: "a"} +NON_STR_KEYS',
            lambda: json.dumps({1: "a"}),
            lambda: orjson.dumps({1: "a"}, option=orjson.OPT_NON_STR_KEYS),
        ),
        (
            'dumps {"x": nan}',
            lambda: json.dumps({"x": float("nan")}),
            lambda: orjson.dumps({"x": float("nan")}),
        ),
        (
            'loads "NaN"',
            lambda: json.loads("NaN"),
            lambda: orjson.loads("NaN"),
        ),
        (
            "dumps a datetime",
            lambda: json.dumps(moment),
            lambda: orjson.dumps(moment),
        ),
        (
            "dumps 2**64",
            lambda: json.dumps(2**64),
            lambda: orjson.dumps(2**64),
        ),
        (
            # json's column prints the digits; a phone column cannot hold them twice
            "loads a 23-digit int",
            lambda: json.loads(BIG_DIGITS),
            lambda: orjson.loads(BIG_DIGITS),
        ),
        (
            'dumps "café"',
            lambda: json.dumps("café"),
            lambda: orjson.dumps("café"),
        ),
    )


def plural(records):
    """`records` with a thousands separator and the right noun after it."""
    return f"{records:,} record{'' if records == 1 else 's'}"


def table_row(values, weights, size=11):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Measure the swap on this device and print what it would change.

    The timings are the headline, but the two equality checks beside them are
    what make the headline worth reading: the round trip has to produce the same
    object through both libraries, and orjson's output has to be byte-for-byte
    what `json.dumps` produces with `separators=(",", ":")` and
    `ensure_ascii=False`. Without those, a speedup could just as well be a
    different encoding.
    """

    def show_count():
        """Report the document size the next run will use, as the slider moves."""
        caption.value = f"{plural(SIZES[int(size.value)])} per document"

    def start():
        """Hand one run to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end, which fires once on release, so one
        gesture means one run. The guard is tested and set here rather than inside
        `run` because this body is synchronous where `run_thread` only schedules:
        a `disabled` set inside the worker would not have happened yet when this
        handler returns and Flet pushes the control states, so a second release
        would be accepted and two runs would rewrite the same table.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Serialise and parse the document with both libraries and fill the table.

        orjson holds the GIL for the whole call, so this thread buys nothing but a
        handler that returns immediately — which is the honest reason to use it
        here. The try/except is load-bearing: `page.run_thread` discards whatever
        a worker raises, so a mistake in here would look like a screen that
        quietly stopped updating. It clears the table as well as writing the
        message, because timings left over from the previous run read as though
        they described the error.
        """
        try:
            records = SIZES[int(size.value)]
            reps = 25 if records > 200 else 200
            document = make_document(records)

            dumps_fast, raw = fastest(lambda: orjson.dumps(document), reps)
            dumps_slow, text = fastest(lambda: json.dumps(document), reps)
            loads_fast, from_orjson = fastest(lambda: orjson.loads(raw), reps)
            loads_slow, from_json = fastest(lambda: json.loads(text), reps)

            compact = json.dumps(
                document, separators=(",", ":"), ensure_ascii=False
            ).encode()
            wide, narrow = len(text.encode()), len(raw)

            dumps_fast, dumps_slow = round(dumps_fast, 1), round(dumps_slow, 1)
            loads_fast, loads_slow = round(loads_fast, 1), round(loads_slow, 1)

            timings.controls = [
                table_row(
                    ("measure", "orjson", "json", "orjson vs json"), TIMING_WEIGHTS
                ),
                ft.Divider(height=1),
                table_row(
                    (
                        "dumps µs",
                        f"{dumps_fast:,.1f}",
                        f"{dumps_slow:,.1f}",
                        ratio(dumps_fast, dumps_slow),
                    ),
                    TIMING_WEIGHTS,
                ),
                table_row(
                    (
                        "loads µs",
                        f"{loads_fast:,.1f}",
                        f"{loads_slow:,.1f}",
                        ratio(loads_fast, loads_slow),
                    ),
                    TIMING_WEIGHTS,
                ),
                table_row(
                    (
                        "output B",
                        f"{narrow:,}",
                        f"{wide:,}",
                        f"{100 * (wide - narrow) // wide}% smaller",
                    ),
                    TIMING_WEIGHTS,
                ),
            ]
            checks.value = (
                "round trip: "
                + (
                    "identical objects"
                    if from_orjson == from_json
                    else "DIFFERENT OBJECTS"
                )
                + " · vs json compact: "
                + ("identical bytes" if raw == compact else "DIFFERENT BYTES")
            )
            verdict.value = (
                f"{plural(records)} · dumps saves "
                f"{dumps_slow - dumps_fast:,.1f} µs and loads saves "
                f"{loads_slow - loads_fast:,.1f} µs per call, "
                f"against a {FRAME_MS} ms frame at 60 Hz"
            )
        except Exception as error:
            timings.controls = []
            checks.value = ""
            verdict.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def fill_cases():
        """Build the divergence table by making every call on this device."""
        cases.controls = [
            table_row(("case", "json", "orjson"), CASE_WEIGHTS, size=10),
            ft.Divider(height=1),
            *(
                table_row(
                    (label, describe(stdlib), describe(fast)), CASE_WEIGHTS, size=10
                )
                for label, stdlib, fast in divergences()
            ),
        ]

    page.appbar = ft.AppBar(title=ft.Text("orjson vs json"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"orjson {orjson.__version__} · "
                        f"Python {platform.python_version()} · {page.platform.value} · "
                        f"native {native_origin()}",
                        size=11,
                    ),
                    ft.Text(
                        f"orjson.dumps() returns {type(orjson.dumps(0)).__name__}, "
                        f"json.dumps() returns {type(json.dumps(0)).__name__} · "
                        f"stdlib json speedups: {json_speedups()}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=0,
                        max=len(SIZES) - 1,
                        value=3,
                        divisions=len(SIZES) - 1,
                        on_change=show_count,
                        on_change_end=start,
                    ),
                    timings := ft.Column(spacing=4),
                    checks := ft.Text(size=11),
                    verdict := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("json vs orjson, case by case", size=11),
                    cases := ft.Column(spacing=4),
                ],
            ),
        )
    )

    show_count()
    fill_cases()
    start()


if __name__ == "__main__":
    ft.run(main)
