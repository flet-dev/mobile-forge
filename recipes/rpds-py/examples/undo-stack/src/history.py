import importlib.metadata
import random
import sys
import time

from rpds import HashTrieMap

TITLE_KEY = "title"
EDIT_KEY = "last edit"
FIELDS = tuple(f"field_{i:04d}" for i in range(2000))
BURST = 25
# Snapshots built by each strategy when timing them. Fixed rather than tied to
# the history on screen, so the figures stay comparable however few edits have
# been made -- and because the losing side really does materialise this many
# copies of the whole document at once, about 12 MB of dict table at 2000 fields.
TIMED = 250
# Lookups timed per loop iteration; see _read_cost.
UNROLL = 10
SIZEOF_NOTE = (
    "getsizeof reports 56 bytes for any HashTrieMap: its entries are Rust "
    "allocations the interpreter cannot see."
)


def _version():
    """Report the installed rpds-py version.

    The `rpds` module carries no `__version__`, so the distribution metadata is
    the only place the number lives -- under the distribution name `rpds-py`,
    which is not the name of the module it installs.
    """
    try:
        return importlib.metadata.version("rpds-py")
    except importlib.metadata.PackageNotFoundError:
        return "?"


CAPTION = f"rpds-py {_version()} · HashTrieMap of {len(FIELDS) + 2} keys"


def new_document():
    """Build version one: a title, an edit note, and 2000 filler fields.

    The filler is what makes the comparison mean anything. A three-key document
    copies as cheaply as a dict; what a plain-dict snapshot costs is the whole
    table, so the document has to be big enough for a table to matter.
    """
    fields = {key: "unset" for key in FIELDS}
    return HashTrieMap({**fields, TITLE_KEY: "Untitled note", EDIT_KEY: "created"})


def retitle(doc, title):
    """Return a new version with a different title, leaving `doc` untouched."""
    return doc.insert(TITLE_KEY, title).insert(EDIT_KEY, f"title = {title!r}")


def random_edit(doc, number):
    """Return a new version with one randomly chosen field rewritten.

    Two chained inserts, so two maps are allocated and the intermediate one is
    dropped immediately -- and that is still the cheap path. An insert rebuilds
    only the nodes between the root and the changed leaf, one to three kilobytes
    whatever the document size, where a dict snapshot rebuilds every slot.
    """
    key = random.choice(FIELDS)
    value = f"revision {number}"
    return doc.insert(key, value).insert(EDIT_KEY, f"{key} = {value!r}")


def burst(doc, start):
    """Return BURST successive versions, one random field edit apart.

    Every version in between is kept, which is the point: the same run of edits
    kept as dict copies would materialise BURST complete tables.
    """
    versions = []
    for number in range(BURST):
        doc = random_edit(doc, start + number)
        versions.append(doc)
    return versions


def compare(doc, kept):
    """Build TIMED snapshots both ways on this device and report what each cost.

    Returns plain numbers: microseconds per snapshot each way, nanoseconds per
    key lookup each way, what `sys.getsizeof` says about each structure, and the
    table a dict history of `kept` versions would have to hold.

    That size row is the interesting one, and it is deliberately lopsided.
    `getsizeof` reports a dict's real table, but reports 56 bytes for a
    HashTrieMap holding two entries or two hundred thousand, because the entries
    live in Rust allocations the interpreter never sees -- an app cannot ask
    Python what its version history weighs. Measured by resident set size on a
    macOS desktop instead, 1000 versions of a 2000-key document held under 2 MB
    in total, against about 64 MB for the same history kept as dict copies.
    """
    plain = dict(doc)
    values = [f"snapshot {i}" for i in range(TIMED)]

    # Read costs first, while the heap is quiet. Measured after the snapshot
    # loops below they came out noisier from run to run, because those loops
    # leave megabytes of dict copies alive until this function returns.
    map_read = _read_cost(doc, TITLE_KEY)
    dict_read = _read_cost(plain, TITLE_KEY)

    # Both loops keep every snapshot alive, because a history allowed to fall
    # out of scope lets the allocator hand back the same block over and over,
    # which is not what either strategy costs in a real undo stack.
    started = time.perf_counter()
    version, versions = doc, []
    for index, value in enumerate(values):
        version = version.insert(FIELDS[index % len(FIELDS)], value)
        versions.append(version)
    persistent = (time.perf_counter() - started) / TIMED * 1e6

    started = time.perf_counter()
    copy, copies = plain, []
    for index, value in enumerate(values):
        copy = dict(copy)
        copy[FIELDS[index % len(FIELDS)]] = value
        copies.append(copy)
    copied = (time.perf_counter() - started) / TIMED * 1e6

    return {
        "kept": kept,
        "timed": TIMED,
        "persistent_us": persistent,
        "copy_us": copied,
        "map_read_ns": map_read,
        "dict_read_ns": dict_read,
        "map_sizeof": sys.getsizeof(doc),
        "dict_sizeof": sys.getsizeof(plain),
        "copied_bytes": sys.getsizeof(plain) * kept,
    }


def summarise(cost):
    """Turn what compare() measured into the rows of the table on screen.

    The units live next to the measurement rather than in the layout code. The
    last row is the one worth reading: what the history currently on screen
    would have weighed as dict copies, priced from the dict's own table size.
    """
    timed, fast, slow = cost["timed"], cost["persistent_us"], cost["copy_us"]
    return (
        ("", "HashTrieMap", "dict copies"),
        (
            f"{timed} snapshots",
            f"{fast * timed / 1000:.1f} ms",
            f"{slow * timed / 1000:.1f} ms",
        ),
        ("one snapshot", f"{fast:.1f} µs", f"{slow:.1f} µs"),
        (
            "one key lookup",
            f"{cost['map_read_ns']:.0f} ns",
            f"{cost['dict_read_ns']:.1f} ns",
        ),
        (
            "sys.getsizeof",
            f"{cost['map_sizeof']} B",
            f"{cost['dict_sizeof'] / 1024:.0f} KB",
        ),
        (
            f"{cost['kept']} versions kept",
            "one path each",
            f"{cost['copied_bytes'] / 1048576:.1f} MB of table",
        ),
    )


def _read_cost(mapping, key, rounds=100000, repeats=3):
    """Time one key lookup, in nanoseconds, on whatever device this is running on.

    The loop around the measurement is not free, and that is the whole
    difficulty. On a macOS desktop an empty `for _ in range(n)` pass costs about
    6 ns an iteration -- more than the dict lookup being measured -- so timing
    one lookup per iteration mostly times the loop. Subtracting a separately
    timed empty loop over-corrects, because the interpreter runs a bare loop
    faster than the same loop with a body: doing that priced a dict lookup at
    3 ns and made the map look 24 times dearer, against ten to fifteen by every
    other method tried. Repeating the subscript UNROLL times per iteration
    spreads the overhead over UNROLL lookups instead, which needs no correction
    and cannot go negative. It agrees with `timeit` on the map to within a few
    percent and reads below it on the dict, where `timeit`'s own one-lookup loop
    is still most of what it reports.
    """
    best = None
    for _ in range(repeats):
        started = time.perf_counter()
        for _ in range(rounds):
            mapping[key]
            mapping[key]
            mapping[key]
            mapping[key]
            mapping[key]
            mapping[key]
            mapping[key]
            mapping[key]
            mapping[key]
            mapping[key]
        elapsed = time.perf_counter() - started
        best = elapsed if best is None else min(best, elapsed)
    return best / (rounds * UNROLL) * 1e9
