"""Ask this device whether ujson is really faster than the stdlib json."""

import decimal
import json
import platform
import sys
import time

import flet as ft

try:
    import ujson
except ImportError as error:  # a missing wheel must read as a message, not a crash
    ujson, IMPORT_ERROR = None, error
else:
    IMPORT_ERROR = None

COUNTS = ("100", "1000", "5000")

REPS = {"100": 150, "1000": 40, "5000": 10}

SHAPE_WEIGHTS = (5, 5, 4, 5, 4, 5)

AUDIT_WEIGHTS = (5, 6, 5)

FRAME_US = 16_700.0

BIG_DIGITS = "12345678901234567890123"

LONG_DECIMAL = "1.234567890123456789012345"


def api_records(count):
    """A document of API-shaped objects: strings, floats, bools, nulls, nesting.

    The `source` field carries a URL because slashes are the one character the
    two libraries treat differently by default, and a document without one hides
    the difference the size column is there to show.
    """
    return {
        "generated": "2026-08-19T12:30:05.123456",
        "source": "https://api.example.com/v1/fleet",
        "records": [
            {
                "id": f"rec-{index:05d}",
                "name": f"Sensor {index % 97}",
                "value": 1.5 + (index % 1000) / 8.0,
                "ratio": index / 7.0,
                "enabled": bool(index % 3),
                "note": None if index % 5 else "threshold crossed",
                "position": {
                    "lat": 48.8566 + index / 10000.0,
                    "lon": 2.3522 - index / 10000.0,
                },
                "tags": [f"tag-{index % 7}", f"zone-{index % 4}"],
            }
            for index in range(count)
        ],
    }


def float_series(count):
    """A list of doubles that need their full precision to survive a round trip.

    Built from integer arithmetic rather than `random` or `math.sin` so every
    device produces the same bytes: a value divided by 7 has a 16-to-17 digit
    decimal form, which is what makes this the shape that separates the two
    number formatters.
    """
    return [((index * 48271) % 2147483647) / 7.0 for index in range(count)]


def feature_flags(count):
    """A list of booleans — the cheapest possible values to encode."""
    return [bool((index * 2654435761) % 3) for index in range(count)]


def asset_urls(count):
    """A list of URLs, i.e. strings that are mostly slashes and ASCII."""
    return [
        f"https://cdn.example.com/assets/v2/img/{index:06d}/thumb.webp"
        for index in range(count)
    ]


def unicode_labels(count):
    """A list of accented strings, which both libraries escape by default."""
    return [f"élément-{index:06d} — naïve café" for index in range(count)]


SHAPES = (
    ("records", api_records),
    ("floats", float_series),
    ("flags", feature_flags),
    ("URLs", asset_urls),
    ("text", unicode_labels),
)


def fastest(work, reps):
    """Best of `reps` calls of `work`, in microseconds, plus its last result.

    The best rather than the mean: on a phone the mean mostly measures whatever
    else the scheduler decided to run, while the minimum is the closest thing to
    the cost of the call itself.
    """
    best, result = None, None
    for _ in range(reps):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1_000_000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, result


def measure(build, count, reps):
    """Serialise and parse one document with both libraries.

    `json` is called with `separators=(",", ":")` so it is compared at its own
    compact setting: ujson has no spacing to remove, and against `json.dumps`
    defaults every size difference would be spaces rather than anything about
    the encoders. The document is built here and dropped on return, so only one
    shape is ever in memory — the 5,000-item records document is a few megabytes.
    """
    document = build(count)
    u_dumps, u_text = fastest(lambda: ujson.dumps(document), reps)
    j_dumps, j_text = fastest(lambda: json.dumps(document, separators=(",", ":")), reps)
    u_loads, u_object = fastest(lambda: ujson.loads(u_text), reps)
    j_loads, j_object = fastest(lambda: json.loads(j_text), reps)
    return {
        "dumps": (u_dumps, j_dumps),
        "loads": (u_loads, j_loads),
        "bytes": (len(u_text.encode()), len(j_text.encode())),
        "agree": u_object == j_object and json.loads(u_text) == ujson.loads(j_text),
    }


def duration(value):
    """Microseconds for a table cell: readable at 8 µs and at 80,000 µs."""
    return f"{value:,.1f}" if value < 1000 else f"{value:,.0f}"


