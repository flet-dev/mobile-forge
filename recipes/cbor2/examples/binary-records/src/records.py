import base64
import json
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.metadata import version

import cbor2

# cbor2 6.x is one Rust extension with no pure-Python fallback, so dumps is
# always a builtin and __module__ always names the accelerator. Reading it is
# how you check on a device, where a native module may report no __file__.
VERSION = f"cbor2 {version('cbor2')} · dumps from {cbor2.dumps.__module__}"

SEED = 20260821
EPOCH = datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)
FLAGS = ("calibrated", "indoor", "retry", "roaming")

# Tag 27 is registered with IANA for "a serialised language-independent object
# with type name and constructor arguments" — exactly the shape a default= hook
# needs, so a custom type gets a standard wrapper instead of a private one.
OBJECT_TAG = 27

SAMPLES = (
    ("datetime, aware", EPOCH),
    ("Decimal", Decimal("19.99")),
    ("int, 80 bits", 2**80 + 7),
    ("set", {"indoor", "retry"}),
    ("UUID", uuid.UUID(int=SEED)),
    ("bytes", b"\x89PNG\r\n\x1a\n"),
    ("str", "café"),
)


@dataclass(frozen=True)
class Coordinate:
    """A type no CBOR tag describes, so the app has to supply the encoding."""

    lat: float
    lon: float


def leading_tag(blob):
    """Read the tag number off the front of an encoded value, or None.

    Major type 6 is a tag: the top three bits of the first byte are 110, and the
    low five are the tag number itself when it is under 24, or the width of the
    number that follows. Doing that by hand is the point of the exercise — a
    tagged value announces its type on the wire, so a decoder that has never
    heard of tag 4 still knows how much of the document to skip.
    """
    head = blob[0]
    if head >> 5 != 6:
        return None
    extra = head & 0x1F
    if extra < 24:
        return extra
    return int.from_bytes(blob[1 : 1 + {24: 1, 25: 2, 26: 4, 27: 8}[extra]], "big")


def json_verdict(value):
    """What json does with the same value: refuse it, change it, or carry it.

    The int is the interesting answer. json.dumps writes all 25 digits and
    Python reads them back exactly, so the round trip looks clean — but JSON has
    one number type, and a receiver that maps numbers onto IEEE doubles gets a
    different integer above 2**53. CBOR gives it tag 2 and a byte string, which
    no decoder can quietly widen into a float.
    """
    try:
        text = json.dumps(value)
    except TypeError:
        return "TypeError"
    back = json.loads(text)
    if type(back) is not type(value) or back != value:
        return f"{type(back).__name__}, changed"
    if isinstance(back, int) and abs(back) > 2**53:
        return "int, > 2**53"
    return f"{type(back).__name__}, exact"


def tag_table():
    """One row per sample: the tag CBOR wrote, and what each format returns.

    Each value is encoded on its own, so the hex is that value's whole encoding
    and the tag is the first thing in it.
    """
    rows = []
    for label, value in SAMPLES:
        blob = cbor2.dumps(value)
        back = cbor2.loads(blob)
        tag = leading_tag(blob)
        rows.append(
            {
                "label": label,
                "hex": blob[:6].hex(" ") + (" ..." if len(blob) > 6 else ""),
                "tag": "—" if tag is None else str(tag),
                "cbor": f"{type(back).__name__}, "
                + ("exact" if back == value else "changed"),
                "json": json_verdict(value),
            }
        )
    return rows


def _encode_unknown(encoder, value):
    """default= hook: give a type CBOR has no tag for the standard tag-27 shape."""
    if isinstance(value, Coordinate):
        encoder.encode(cbor2.CBORTag(OBJECT_TAG, ["Coordinate", value.lat, value.lon]))
    else:
        raise cbor2.CBOREncodeTypeError(f"cannot serialise {type(value).__name__}")


def _decode_unknown(tag, shareable):
    """tag_hook= : rebuild a Coordinate, and pass every other tag through.

    tag.value is a tuple, and a map nested inside a tag is an immutable mapping:
    6.x decodes tag payloads immutably so they can serve as dict keys. Index
    them, do not append to them. The second argument is the value-sharing flag,
    and can be ignored unless you encode with value_sharing=True.
    """
    if tag.tag == OBJECT_TAG and tag.value[0] == "Coordinate":
        return Coordinate(tag.value[1], tag.value[2])
    return tag


