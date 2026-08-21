import datetime as dt
import json
import os
import random
import threading
import time
from decimal import Decimal

import bson
import pymongo
from bson import Binary, Decimal128, Int64, ObjectId
from bson.codec_options import CodecOptions
from bson.errors import InvalidBSON

VERSION = (
    f"pymongo {pymongo.__version__} · "
    f"bson C extension {'on' if bson.has_c() else 'off'}"
)

# A BSON file is documents concatenated, nothing else -- so it belongs with the
# data the user expects to keep, not in the cache.
NAME = "readings.bson"
PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), NAME)

# BSON stores a datetime as a count of UTC milliseconds and no zone. Without
# tz_aware every timestamp comes back naive, and .astimezone() would then read
# it as local time and shift it.
OPTIONS = CodecOptions(tz_aware=True, tzinfo=dt.timezone.utc)

# Appending is one write() of one complete document. The lock keeps two of them
# from interleaving, which would tear a document in half; page.run_thread hands
# work to a pool, so two taps really can overlap.
_LOCK = threading.Lock()

SENSORS = ("kitchen", "balcony", "cellar", "attic")
SEED_COUNT = 5
BATCH = 1000


def reading():
    """Build one sensor document out of the BSON types json cannot carry.

    Every field here is a real BSON type rather than a string standing in for
    one: the id is 12 bytes, the temperature is an exact decimal, the sample
    count is a 64-bit integer, and the payload is raw binary.
    """
    return {
        "_id": ObjectId(),
        "sensor": random.choice(SENSORS),
        "when": dt.datetime.now(dt.timezone.utc),
        "celsius": Decimal128(Decimal(f"{random.uniform(17, 24):.2f}")),
        "samples": Int64(random.randint(2**33, 2**35)),
        "tags": ["indoor", "hourly"],
        "raw": Binary(random.randbytes(24), 0),
    }


def append(doc):
    """Append one encoded document to the store, and return the bytes written.

    Each document carries its own length prefix, so a file of them needs no
    header, no separator and no index -- appending is a single write. This is
    the layout `mongodump` produces, which is why a store written here can be
    read by anything that speaks BSON.
    """
    blob = bson.encode(doc)
    with _LOCK:
        with open(PATH, "ab") as handle:
            handle.write(blob)
    return len(blob)


def documents():
    """Read every stored document back, and say whether the file ended cleanly.

    `decode_file_iter` walks the file using those length prefixes instead of
    reading it whole, so memory tracks the largest document rather than the
    size of the store -- and a write cut short by a kill costs only its own
    document, because every earlier one has already been handed over. Reading
    the same bytes with `decode_all` would have raised before returning any.
    """
    docs = []
    with _LOCK:
        with open(PATH, "rb") as handle:
            try:
                for doc in bson.decode_file_iter(handle, codec_options=OPTIONS):
                    docs.append(doc)
            except InvalidBSON:
                return docs, False
    return docs, True


def seed():
    """Fill the store the first time the app runs, so there is something to show."""
    if not os.path.exists(PATH):
        for _ in range(SEED_COUNT):
            append(reading())


def size():
    """Bytes the store currently occupies on disk."""
    return os.path.getsize(PATH) if os.path.exists(PATH) else 0


def summary(docs, limit=6):
    """Format the most recent documents, newest first, for the list on screen.

    `when` arrives tz-aware because of OPTIONS, so `.astimezone()` can convert
    it for display; the stored value stays UTC milliseconds either way.
    """
    rows = []
    for doc in reversed(docs[-limit:]):
        rows.append(
            (
                str(doc["_id"])[-6:],
                doc["sensor"],
                f"{doc['celsius'].to_decimal():.2f} °C",
                doc["when"].astimezone().strftime("%H:%M:%S"),
            )
        )
    return rows


def fidelity():
    """Round-trip a document and report, field by field, what came back.

    The `same` column is the interesting one. A generic (subtype 0) Binary
    returns as plain `bytes`, and a datetime loses everything below the
    millisecond, so both come back usable but not identical.
    """
    doc = reading()
    back = bson.decode(bson.encode(doc), codec_options=OPTIONS)
    rows = []
    for field, value in doc.items():
        try:
            json.dumps({field: value})
            portable = "yes"
        except TypeError:
            portable = "no"
        rows.append(
            (
                field,
                type(value).__name__,
                type(back[field]).__name__,
                "yes" if back[field] == value else "no",
                portable,
            )
        )
    return rows


def throughput(count=BATCH):
    """Time a batch round trip, so the C accelerator has a number attached.

    The documents are built before the clock starts: this measures encoding
    and decoding, not `ObjectId()` and `random`.
    """
    docs = [reading() for _ in range(count)]

    started = time.perf_counter()
    blobs = [bson.encode(doc) for doc in docs]
    encoding = time.perf_counter() - started

    started = time.perf_counter()
    for blob in blobs:
        bson.decode(blob, codec_options=OPTIONS)
    decoding = time.perf_counter() - started

    total = sum(len(blob) for blob in blobs)
    return count, encoding / count * 1e6, decoding / count * 1e6, total / count
