import gc
import statistics
import time
import tracemalloc

from cymem.about import __version__
from cymem.cymem import Address, Pool

BLOCKS = {"64 B": 64, "512 B": 512, "4 KB": 4096}
REPEATS = 15
LABEL = f"cymem {__version__}"


def _pooled(count, block):
    """Hand `count` zero-filled blocks to one Pool, keeping our own list as well.

    This is the Python-reachable half of cymem. Pool.alloc is a cdef method that
    only Cython can call, so the blocks come from Address -- one Python object per
    block -- and own_pyref is what ties their lifetime to the Pool's.
    """
    pool = Pool()
    mine = []
    for _ in range(count):
        held = Address(block, 1)
        pool.own_pyref(held)
        mine.append(held)
    return pool, mine


def _plain(count, block):
    """The obvious alternative: `count` bytearrays in a list, each refcounted alone."""
    return None, [bytearray(block) for _ in range(count)]


def _timings(build, count, block):
    """Median microseconds to allocate one whole set and to release it again.

    gc.collect() runs between rounds but outside both timers. Neither structure
    is cyclic, so `del` alone gives back 99.9% of the bytes -- and a collect
    inside the release timer measured a whole-heap traversal that both strategies
    pay identically, which was enough to hide the difference underneath it.
    """
    allocated, released = [], []
    for _ in range(REPEATS):
        gc.collect()
        started = time.perf_counter()
        keep = build(count, block)
        allocated.append((time.perf_counter() - started) * 1e6)
        started = time.perf_counter()
        del keep
        released.append((time.perf_counter() - started) * 1e6)
    return statistics.median(allocated), statistics.median(released)


def _held_bytes(build, count, block):
    """Bytes still held at three moments: after allocating, after dropping half our
    own references, and after dropping the container itself.

    The middle number is the point of the whole app. A Pool frees its blocks when
    the Pool is collected, not when you let go of a block, so releasing half the
    Addresses gives back only the list slots -- while releasing half the bytearrays
    gives back half the memory. tracemalloc can see all of it because cymem
    allocates through PyMem_Malloc rather than plain malloc.
    """
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    pool, mine = build(count, block)
    full = tracemalloc.get_traced_memory()[0] - base
    del mine[::2]
    gc.collect()
    half = tracemalloc.get_traced_memory()[0] - base
    del pool, mine
    gc.collect()
    empty = tracemalloc.get_traced_memory()[0] - base
    tracemalloc.stop()
    return full, half, empty


def compare(count, block):
    """Measure both strategies at this size and return a dict of numbers for each.

    Timing and byte accounting are separate passes over the same builder: tracing
    hooks every allocation the interpreter makes and roughly doubles the timings
    it would otherwise be reporting.

    `per_block` is what each block costs beyond its payload -- the wrapper object,
    and the list slot pointing at it.
    """
    rows = []
    for name, build in (("Pool", _pooled), ("bytearray", _plain)):
        alloc_us, free_us = _timings(build, count, block)
        full, half, empty = _held_bytes(build, count, block)
        rows.append(
            {
                "name": name,
                "alloc_us": alloc_us,
                "free_us": free_us,
                "held": full,
                "half": half,
                "empty": empty,
                "per_block": (full - count * block) / count,
            }
        )
    return rows


def bookkeeping(count, block):
    """What a Pool filled from Python reports about itself.

    `size` and `addresses` are maintained by Pool.alloc, which Python cannot reach,
    so they stay at zero and empty however much memory the pool is really keeping
    alive. `refs` is the count that moves.
    """
    pool, _mine = _pooled(count, block)
    return {"size": pool.size, "addresses": len(pool.addresses), "refs": len(pool.refs)}