def custom_roundtrip():
    """Encode a Coordinate, then decode it twice: without the hook, and with it.

    The no-hook decode is the part worth looking at. It does not raise — an
    unknown tag becomes a CBORTag holding its number and payload, so a reader
    that does not know your type still parses the document around it.
    """
    home = Coordinate(48.8584, 2.2945)
    blob = cbor2.dumps(home, default=_encode_unknown)
    back = cbor2.loads(blob, tag_hook=_decode_unknown)
    return {
        "hex": blob.hex(" "),
        "plain": repr(cbor2.loads(blob)),
        "back": repr(back),
        "same": back == home,
    }


def build_document(count):
    """Build a device journal of `count` records, seeded so sizes are repeatable.

    Five of the eight fields per record are types json refuses outright, which
    is the whole reason this is a CBOR document.
    """
    rng = random.Random(SEED)
    return {
        "device": uuid.UUID(int=SEED),
        "generated": EPOCH,
        "records": [
            {
                "id": uuid.UUID(int=rng.getrandbits(128)),
                "at": EPOCH + timedelta(seconds=37 * index),
                "amount": Decimal(f"{rng.randrange(1, 99999)}.{rng.randrange(99):02d}"),
                "flags": set(rng.sample(FLAGS, rng.randrange(1, 4))),
                "serial": 2**72 + rng.getrandbits(48),
                "digest": rng.randbytes(16),
                "temp_c": round(rng.uniform(-10, 45), 2),
                "ok": rng.random() > 0.1,
            }
            for index in range(count)
        ],
    }


def _json_ready(value):
    """json default= : flatten every CBOR-native type into something json takes.

    This function is half of the side agreement that CBOR's tags remove: nothing
    in the output says a string is a timestamp, a decimal or base64.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    raise TypeError(f"cannot serialise {type(value).__name__}")


def _rehydrate(payload):
    """The other half: turn json's strings back into the original types.

    Written out in full because that is the point. The receiver of a JSON
    document maintains this by hand, field by field, in step with the sender.
    """
    return {
        "device": uuid.UUID(payload["device"]),
        "generated": datetime.fromisoformat(payload["generated"]),
        "records": [
            {
                "id": uuid.UUID(record["id"]),
                "at": datetime.fromisoformat(record["at"]),
                "amount": Decimal(record["amount"]),
                "flags": set(record["flags"]),
                "serial": record["serial"],
                "digest": base64.b64decode(record["digest"]),
                "temp_c": record["temp_c"],
                "ok": record["ok"],
            }
            for record in payload["records"]
        ],
    }


def _fastest(work, rounds=3):
    """Run `work` a few times and return its result and the best time in ms."""
    best = None
    for _ in range(rounds):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1000
        best = elapsed if best is None else min(best, elapsed)
    return result, best


def benchmark(count):
    """Encode and decode the same journal as CBOR and as JSON, and time each leg.

    Best of three passes, because a single pass on a phone measures whatever
    else the scheduler was doing.

    Read the decode numbers together. json.loads on its own beats cbor2 and it
    is not a fair race: it has finished while cbor2 is still building datetimes,
    Decimals, UUIDs and byte strings. `json_typed` adds the rehydration that
    makes the two comparable. Both results are then checked against the original
    document with ==, so neither side wins by stopping early.

    string_referencing is measured too: it replaces every repeat of a string —
    here the eight field names, once per record — with a back reference. It is
    an extension to RFC 8949 rather than part of it, so use it only where the
    decoder is cbor2 as well.
    """
    document = build_document(count)

    blob, cbor_encode = _fastest(lambda: cbor2.dumps(document))
    decoded, cbor_decode = _fastest(lambda: cbor2.loads(blob))
    packed, _ = _fastest(lambda: cbor2.dumps(document, string_referencing=True))

    text, json_encode = _fastest(lambda: json.dumps(document, default=_json_ready))
    _, json_decode = _fastest(lambda: json.loads(text))
    restored, json_typed = _fastest(lambda: _rehydrate(json.loads(text)))

    return {
        "records": count,
        "cbor_bytes": len(blob),
        "packed_bytes": len(packed),
        "json_bytes": len(text.encode("utf-8")),
        "cbor_encode": cbor_encode,
        "cbor_decode": cbor_decode,
        "json_encode": json_encode,
        "json_decode": json_decode,
        "json_typed": json_typed,
        "cbor_identical": decoded == document,
        "json_identical": restored == document,
    }
