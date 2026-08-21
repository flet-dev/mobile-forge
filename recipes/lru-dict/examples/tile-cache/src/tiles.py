import struct
import time
import zlib
from collections import OrderedDict
from functools import lru_cache

from lru import LRU

TILE = 80
GRID = 3
WORLD = 5
MAX_ITER = 80
CAPACITIES = (4, 9, 24)
ORIGIN = (-2.2, -1.5)
SPAN = 3.0
HEADLINE = f"{TILE}x{TILE} tiles, {GRID}x{GRID} of a {WORLD}x{WORLD} map on screen"


def _palette():
    """Build the escape-count to RGB table once, so rendering is a table lookup."""
    table = []
    for n in range(MAX_ITER + 1):
        if n == MAX_ITER:
            table.append(bytes((12, 12, 20)))
        else:
            t = n / MAX_ITER
            table.append(
                bytes((int(255 * t**0.4), int(190 * t**1.6), int(90 + 120 * t)))
            )
    return table


PALETTE = _palette()


def _png(rows):
    """Wrap 8-bit RGB scanlines as PNG bytes, which is what ft.Image.src takes directly.

    Written by hand out of zlib and struct so the example's only dependency is the
    package it is about. Colour type 2 is truecolour RGB; every scanline is prefixed
    with filter byte 0.
    """

    def chunk(tag, payload):
        """One PNG chunk: length, tag, payload, CRC of tag and payload."""
        body = tag + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + row for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", TILE, TILE, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def render_tile(zoom, tx, ty):
    """Render one Mandelbrot tile to PNG bytes. This is the cost a cache hit avoids.

    Pure-Python escape iteration, so a tile costs real milliseconds on a phone and a
    screenful costs nine times that. Any cache would do here; what matters is that the
    miss is expensive enough that the hit rate is the only number worth watching.
    """
    scale = SPAN / (WORLD * 2**zoom)
    step = scale / TILE
    left = ORIGIN[0] + tx * scale
    top = ORIGIN[1] + ty * scale
    rows = []
    for py in range(TILE):
        ci = top + py * step
        row = bytearray()
        for px in range(TILE):
            cr = left + px * step
            zr = zi = 0.0
            n = 0
            while n < MAX_ITER and zr * zr + zi * zi < 4.0:
                zr, zi = zr * zr - zi * zi + cr, 2.0 * zr * zi + ci
                n += 1
            row += PALETTE[n]
        rows.append(bytes(row))
    return _png(rows)


class TileCache:
    """A byte-accounted tile store on top of a fixed-size LRU.

    The LRU bounds the number of entries; the eviction callback is what turns that
    into a bound on bytes. It fires for a capacity eviction and for every entry
    dropped by set_size(), with the key and the value being discarded, which is
    enough to keep a running total exact for this workload — nothing here ever
    overwrites, pops or clears a key, and the callback does not fire for any of
    those. A cache that deletes entries has to adjust the total at the delete too.

    The callback runs inside the assignment that overflowed the cache, so it must be
    cheap and must not raise: lru-dict does not check the callback's result, and an
    exception raised here is left pending and surfaces at some unrelated later line.
    It must also not read the cache. It runs before the new entry is linked in, and
    keys(), values() and items() called from in there come back with holes that
    segfault on access; the key and value it is handed are the safe inputs.
    """

    def __init__(self, capacity):
        """Bind the callback at construction; set_callback() can change it later."""
        self.evictions = 0
        self.resident_bytes = 0
        self._store = LRU(capacity, callback=self._evicted)

    def _evicted(self, key, png):
        """Subtract an evicted tile from the byte total. Must not raise."""
        self.evictions += 1
        self.resident_bytes -= len(png)

    def fetch(self, key):
        """Return (png, was_hit), rendering the tile only when it is not resident.

        get() counts into get_stats() and refreshes recency, so the hit path is this
        one call. Membership tests do not refresh recency, which is why there is no
        `if key in store` here: it would leave every tile looking equally old.
        """
        png = self._store.get(key)
        if png is not None:
            return png, True
        png = render_tile(*key)
        self._store[key] = png
        self.resident_bytes += len(png)
        return png, False

    def resize(self, capacity):
        """Change the bound in place, evicting from the cold end to the new size."""
        self._store.set_size(capacity)

    def report(self, hits, elapsed):
        """Rows of (label, left, right) strings describing the frame just drawn.

        get_stats() is the LRU's own running (hits, misses), counted for get() and
        the subscript only. peek_last_item() is the least recently used entry — the
        one the next insert will drop — and peek_first_item() the most recent;
        neither counts as a use, and both return None while the cache is empty.
        """
        seen, missed = self._store.get_stats()
        total = seen + missed
        victim = self._store.peek_last_item()
        return [
            ("this frame", f"{hits}/{GRID * GRID} hits", f"{elapsed:.0f} ms"),
            (
                "hits / misses",
                f"{seen} / {missed}",
                f"{seen / total:.0%}" if total else "-",
            ),
            (
                "resident / capacity",
                f"{len(self._store)} / {self._store.get_size()}",
                f"{self.resident_bytes / 1000:.1f} KB",
            ),
            (
                "evicted",
                str(self.evictions),
                "next z{} {},{}".format(*victim[0]) if victim else "-",
            ),
        ]


