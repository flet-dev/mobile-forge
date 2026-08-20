import json
import time

import jiter
import ujson

VERSION = f"jiter {jiter.__version__} · ujson {ujson.__version__}"

# What jiter should do with a document that stops mid-way. 'off' is the default,
# and is what every other JSON parser in the app does.
MODES = ("off", "on", "trailing-strings")

REPLY = {
    "id": "chatcmpl-8f3",
    "model": "flet-demo-1",
    "created": 1766217600,
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "A phone can show a reply while it is still arriving, "
                "because the parser does not need the closing brace.",
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 18, "completion_tokens": 27, "score": 1.25},
}

# Compact, because that is the shape bytes have on a socket.
DOCUMENT = json.dumps(REPLY, separators=(",", ":")).encode()

# Bytes per simulated chunk. Small enough that strings visibly grow a few
# characters at a time.
CHUNK = 5

# Rows of a repetitive payload for the parser comparison. Every row repeats the
# same four keys and the same three string values, which is what the cache is for.
BULK_ROWS = 3000


def prefixes():
    """Every prefix a chunked transfer hands you, ending with the whole document."""
    return [DOCUMENT[:end] for end in range(CHUNK, len(DOCUMENT), CHUNK)] + [DOCUMENT]


def decode(prefix, mode):
    """Parse a document that stops mid-way, returning (value, error message).

    This is the reason jiter is worth shipping to a phone. With partial_mode
    'off' the call raises until the final byte lands, like any other parser.
    With 'on' the object comes back with the incomplete tail discarded, and with
    'trailing-strings' the half-arrived string is kept as far as it got.

    Two things the growing prefixes make visible. An empty or barely-started
    buffer still raises even in a partial mode, so the try/except is not
    optional. And a truncated *number* is not discarded the way a truncated
    string is -- it is parsed as far as it is valid, so this document's
    "created":1766217600 shows up as 17, then 1766217, before it is finally
    right. Watch that field go by: two of those three values are wrong, and
    nothing in the result says so.
    """
    try:
        return jiter.from_json(prefix, partial_mode=mode), ""
    except ValueError as exc:
        return None, str(exc)


def stdlib(prefix):
    """The same bytes through json.loads, whose complaint is half the demo."""
    try:
        json.loads(prefix)
    except ValueError as exc:
        return str(exc)
    return ""


def outline(value, path=""):
    """Flatten a partial document into one 'path = value' line per leaf."""
    if isinstance(value, dict):
        items = value.items()
        return [line for k, v in items for line in outline(v, f"{path}.{k}".strip("."))]
    if isinstance(value, list):
        pairs = enumerate(value)
        return [line for i, v in pairs for line in outline(v, f"{path}.{i}")]
    text = json.dumps(value)
    return [f"{path} = {text[:38] + '…' if len(text) > 38 else text}"]


def measure():
    """Time the three parsers on one repetitive payload, and count string objects.

    The timings are the honest part: on a payload this size jiter lands close to
    ujson and only modestly ahead of the standard library, which has a C scanner
    of its own. Speed is not the reason to add it.

    The object counts are the mobile-relevant part. cache_mode='all', the
    default, hands back one shared Python string for every repeat of the same
    text, so a document full of repeated status values costs a fraction of the
    memory it otherwise would -- on a device that is worth more than the
    microseconds.
    """
    rows = [
        {"status": "delivered", "region": "eu-west-1", "kind": "event", "n": i}
        for i in range(BULK_ROWS)
    ]
    payload = json.dumps(rows).encode()
    timings = [
        ("json.loads", _best(lambda: json.loads(payload))),
        ("ujson.loads", _best(lambda: ujson.loads(payload))),
        ("jiter.from_json", _best(lambda: jiter.from_json(payload))),
        (
            "jiter, cache_mode='none'",
            _best(lambda: jiter.from_json(payload, cache_mode="none")),
        ),
    ]
    unique = {
        mode: len(
            {id(row["status"]) for row in jiter.from_json(payload, cache_mode=mode)}
        )
        for mode in ("all", "none")
    }
    return len(payload), timings, unique


def _best(parse):
    """Milliseconds for the quickest of three runs, which is the least noisy."""
    best = None
    for _ in range(3):
        started = time.perf_counter()
        parse()
        elapsed = (time.perf_counter() - started) * 1000
        best = elapsed if best is None else min(best, elapsed)
    return best
