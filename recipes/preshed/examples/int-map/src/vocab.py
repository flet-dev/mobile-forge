import hashlib
import platform
import sys
import time
from collections import Counter
from dataclasses import dataclass

import preshed.about
from preshed.counter import PreshCounter
from preshed.maps import PreshMap

# a cell is C `struct { uint64_t key; void* value; }` — 16 bytes on every ABI Flet
# targets, armeabi-v7a included, where the key's 8-byte alignment pads the 4-byte
# pointer straight back. Not struct.calcsize("QP"): the struct module never pads
# the tail of a format, so on that ABI it answers 12.
CELL_BYTES = 16
SIZES = (25_000, 100_000, 200_000)
SYLLABLES = ("ba", "ke", "mi", "ro", "tu", "na", "shi", "lo", "vu", "za", "pe", "gi")
VERSION = f"preshed {preshed.about.__version__} · Python {platform.python_version()}"


@dataclass
class Report:
    """One run's measurements, plus the two live preshed tables it filled."""

    entries: int
    capacity: int
    map_bytes: int
    dict_bytes: int
    map_ns: float
    dict_ns: float
    presh_ms: float
    counter_ms: float
    occurrences: int
    collisions: int
    table: PreshMap
    counts: PreshCounter


def word(index):
    """Build token number `index` out of syllables, so every run sees the same corpus.

    Five syllables drawn from twelve give 12**5 = 248,832 distinct tokens; past
    that the words repeat and the collision count below stops measuring the hash.
    """
    out = ""
    for _ in range(5):
        out += SYLLABLES[index % len(SYLLABLES)]
        index //= len(SYLLABLES)
    return out


def key(text):
    """Fold text down to the uint64 that preshed's tables take as a key.

    A PreshMap stores the integer you hand it and never sees the string, so text
    has to be hashed on the way in. blake2b truncated to eight bytes is the
    portable way to do that from Python: the builtin `hash()` is salted per
    process, so the same word would land on a different key after a restart and
    any table written to disk would be worthless. Keys 0 and 1 are preshed's own
    empty and deleted markers — they store and read back, but `len()` does not
    count them — so the two values that would collide with them are nudged clear.
    """
    folded = int.from_bytes(
        hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big"
    )
    return folded if folded > 1 else folded + 2


def capacity_for(entries):
    """Smallest table that holds `entries` without a rehash.

    preshed doubles as soon as the table is three fifths full, allocating a fresh
    array each time — 8, 16, 32 ... 524,288 cells in turn. Filling 200,000 keys
    from the default size left the process 16.7 MB heavier on desktop, twice what
    the finished table needs; pre-sized, the same fill cost 8.4 MB.
    """
    size = 8
    while entries >= size * 3 // 5:
        size *= 2
    return size


def stream(keys, occurrences):
    """Two occurrences per token: one sweep of the whole vocabulary, one hot half.

    Half the stream visits every key exactly once in scattered order; the other
    half lands on the hottest 1%, so those keys end on 101 and the rest on 1.
    Counting a flat stream would be an unrealistically kind benchmark — real text
    is skewed, and a skewed stream keeps hammering the same few cells.
    """
    hot = max(1, len(keys) // 100)
    return [
        keys[(i // 2) % hot] if i % 2 else keys[(i // 2 * 7919) % len(keys)]
        for i in range(occurrences)
    ]


def dict_bytes(mapping):
    """Bytes a dict of int→int really costs: the table plus every boxed integer.

    This is the whole point of preshed. `sys.getsizeof` on the dict alone reports
    the open-addressing table, which is the smaller half; each key and each value
    is a separate heap-allocated `int` object next to it.
    """
    return (
        sys.getsizeof(mapping)
        + sum(sys.getsizeof(k) for k in mapping)
        + sum(sys.getsizeof(v) for v in mapping.values())
    )


def probe(table, keys):
    """Nanoseconds per successful lookup, averaged over one pass through `keys`."""
    started = time.perf_counter()
    for k in keys:
        table[k]
    return (time.perf_counter() - started) / len(keys) * 1e9


def build(entries):
    """Index the same `entries` tokens twice — PreshMap and dict — and measure both.

    Returns a Report: the two footprints, the per-lookup cost of each, and the time
    to tally the token stream with PreshCounter against collections.Counter. The
    honest result is that the dict wins the lookup — from Python both pay the same
    interpreter overhead on top, and dict's is the more tuned C lookup underneath.
    preshed wins on memory, and on `inc()`, which reads and writes a cell in one
    call where `tally[k] += 1` is two dict operations and a fresh int object.
    """
    keys = [key(word(i)) for i in range(entries)]

    table = PreshMap(initial_size=capacity_for(entries))
    for i, k in enumerate(keys):
        table[k] = i + 1

    plain = {k: i + 1 for i, k in enumerate(keys)}
    map_ns = probe(table, keys)
    plain_ns = probe(plain, keys)
    plain_bytes = dict_bytes(plain)
    del plain  # 23 MB at the largest size; drop it before the counters go up

    occurrences = entries * 2
    tokens = stream(keys, occurrences)

    counts = PreshCounter(initial_size=capacity_for(entries))
    started = time.perf_counter()
    for k in tokens:
        counts.inc(k, 1)
    presh_ms = (time.perf_counter() - started) * 1e3

    tally = Counter()
    started = time.perf_counter()
    for k in tokens:
        tally[k] += 1
    counter_ms = (time.perf_counter() - started) * 1e3

    return Report(
        entries=entries,
        capacity=table.capacity,
        map_bytes=table.capacity * CELL_BYTES,
        dict_bytes=plain_bytes,
        map_ns=map_ns,
        dict_ns=plain_ns,
        presh_ms=presh_ms,
        counter_ms=counter_ms,
        occurrences=occurrences,
        collisions=entries - len(set(keys)),
        table=table,
        counts=counts,
    )


def find(report, text):
    """Hash `text` and report what the map and the counter say about that key.

    Returns the 64-bit key, the 1-based position stored for it or None when the
    table has never seen it, and how often the stream hit it. Note the two
    different misses: PreshMap answers None for an absent key, PreshCounter
    answers 0, because a counter cannot tell "never seen" from "seen zero times".
    """
    digest = key(text)
    return digest, report.table[digest], report.counts[digest]
