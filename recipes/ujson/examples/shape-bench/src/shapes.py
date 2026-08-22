import decimal
import json
import sys
import time

import ujson

# Items per document: a settings blob, a screenful of records, a sync payload.
COUNTS = ("100", "1000", "5000")

# Fewer repetitions as the documents grow, so one sweep stays under a second.
REPS = {"100": 150, "1000": 40, "5000": 10}

FRAME_US = 16_700.0  # one frame at 60 Hz, what every saving is measured against

BIG_DIGITS = "12345678901234567890123"

LONG_DECIMAL = "1.234567890123456789012345"


def api_records(count):
    """A document of API-shaped objects: strings, floats, bools, nulls, nesting.

    The `source` field carries a URL because slashes are the one character the two
    libraries treat differently by default, and a document without one hides the
    difference the size column is there to show.
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

    Built from integer arithmetic rather than `random` or `math.sin` so every device
    produces the same bytes: a value divided by 7 has a 16-to-17 digit decimal form,
    which is what makes this the shape that separates the two number formatters.
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


def header(device):
    """Two lines naming what is running and where the native module came from.

    The origin is read through `__file__` first and `__spec__.origin` second, because
    Flet relocates native extensions out of site-packages and which attribute survives
    that varies by platform — on Android it can be missing altogether.

    The stdlib's C speedups are worth naming too: without `_json` the stdlib parses and
    serialises in pure Python, and every `json` column below turns into a landslide for
    a reason that has nothing to do with ujson.
    """
    origin = getattr(ujson, "__file__", None) or getattr(
        getattr(ujson, "__spec__", None), "origin", None
    )
    return (
        f"ujson {ujson.__version__} · Python {sys.version.split()[0]} · {device} · "
        f"native {origin.rsplit('/', 1)[-1] if origin else 'unreported'}",
        f"stdlib json speedups: {'C' if '_json' in sys.modules else 'pure Python'} · "
        f"microseconds per call, best of {REPS['100']}/{REPS['1000']}/{REPS['5000']} · "
        "json is called compact",
    )


def sweep(choice):
    """Time every shape at `choice` items and return one plain row per shape.

    Each row carries both libraries' `dumps` and `loads` timings in microseconds, the
    size difference as a percentage, the ratio and saving the verdict line needs, and
    whether the two libraries agreed on the parsed object.
    """
    count, reps = int(choice), REPS[choice]
    return [_measure(name, build, count, reps) for name, build in SHAPES]


def verdict(choice, rows):
    """One sentence placing the sweep against a frame at 60 Hz.

    The best and worst shape are named rather than averaged: ujson is not uniformly
    faster, and a mean over five shapes would hide the one that loses.
    """
    quickest = max(rows, key=lambda row: row["dumps_ratio"])
    slowest = min(rows, key=lambda row: row["dumps_ratio"])
    widest = max(rows, key=lambda row: abs(row["size_pct"]))
    saved = sum(row["saved"] for row in rows)
    return (
        f"{int(choice):,} items each · dumps best {quickest['name']} "
        f"{quickest['dumps_ratio']:.2f}x, worst {slowest['name']} "
        f"{slowest['dumps_ratio']:.2f}x · largest size change {widest['name']} "
        f"{widest['size_pct']:+.1f}% · all five dumps together save {saved:,.0f} µs "
        f"of a {FRAME_US:,.0f} µs frame at 60 Hz"
    )


def crosscheck(rows):
    """Whether every shape round-tripped to the same object through both libraries.

    Stated on screen so a wrong answer is visible rather than merely plausible: a
    speedup means nothing if the data came back different.
    """
    disagreed = [row["name"] for row in rows if not row["agree"]]
    if disagreed:
        return f"round trip: OBJECTS DIFFER for {', '.join(disagreed)}"
    return "round trip: identical objects, both directions, all shapes"


def audit():
    """The drop-in questions, each answered by a call made on this device.

    Every row is computed here rather than quoted, so a case that stopped being true on
    some platform or some ujson release prints its new answer instead of this list's
    expectation. Nothing here recurses deeply: the 1,024-level encoder cap is real, but
    probing it means 1,024 frames of C stack on a phone thread, which is a worse thing
    to learn from an example than from a sentence.
    """
    failure = _decode_failure()
    slash = {"u": "a/b"}
    big = decimal.Decimal(LONG_DECIMAL)
    return (
        _compare(
            "dumps returns",
            lambda: type(ujson.dumps(0)).__name__,
            lambda: type(json.dumps(0)).__name__,
        ),
        _compare(
            'dumps {"u": "a/b"}',
            lambda: ujson.dumps(slash),
            lambda: json.dumps(slash, separators=(",", ":")),
        ),
        _compare(
            "dumps float('nan')",
            lambda: ujson.dumps(float("nan")),
            lambda: json.dumps(float("nan")),
        ),
        _compare(
            "loads a 23-digit int",
            lambda: ujson.loads(BIG_DIGITS),
            lambda: json.loads(BIG_DIGITS),
        ),
        _compare(
            'dumps {(1, 2): "a"}',
            lambda: ujson.dumps({(1, 2): "a"}),
            lambda: json.dumps({(1, 2): "a"}),
        ),
        _compare(
            "dumps a 25-digit Decimal",
            lambda: ujson.dumps(big),
            lambda: json.dumps(big),
        ),
        _compare(
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


def _measure(name, build, count, reps):
    """Serialise and parse one document of `name` with both libraries.

    `json` is called with `separators=(",", ":")` so it is compared at its own compact
    setting: ujson has no spacing to remove, and against `json.dumps` defaults every
    size difference would be spaces rather than anything about the encoders. The
    document is built here and dropped on return, so only one shape is ever in memory —
    the 5,000-item records document is a few megabytes on its own.
    """
    document = build(count)
    u_dumps, u_text = _best(lambda: ujson.dumps(document), reps)
    j_dumps, j_text = _best(lambda: json.dumps(document, separators=(",", ":")), reps)
    u_loads, u_object = _best(lambda: ujson.loads(u_text), reps)
    j_loads, j_object = _best(lambda: json.loads(j_text), reps)
    u_bytes, j_bytes = len(u_text.encode()), len(j_text.encode())
    return {
        "name": name,
        "dumps": (u_dumps, j_dumps),
        "loads": (u_loads, j_loads),
        "size_pct": 100.0 * (u_bytes - j_bytes) / j_bytes,
        "dumps_ratio": j_dumps / u_dumps,
        "saved": j_dumps - u_dumps,
        "agree": u_object == j_object and json.loads(u_text) == ujson.loads(j_text),
    }


def _best(work, reps):
    """Best of `reps` calls of `work`, in microseconds, plus its last result.

    The best rather than the mean: on a phone the mean mostly measures whatever else
    the scheduler decided to run, while the minimum is the closest thing to the cost of
    the call itself.
    """
    best, result = None, None
    for _ in range(reps):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1_000_000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, result


def _decode_failure():
    """The exception ujson raises for malformed JSON, as an object.

    Returned rather than described so the audit row can ask what an existing
    `except json.JSONDecodeError` clause would have done with it.
    """
    try:
        ujson.loads("{")
    except Exception as error:
        return error
    return None


def _compare(label, ours, theirs):
    """One audit row: the label, ujson's answer, and how the stdlib's differed."""
    mine, yours = _describe(ours), _describe(theirs)
    return label, mine, ("same as json" if mine == yours else f"json: {yours}")


def _describe(work):
    """Run `work` and return its result, or the exception it raised, as short text.

    Half the audit rows are calls one of the two libraries refuses, so catching is the
    point rather than a precaution. The catch is deliberately broad — these raise plain
    `TypeError`, `ValueError` and `OverflowError` — and it has to be here, because Flet
    turns an unhandled exception in an event handler into a crashed session.
    """
    try:
        answer = repr(work())
    except Exception as error:
        answer = f"{type(error).__name__}: {error}"
    return answer if len(answer) <= 56 else answer[:55] + "…"