def step(zoom, ox, oy, dx, dy, dz):
    """Pan or zoom the window, clamped to the map, returning the new (zoom, ox, oy).

    A zoom step doubles or halves the tile indices, so it normally lands on keys the
    cache has never seen. Not always: the halving is the exact inverse of the
    doubling, so zooming out and straight back in returns to the keys just left
    behind, and with capacity to spare for both levels that round trip is all hits.
    """
    new_zoom = max(0, zoom + dz)
    if new_zoom > zoom:
        ox, oy = 2 * ox + 1, 2 * oy + 1
    elif new_zoom < zoom:
        ox, oy = (ox - 1) // 2, (oy - 1) // 2
    edge = WORLD * 2**new_zoom - GRID
    return new_zoom, min(max(ox + dx, 0), edge), min(max(oy + dy, 0), edge)


def frame(cache, zoom, ox, oy):
    """Fetch the GRID x GRID tiles at this position; report hits and milliseconds.

    The fetch order is what makes the hit rate directional, and it surprised us. A
    pan shares six of the nine tiles whichever way it goes, but the loop runs from
    the top-left, so panning left or up asks for the new column or row first. At a
    capacity of exactly nine that first miss evicts the coldest entry — which is a
    tile this same loop is about to want — and the eviction cascades: the frame ends
    with nine misses and nothing kept. Panning right or down asks for the tiles it
    already has first, refreshing them ahead of the miss, and keeps six. Three
    entries of slack (capacity 24) make both directions keep six.
    """
    started = time.perf_counter()
    hits = 0
    rows = []
    for gy in range(GRID):
        row = []
        for gx in range(GRID):
            png, hit = cache.fetch((zoom, ox + gx, oy + gy))
            hits += hit
            row.append(png)
        rows.append(row)
    return rows, hits, (time.perf_counter() - started) * 1000


def _ns(work, ops):
    """Nanoseconds per operation, best of three, to blunt scheduler noise on a phone."""
    best = min(_once(work) for _ in range(3))
    return best / ops * 1e9


def _once(work):
    """Seconds taken by one pass of work."""
    started = time.perf_counter()
    work()
    return time.perf_counter() - started


def compare(ops=20000):
    """Time a hit and a miss through lru-dict, OrderedDict and functools.lru_cache.

    The whole reason to run this on the device rather than trust a desktop figure:
    all three are bounded LRU caches, and the interesting result is how little
    separates them. lru-dict does the recency update inside one C call, the
    OrderedDict recipe needs a second call to move_to_end, and lru_cache pays for a
    function call it then does not make. The third is the only one that cannot be
    handed a value produced elsewhere — which is why a tile cache is not written
    with it, whatever these numbers say.
    """
    keys = [f"tile:{i}" for i in range(256)]
    value = b"x" * 512
    hot = [keys[i % 256] for i in range(ops)]
    cold = [f"cold:{i}" for i in range(ops)]

    warm_lru = LRU(256)
    warm_od = OrderedDict()
    for key in keys:
        warm_lru[key] = value
        warm_od[key] = value

    @lru_cache(maxsize=256)
    def warm_wrapped(key):
        """Stand-in for an expensive pure function, primed below with every key."""
        return value

    @lru_cache(maxsize=256)
    def cold_wrapped(key):
        """The same function left unprimed, so the miss pass really misses."""
        return value

    for key in keys:
        warm_wrapped(key)

    def lru_hit():
        """A subscript on a full LRU; the C type reorders itself."""
        for key in hot:
            warm_lru[key]

    def od_hit():
        """The stdlib recipe: a lookup, then an explicit move_to_end."""
        touch = warm_od.move_to_end
        for key in hot:
            warm_od[key]
            touch(key)

    def wrapped_hit():
        """A hit through a decorated function, which is still a function call."""
        for key in hot:
            warm_wrapped(key)

    def lru_miss():
        """Insert past capacity, so every insert after the first 256 evicts."""
        store = LRU(256)
        for key in cold:
            store[key] = value

    def od_miss():
        """The same steady state with the eviction written out by hand."""
        store = OrderedDict()
        for key in cold:
            store[key] = value
            if len(store) > 256:
                store.popitem(last=False)

    def wrapped_miss():
        """Every key new, so lru_cache calls the function and then evicts."""
        for key in cold:
            cold_wrapped(key)

    return [
        ("lru-dict LRU", _ns(lru_hit, ops), _ns(lru_miss, ops)),
        ("OrderedDict", _ns(od_hit, ops), _ns(od_miss, ops)),
        ("functools.lru_cache", _ns(wrapped_hit, ops), _ns(wrapped_miss, ops)),
    ]
