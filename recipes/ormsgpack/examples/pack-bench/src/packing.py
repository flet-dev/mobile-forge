import datetime as dt
import random
import time
import uuid
from dataclasses import dataclass

import msgpack
import ormsgpack

EXT = ormsgpack.OPT_DATETIME_AS_TIMESTAMP_EXT
NON_STR_KEYS = ormsgpack.OPT_NON_STR_KEYS

VERSIONS = (
    f"ormsgpack {ormsgpack.__version__} · "
    f"msgpack {'.'.join(str(part) for part in msgpack.version)}"
)
SIZES = (200, 1000, 5000)

# Seconds spent timing each of the four operations. Long enough that a phone's
# clock granularity and its first-call cache misses stop mattering, short enough
# that the whole run stays under a second behind the spinner.
BUDGET = 0.15

SITES = ("north", "south", "east", "west")
TAGS = ("calibrated", "indoor", "spare", "battery", "leased")

# A datetime with a real offset, because the offset is the part that does not
# survive the msgpack timestamp extension.
DELHI = dt.timezone(dt.timedelta(hours=5, minutes=30))
MOMENT = dt.datetime(2026, 8, 21, 18, 0, 45, 123456, tzinfo=DELHI)
BADGE = uuid.UUID("8c2f31b0-1f6d-4a52-9e07-3f5b2a9c4d18")


@dataclass
class Reading:
    """One sensor row as a dataclass, which ormsgpack serialises without help."""

    sensor: int
    site: str


def build_payload(count):
    """Build `count` plain-dict records: the shape an app caches or posts.

    Deterministic for a given count, so two runs at the same size compare the
    same bytes rather than two different random documents.
    """
    rng = random.Random(count)
    return [
        {
            "id": index,
            "name": f"sensor-{index:05d}",
            "site": rng.choice(SITES),
            "reading": round(rng.uniform(-40, 120), 4),
            "ok": rng.random() > 0.1,
            "tags": rng.sample(TAGS, 3),
            "note": None if index % 3 else "recalibrated",
        }
        for index in range(count)
    ]


def _milliseconds(call):
    """Run `call` for a fixed budget and return the mean milliseconds per call."""
    call()
    calls = 0
    started = time.perf_counter()
    while time.perf_counter() - started < BUDGET:
        call()
        calls += 1
    return (time.perf_counter() - started) / calls * 1e3


def compare(count):
    """Pack and unpack one payload with both libraries and time all four calls.

    The measurement the example exists for. On every payload shape tried while
    writing this, the two libraries produced *byte-identical* output, so the
    choice between them is never about wire size: whatever one writes, the other
    reads. What differs is the clock. Packing is where the Rust implementation
    wins clearly; unpacking is close enough that it is not a reason to switch on
    its own, and on short strings and bools msgpack has been measured ahead.
    """
    payload = build_payload(count)
    orm_blob = ormsgpack.packb(payload)
    msgpack_blob = msgpack.packb(payload)
    return {
        "records": count,
        "orm_bytes": len(orm_blob),
        "msgpack_bytes": len(msgpack_blob),
        "identical": orm_blob == msgpack_blob,
        "orm_pack": _milliseconds(lambda: ormsgpack.packb(payload)),
        "msgpack_pack": _milliseconds(lambda: msgpack.packb(payload)),
        "orm_unpack": _milliseconds(lambda: ormsgpack.unpackb(orm_blob)),
        "msgpack_unpack": _milliseconds(lambda: msgpack.unpackb(msgpack_blob)),
    }


def _trip(value, option=0):
    """Pack `value`, unpack it again, and return the bytes and what came back.

    `unpackb` accepts only two of the flags — OPT_NON_STR_KEYS and
    OPT_DATETIME_AS_TIMESTAMP_EXT — and raises `ValueError: Invalid opts` on any
    other, so the same `option` value cannot simply be handed to both sides.
    Masking it here is the pattern that survives adding a packing-only flag.
    """
    blob = ormsgpack.packb(value, option=option)
    return blob, ormsgpack.unpackb(blob, option=option & (EXT | NON_STR_KEYS))


def round_trips():
    """Run every asymmetric round trip live and report what each one returned.

    What the byte counts and the reprs record: ormsgpack serialises types
    msgpack refuses, but it serialises them *into msgpack's own types*, and
    nothing in the bytes says what they were. A dataclass comes back a dict, a
    UUID and a datetime come back strings, a tuple comes back a list. There is
    exactly one exception, and it is worth knowing: a tuple used as a dict *key*
    comes back a tuple, because a key has to stay hashable.

    The datetime pair is the one that changes a value rather than just a type.
    Default output is an RFC 3339 string that keeps the +05:30 offset in 34
    bytes; OPT_DATETIME_AS_TIMESTAMP_EXT writes the standard msgpack timestamp
    in 10 and gives a real datetime back, but the extension stores an instant,
    so the offset is gone and UTC is what returns. A naive datetime has no
    instant to store, so it falls back to the string form unless OPT_NAIVE_UTC
    declares that naive means UTC.
    """
    rows = []

    blob, back = _trip(Reading(7, "north"))
    rows.append(("dataclass", "Reading(7, 'north')", back, len(blob), "→ dict"))

    blob, back = _trip(BADGE)
    rows.append(("UUID", "UUID('8c2f31b0-…')", back, len(blob), "→ str"))

    blob, back = _trip(MOMENT)
    rows.append(("datetime", "18:00:45+05:30", back, len(blob), "→ str, offset kept"))

    blob, back = _trip(MOMENT, option=EXT)
    rows.append(
        ("datetime + EXT", "18:00:45+05:30", back, len(blob), "→ datetime, in UTC")
    )

    blob, back = _trip(MOMENT.replace(tzinfo=None), option=EXT)
    rows.append(
        ("naive datetime + EXT", "18:00:45", back, len(blob), "→ str, no instant")
    )

    blob, back = _trip({"seen": (1, 2)})
    rows.append(("tuple value", "{'seen': (1, 2)}", back, len(blob), "→ list"))

    blob, back = _trip({(1, 2): "cell"}, option=NON_STR_KEYS)
    rows.append(("tuple key", "{(1, 2): 'cell'}", back, len(blob), "→ still a tuple"))

    blob, back = _trip({dt.date(2026, 8, 21): "cell"}, option=NON_STR_KEYS)
    rows.append(("date key", "{date(2026, 8, 21): …}", back, len(blob), "→ str key"))

    return rows
