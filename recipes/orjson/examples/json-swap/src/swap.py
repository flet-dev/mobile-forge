import datetime
import json
import sys
import time

import orjson

# Records per document, from a settings blob to something a sync would send.
SIZES = (1, 5, 20, 50, 137, 500, 1000, 2000)

FRAME_MS = 16.7  # one frame at 60 Hz, the yardstick every saving is measured against

BIG_DIGITS = "12345678901234567890123"


def header(device):
    """Two lines naming what is running and where the native module came from.

    The bytes-versus-str difference is asked of the two libraries rather than
    written out, so it cannot go stale. The origin is read through `__file__`
    first and `__spec__.origin` second because Flet relocates native extensions
    out of site-packages, and which attribute survives that varies by platform
    and by package -- on Android it can be missing altogether.

    The stdlib's C speedups are worth naming too: without `_json` every `json`
    column below inflates for a reason that has nothing to do with orjson.
    """
    module = orjson.orjson
    origin = getattr(module, "__file__", None) or getattr(
        getattr(module, "__spec__", None), "origin", None
    )
    return (
        f"orjson {orjson.__version__} · Python {sys.version.split()[0]} · {device} · "
        f"native {origin.rsplit('/', 1)[-1] if origin else 'unreported'}",
        f"orjson.dumps() returns {type(orjson.dumps(0)).__name__}, "
        f"json.dumps() returns {type(json.dumps(0)).__name__} · stdlib json speedups: "
        f"{'C' if '_json' in sys.modules else 'pure Python'}",
    )


def document(records):
    """Build an API-shaped document with `records` entries.

    Deterministic, so the same slider position produces the same bytes on every
    device and two phones can be compared directly. The shape exercises the parts
    of a document where the two libraries could differ: an accented string (orjson
    never escapes it, json escapes it by default), floats, bools, nulls, a nested
    object and a list.
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


def measure(records):
    """Serialise and parse one document with both libraries, and check they agree.

    Returns the four best-of-N timings in microseconds, both output sizes, and the
    two equality checks that make the timings worth reading. The round trip has to
    produce the same object through either library, and orjson's output has to be
    byte-for-byte what `json.dumps` produces with `separators=(",", ":")` and
    `ensure_ascii=False` -- without that second check a speedup could just as well
    be a different encoding, and the size row would mean nothing.

    Timings are rounded here rather than at display time so that the ratio a reader
    computes from the two printed columns is the ratio the table shows.
    """
    reps = 25 if records > 200 else 200
    payload = document(records)

    dumps_fast, raw = _best(lambda: orjson.dumps(payload), reps)
    dumps_slow, text = _best(lambda: json.dumps(payload), reps)
    loads_fast, from_orjson = _best(lambda: orjson.loads(raw), reps)
    loads_slow, from_json = _best(lambda: json.loads(text), reps)

    compact = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return {
        "dumps": (round(dumps_fast, 1), round(dumps_slow, 1)),
        "loads": (round(loads_fast, 1), round(loads_slow, 1)),
        "size": (len(raw), len(text.encode())),
        "same_object": from_orjson == from_json,
        "same_bytes": raw == compact,
    }


def divergences():
    """Every documented json/orjson disagreement, run here and reported as text.

    Each row is computed on the device when the table is built, so a case that
    stopped being true would show its new answer instead of this list's
    expectation. The most dangerous of them is the 23-digit integer: `json` returns
    it exactly, orjson returns a float, and nothing raises.
    """
    moment = datetime.datetime(2026, 8, 17, 12, 30, 5, 123456)
    cases = (
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
        ('loads "NaN"', lambda: json.loads("NaN"), lambda: orjson.loads("NaN")),
        ("dumps a datetime", lambda: json.dumps(moment), lambda: orjson.dumps(moment)),
        ("dumps 2**64", lambda: json.dumps(2**64), lambda: orjson.dumps(2**64)),
        (
            "loads a 23-digit int",
            lambda: json.loads(BIG_DIGITS),
            lambda: orjson.loads(BIG_DIGITS),
        ),
        ('dumps "café"', lambda: json.dumps("café"), lambda: orjson.dumps("café")),
    )
    return [(label, _describe(left), _describe(right)) for label, left, right in cases]


def _best(work, reps):
    """Best of `reps` calls of `work`, in microseconds, plus its last result."""
    best, result = None, None
    for _ in range(reps):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1_000_000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, result


def _describe(work):
    """Run `work` and say what it produced, or which exception it raised.

    Every case above is a call one library refuses, so the catch is the point
    rather than a precaution. It is deliberately broad: these raise plain
    `TypeError` and `ValueError` rather than anything library-shaped, and Flet
    turns an unhandled exception in an event handler into a crashed session.
    """
    try:
        return repr(work())
    except Exception as error:
        return f"{type(error).__name__}: {error}"
