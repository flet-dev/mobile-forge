import base64
import hashlib
import os
import platform
import random
import time
import zlib

import google_crc32c

BLOB_NAME = "vault.bin"
MANIFEST_NAME = "vault.crc32c"
BLOB_SIZE = 8_000_000
CHUNK = 1_000_000
CHUNKS = BLOB_SIZE // CHUNK
BLOB_MB = BLOB_SIZE // 1_000_000
ROUNDS = 5
ENGINE = f"implementation {google_crc32c.implementation!r} on {platform.machine()}"

DIGESTS = (
    ("CRC32C (Castagnoli)", lambda b: f"{google_crc32c.value(b):08x}"),
    ("CRC-32 (zlib, IEEE)", lambda b: f"{zlib.crc32(b):08x}"),
    ("MD5", lambda b: hashlib.md5(b).hexdigest()[:8]),
    ("SHA-256", lambda b: hashlib.sha256(b).hexdigest()[:8]),
)


def _path(name):
    """Absolute path inside the durable per-app data directory."""
    return os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), name)


def stored():
    """True once a blob and its manifest exist on this device."""
    return os.path.exists(_path(BLOB_NAME)) and os.path.exists(_path(MANIFEST_NAME))


def scan():
    """Stream the blob once, returning per-chunk CRC32Cs, the whole-file CRC32C
    and the seconds spent.

    ``Checksum.consume`` is upstream's streaming helper: it reads a chunk, folds
    it into the running checksum and yields it, so a single pass produces both
    the whole-file value and the per-chunk list that later locates the damage.
    Chunking is not only about memory — the C extension never releases the GIL,
    so an un-chunked call freezes every other thread for its whole duration.
    """
    running = google_crc32c.Checksum()
    started = time.perf_counter()
    with open(_path(BLOB_NAME), "rb") as blob:
        chunks = [google_crc32c.value(chunk) for chunk in running.consume(blob, CHUNK)]
    whole = int.from_bytes(running.digest(), "big")
    return chunks, whole, time.perf_counter() - started


def store():
    """Write a fresh random blob and record one CRC32C per chunk beside it.

    The manifest is the point of the exercise: a whole-file checksum tells you
    that something is wrong, and a per-chunk manifest tells you where. Both are
    written from the same pass over the bytes that were just flushed to disk,
    not from the bytes still in memory, so the recorded value describes what the
    filesystem actually holds.
    """
    with open(_path(BLOB_NAME), "wb") as blob:
        for _ in range(CHUNKS):
            blob.write(os.urandom(CHUNK))
    chunks, whole, elapsed = scan()
    with open(_path(MANIFEST_NAME), "w") as manifest:
        manifest.write("\n".join(f"{value:08x}" for value in chunks))
    return whole, elapsed


def verify():
    """Re-checksum the blob and report which chunks no longer match the manifest.

    Returns the bad chunk indices, the whole-file CRC32C and the seconds spent.
    """
    with open(_path(MANIFEST_NAME)) as manifest:
        expected = [int(value, 16) for value in manifest.read().split()]
    chunks, whole, elapsed = scan()
    bad = [i for i, value in enumerate(chunks) if value != expected[i]]
    return bad, whole, elapsed


def damage():
    """Flip one bit at a random offset of the stored blob, in place.

    One bit in eight million bytes is the failure a checksum exists to catch: it
    survives a copy, a flaky download and a half-written file, and nothing else
    in the app will notice it. Returns the byte offset and the chunk it lands in.
    """
    offset = random.randrange(BLOB_SIZE)
    with open(_path(BLOB_NAME), "r+b") as blob:
        blob.seek(offset)
        byte = blob.read(1)[0]
        blob.seek(offset)
        blob.write(bytes([byte ^ (1 << random.randrange(8))]))
    return offset, offset // CHUNK


def compare():
    """Checksum the whole stored blob four ways and report a rate for each.

    CRC32C and zlib's CRC-32 are both 32-bit CRCs of the same shape, but they
    use different polynomials — Castagnoli's 0x1EDC6F41 against IEEE 802.3's
    0x04C11DB7 — so the two values never agree and a service that asks for one
    will reject the other. The digests below make that visible on identical
    bytes.

    Each rate is the best of ``ROUNDS`` timed passes after a warm-up one. That
    is not ceremony: eight megabytes goes through the fastest of these in well
    under a millisecond, and timing a single cold call gave readings that swung
    by a factor of three over the very same bytes. Best-of also means the first
    row is not penalised for being the one that pulls the file into cache.
    """
    with open(_path(BLOB_NAME), "rb") as blob:
        data = blob.read()
    rows = []
    for label, digest in DIGESTS:
        value = digest(data)
        best = min(_timed(digest, data) for _ in range(ROUNDS))
        rows.append((label, value, len(data) / 1e6 / best))
    return rows


def _timed(digest, data):
    """Seconds one digest pass takes over ``data``."""
    started = time.perf_counter()
    digest(data)
    return time.perf_counter() - started


def cloud_header(crc):
    """Render a CRC32C the way Google Cloud Storage carries it in x-goog-hash.

    Four bytes, most significant first, base64-encoded. Upstream's ``digest``
    docstring credits RFC 4960 for that order, but the RFC's own reference code
    byteswaps the value before it goes on the wire — big-endian here is Cloud
    Storage's convention, and it is what the header wants.
    """
    return "crc32c=" + base64.b64encode(crc.to_bytes(4, "big")).decode()