def describe(work):
    """Run `work` and return its result, or the exception it raised, as text.

    Half the audit rows below are calls one of the two libraries refuses, so
    catching is the point rather than a precaution. The catch is deliberately
    broad — these raise plain `TypeError`, `ValueError` and `OverflowError` —
    and it has to be here, because Flet turns an unhandled exception in an
    event handler into a crashed session.
    """
    try:
        answer = repr(work())
    except Exception as error:
        answer = f"{type(error).__name__}: {error}"
    return answer if len(answer) <= 56 else answer[:55] + "…"


def compare(label, ours, theirs):
    """One audit row: the label, ujson's answer, and how the stdlib's differed."""
    mine, yours = describe(ours), describe(theirs)
    return label, mine, ("same as json" if mine == yours else f"json: {yours}")


def decode_failure():
    """The exception ujson raises for malformed JSON, as an object.

    Returned rather than described so the audit row can ask what an existing
    `except json.JSONDecodeError` clause would have done with it.
    """
    try:
        ujson.loads("{")
    except Exception as error:
        return error
    return None


def audit():
    """The drop-in questions, each answered by a call made on this device.

    Every row is computed here rather than quoted, so a row that stopped being
    true on some platform or some ujson release would print its new answer
    instead of this list's expectation. Nothing here recurses deeply: the 1,024
    level encoder cap is real but probing it means 1,024 frames of C stack on a
    phone thread, which is a worse thing to learn from an example than from a
    sentence.
    """
    failure = decode_failure()
    slash = {"u": "a/b"}
    big = decimal.Decimal(LONG_DECIMAL)
    return (
        compare(
            "dumps returns",
            lambda: type(ujson.dumps(0)).__name__,
            lambda: type(json.dumps(0)).__name__,
        ),
        compare(
            'dumps {"u": "a/b"}',
            lambda: ujson.dumps(slash),
            lambda: json.dumps(slash, separators=(",", ":")),
        ),
        compare(
            "dumps float('nan')",
            lambda: ujson.dumps(float("nan")),
            lambda: json.dumps(float("nan")),
        ),
        compare(
            "loads a 23-digit int",
            lambda: ujson.loads(BIG_DIGITS),
            lambda: json.loads(BIG_DIGITS),
        ),
        compare(
            'dumps {(1, 2): "a"}',
            lambda: ujson.dumps({(1, 2): "a"}),
            lambda: json.dumps({(1, 2): "a"}),
        ),
        compare(
            "dumps a 25-digit Decimal",
            lambda: ujson.dumps(big),
            lambda: json.dumps(big),
        ),
        compare(
            "loads(text, object_hook=)",
            lambda: ujson.loads("{}", object_hook=dict),
            lambda: json.loads("{}", object_hook=dict),
        ),
        (
            "bad JSON raises",
            f"{type(failure).__name__}: {failure}",
            "except json.JSONDecodeError catches it"
            if isinstance(failure, json.JSONDecodeError)
            else "except json.JSONDecodeError misses it",
        ),
    )


def native_origin():
    """Where the import system found ujson, as a short name.

    Read through `__spec__.origin` when `__file__` is missing, because neither
    is dependable: Flet moves native extensions out of site-packages, and which
    attribute survives varies by platform.
    """
    origin = getattr(ujson, "__file__", None) or getattr(
        getattr(ujson, "__spec__", None), "origin", None
    )
    return origin.rsplit("/", 1)[-1] if origin else "unreported"


def json_speedups():
    """Whether this runtime's `json` has its C accelerator, as a short name.

    Without `_json` the stdlib parses and serialises in pure Python, and every
    comparison below turns into a landslide for a reason that has nothing to do
    with ujson.
    """
    return "C" if "_json" in sys.modules else "pure Python"


