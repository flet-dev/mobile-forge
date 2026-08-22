"""The Bloom filter itself: everything in this example that touches bitarray."""

import hashlib
import math
import platform
import struct
import sys
import time
import zlib

import bitarray
from bitarray.util import sc_encode, serialize, zeros

BITS = 1 << 16
SIDE = 256
ROWS = BITS // SIDE
PROBES = 50_000
MAX_HASHES = 8
KEY_COUNTS = (2_000, 5_000, 10_000, 20_000, 40_000)
VERSION = f"bitarray {bitarray.__version__} · Python {platform.python_version()}"


def member(index):
    """The key of member `index`."""
    return b"user-%07d" % index


def outsider(index):
    """The key of probe `index`, disjoint from every member key by construction."""
    return b"probe-%07d" % index


def positions(key, hashes):
    """The `hashes` bit positions `key` occupies, by Kirsch-Mitzenmacher double hashing.

    One SHA-256 digest supplies two 64-bit values, and position i is
    `(first + i * step) % BITS`; `step` is forced odd so that it stays coprime with a
    power-of-two BITS and the positions cannot collapse onto each other. SHA-256 rather
    than the builtin `hash()`, which is salted per process and would make the same key
    land somewhere else on every launch — the numbers this screen reports are meant to
    be identical on every device.
    """
    digest = hashlib.sha256(key).digest()
    first = int.from_bytes(digest[:8], "big")
    step = int.from_bytes(digest[8:16], "big") | 1
    return [(first + i * step) % BITS for i in range(hashes)]


def hash_count(keys):
    """How many hashes minimise the error rate for `keys` members, capped at MAX_HASHES.

    The cap is a practical limit rather than a theoretical one: at 2,000 keys the
    optimum is 23 hashes, and buying an error rate that far below what PROBES
    samples can resolve is 23 lookups nobody sees the benefit of.
    """
    return min(MAX_HASHES, max(1, round(BITS / keys * math.log(2))))


def build(keys, hashes):
    """Set every member's bits in a fresh filter, and time the whole insertion."""
    started = time.perf_counter()
    filt = zeros(BITS)
    for index in range(keys):
        for position in positions(member(index), hashes):
            filt[position] = 1
    return filt, time.perf_counter() - started


def false_positives(filt, hashes):
    """How many of PROBES non-members the filter wrongly accepts, and how long."""
    started = time.perf_counter()
    wrong = sum(
        1
        for index in range(PROBES)
        if all(filt[position] for position in positions(outsider(index), hashes))
    )
    return wrong, time.perf_counter() - started


def bitmap(filt, width):
    """`filt` as a 1-bit-per-pixel PNG whose pixel data is the filter's own buffer.

    PNG's bit-depth-1 greyscale format packs eight pixels into a byte, leftmost
    pixel in the most significant bit — which is exactly how a big-endian bitarray
    packs its bits. So a scanline is a slice of `filt.tobytes()` behind a zero
    filter byte, and no per-pixel conversion happens anywhere below. Set bits come
    out white.
    """
    stride = width // 8
    packed = filt.tobytes()
    height = len(packed) // stride
    rows = b"".join(
        b"\0" + packed[row * stride : (row + 1) * stride] for row in range(height)
    )

    def chunk(kind, payload):
        """One PNG chunk: length, type, payload, CRC-32 over type and payload."""
        body = kind + payload
        crc = struct.pack(">I", zlib.crc32(body))
        return struct.pack(">I", len(payload)) + body + crc

    header = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


def set_bytes(keys):
    """What the same membership question costs as a Python `set` of the member keys.

    The table and the key objects it points at are counted separately, because
    `sys.getsizeof` on a container reports only the container.
    """
    held = {member(index) for index in range(keys)}
    return sys.getsizeof(held) + sum(sys.getsizeof(key) for key in held)


def interval(rate, samples):
    """Half-width of the 95% interval on the count of `samples` draws at `rate`."""
    return 1.96 * math.sqrt(rate * (1 - rate) * samples)


def analyse(keys):
    """Build a filter for `keys` members, measure its error rate, and price it.

    Everything the screen shows is produced here, so a single call is one self-contained
    experiment: no state survives between passes and re-running the same slider position
    gives the same numbers. The filter itself stays in this module — the caller gets
    plain numbers and the finished PNG.
    """
    hashes = hash_count(keys)
    filt, build_seconds = build(keys, hashes)
    wrong, probe_seconds = false_positives(filt, hashes)

    started = time.perf_counter()
    image = bitmap(filt, SIDE)
    draw_seconds = time.perf_counter() - started

    set_bits = filt.count()
    fill = set_bits / BITS
    predicted = fill**hashes
    return {
        "keys": keys,
        "hashes": hashes,
        "image": image,
        "endian": filt.buffer_info().endian,
        "nbytes": filt.buffer_info().nbytes,
        "set_bits": set_bits,
        "fill": fill,
        "wrong": wrong,
        "measured": wrong / PROBES,
        "predicted": predicted,
        "expected": PROBES * predicted,
        "margin": interval(predicted, PROBES),
        "set_bytes": set_bytes(keys),
        "list_bytes": sys.getsizeof([False] * BITS),
        "serialized": len(serialize(filt)),
        "compressed": len(sc_encode(filt)),
        "build_ms": build_seconds * 1000,
        "probe_ms": probe_seconds * 1000,
        "draw_ms": draw_seconds * 1000,
    }