def table_row(values, weights, size=11):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Time both libraries on five payload shapes and audit the swap.

    The shape picker is the whole point: ujson is not uniformly faster, and one
    document would let you conclude either way depending on which one you
    picked. Each run rebuilds every shape at the chosen size, so the numbers on
    screen were produced by this device rather than quoted from a desktop.
    """

    def start():
        """Hand one sweep to a background thread and lock the picker meanwhile.

        The guard is tested and set here rather than inside `run` because this
        body is synchronous where `page.run_thread` only schedules: a `disabled`
        set inside the worker would not have happened yet when this handler
        returns and Flet pushes the control states, so a second tap would be
        accepted and two sweeps would rewrite the same table.
        """
        if picker.disabled:
            return
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Measure every shape at the chosen size and fill the table.

        The try/except is load-bearing: `page.run_thread` discards whatever a
        worker raises, so a mistake in here would look like a screen that
        quietly stopped updating. It clears the table on the way out as well as
        writing the message, because a previous run's timings left under an
        error read as though they described it.
        """
        try:
            choice = picker.selected[0]
            count, reps = int(choice), REPS[choice]
            rows, summary, mismatched = [], [], []

            for name, build in SHAPES:
                result = measure(build, count, reps)
                u_dumps, j_dumps = result["dumps"]
                u_loads, j_loads = result["loads"]
                u_bytes, j_bytes = result["bytes"]
                rows.append(
                    table_row(
                        (
                            name,
                            duration(u_dumps),
                            duration(j_dumps),
                            duration(u_loads),
                            duration(j_loads),
                            f"{100.0 * (u_bytes - j_bytes) / j_bytes:+.1f}%",
                        ),
                        SHAPE_WEIGHTS,
                    )
                )
                summary.append(
                    (
                        name,
                        j_dumps / u_dumps,
                        j_loads / u_loads,
                        100.0 * (u_bytes - j_bytes) / j_bytes,
                        j_dumps - u_dumps,
                    )
                )
                if not result["agree"]:
                    mismatched.append(name)

            table.controls = [
                table_row(
                    ("shape", "u dumps", "json", "u loads", "json", "bytes"),
                    SHAPE_WEIGHTS,
                ),
                ft.Divider(height=1),
                *rows,
            ]
            quickest = max(summary, key=lambda row: row[1])
            slowest = min(summary, key=lambda row: row[1])
            widest = max(summary, key=lambda row: abs(row[3]))
            saved = sum(row[4] for row in summary)
            verdict.value = (
                f"{count:,} items each · dumps best {quickest[0]} "
                f"{quickest[1]:.2f}x, worst {slowest[0]} {slowest[1]:.2f}x · "
                f"largest size change {widest[0]} {widest[3]:+.1f}% · "
                f"all five dumps together save {saved:,.0f} µs "
                f"of a {FRAME_US:,.0f} µs frame at 60 Hz"
            )
            checks.value = (
                "round trip: identical objects, both directions, all shapes"
                if not mismatched
                else f"round trip: OBJECTS DIFFER for {', '.join(mismatched)}"
            )
        except Exception as error:
            table.controls = []
            checks.value = ""
            verdict.value = f"{type(error).__name__}: {error}"

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("ujson vs json"), center_title=True)

    if ujson is None:
        page.add(
            ft.SafeArea(
                content=ft.Column(
                    controls=[
                        ft.Text("ujson did not import", size=16),
                        ft.Text(f"{type(IMPORT_ERROR).__name__}: {IMPORT_ERROR}"),
                        ft.Text(
                            'Add "ujson" to [project] dependencies and rebuild; '
                            "the mobile wheels come from pypi.flet.dev.",
                            size=11,
                        ),
                    ]
                )
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
                        f"ujson {ujson.__version__} · "
                        f"Python {platform.python_version()} · "
                        f"{page.platform.value} · native {native_origin()}",
                        size=11,
                    ),
                    ft.Text(
                        f"stdlib json speedups: {json_speedups()} · "
                        "times are microseconds per call, best of "
                        f"{REPS['100']}/{REPS['1000']}/{REPS['5000']} · "
                        "json is called compact",
                        size=11,
                    ),
                    ft.Row(
                        scroll=ft.ScrollMode.AUTO,
                        controls=[
                            picker := ft.SegmentedButton(
                                segments=[
                                    ft.Segment(value=count, label=f"{int(count):,}")
                                    for count in COUNTS
                                ],
                                selected=[COUNTS[1]],
                                show_selected_icon=False,
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ],
                    ),
                    table := ft.Column(spacing=4),
                    checks := ft.Text(size=11),
                    verdict := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("is the swap transparent?", size=11),
                    ft.Column(
                        spacing=4,
                        controls=[
                            table_row(("case", "ujson", "vs json"), AUDIT_WEIGHTS, 10),
                            ft.Divider(height=1),
                            *(table_row(row, AUDIT_WEIGHTS, 10) for row in audit()),
                        ],
                    ),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
