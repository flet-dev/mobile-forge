"""Four UUID schemes judged as database keys: cost, order, embedded time, range scan."""

import datetime
import importlib
import platform
import sys
import time
import uuid

import flet as ft

try:
    import uuid_utils
except Exception as error:  # the wheel may be missing or fail to load
    uuid_utils = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

SCHEMES = ("v4", "v7", "v6", "v1")

BATCH = 20_000

REPS = 3

# 100-nanosecond ticks between the UUID epoch (1582-10-15) and the Unix epoch.
GREGORIAN_TICKS = 0x01B21DD213814000

# A v1 timestamp's low word covers 2**32 ticks, so its text order restarts this often.
WRAP_SECONDS = 2**32 / 1e7

# The variant bits and an all-zero node, so a constructed id is legal but
# obviously made up.
DUMMY_TAIL = 0x8000_0000_0000_0000

RATE_WEIGHTS = (5, 4, 5)

SAMPLE_ROWS = 3


def rust_generator(scheme):
    """uuid-utils' generator for `scheme`, or None when the wheel did not load."""
    if uuid_utils is None:
        return None
    return getattr(uuid_utils, "uuid" + scheme[1:], None)


def stdlib_generator(scheme):
    """The stdlib generator for `scheme`.

    Returns None for v6 and v7 before CPython 3.14, which is where `uuid.uuid6`,
    `uuid.uuid7` and `uuid.uuid8` were added — on 3.12 and 3.13 the package is the
    only way to get those versions at all.
    """
    return getattr(uuid, "uuid" + scheme[1:], None)


def ns_per_id(make, count=BATCH, reps=REPS):
    """Best-of-`reps` cost of one id in nanoseconds, plus the last batch made.

    The loop that collects the ids is timed along with the generator, because that
    is the shape real code has. It costs the fast implementation proportionally
    more than the slow one, so the ratio this produces understates the package
    rather than flattering it.
    """
    best, ids = None, None
    for _ in range(reps):
        started = time.perf_counter()
        ids = [make() for _ in range(count)]
        elapsed = time.perf_counter() - started
        best = elapsed if best is None else min(best, elapsed)
    return best / count * 1e9, ids


def unix_millis(one, scheme):
    """The timestamp an id carries, in Unix milliseconds, or None for v4.

    v7 stores Unix milliseconds directly. v1 and v6 store 100-nanosecond ticks
    counted from 1582-10-15, which is what the subtraction converts. Both UUID
    classes expose the raw field as `.time` with the same meaning, so this works
    whichever implementation produced the id.
    """
    if scheme == "v4":
        return None
    if scheme == "v7":
        return one.time
    return (one.time - GREGORIAN_TICKS) // 10_000


def disorder(ids):
    """How many adjacent pairs come out of order when the batch is read as text.

    Text is the comparison that matters: a key column in SQLite, a file name and a
    sorted key range in a document store are all compared as strings rather than
    as 128-bit integers.
    """
    text = [str(one) for one in ids]
    return sum(1 for first, second in zip(text, text[1:]) if second <= first)


def occupancy(ids, scheme):
    """(distinct milliseconds, busiest millisecond) over the batch, or None for v4."""
    if scheme == "v4":
        return None
    counts = {}
    for one in ids:
        stamp = unix_millis(one, scheme)
        counts[stamp] = counts.get(stamp, 0) + 1
    return len(counts), max(counts.values())


def id_text(value):
    """A 128-bit integer in canonical 8-4-4-4-12 hyphenated form.

    Written out here rather than through a UUID class so that the constructed ids
    below still work when the wheel is missing, and so it is visible that a bound
    is arithmetic on the timestamp field and nothing else.
    """
    digits = f"{value:032x}"
    return "-".join(
        (digits[:8], digits[8:12], digits[12:16], digits[16:20], digits[20:])
    )


def v1_text(ticks):
    """The id a v1 generator would produce at `ticks`, as text.

    v1 writes the *low* 32 bits of its 60-bit timestamp first, then the middle 16,
    then the high 12 beside the version nibble. Laying that out by hand is the
    clearest way to show why the text order is not the time order.
    """
    low = ticks & 0xFFFFFFFF
    mid = (ticks >> 32) & 0xFFFF
    high = ((ticks >> 48) & 0x0FFF) | 0x1000
    return id_text((low << 96) | (mid << 80) | (high << 64) | DUMMY_TAIL)


def v6_text(ticks):
    """The id a v6 generator would produce at `ticks`, as text.

    Same timestamp as v1, same length, same everything — with the three words
    written most significant first. That reordering is the entire content of the
    v6 specification.
    """
    high = (ticks >> 28) & 0xFFFFFFFF
    mid = (ticks >> 12) & 0xFFFF
    low = 0x6000 | (ticks & 0x0FFF)
    return id_text((high << 96) | (mid << 80) | (low << 64) | DUMMY_TAIL)


def wrap_pair(gap_ticks=200_000):
    """Two instants `gap_ticks` apart that straddle a v1 low-word wrap.

    Nothing is generated here: the pair is chosen so that the earlier instant sits
    just below the point where the low 32 bits of the timestamp roll over, which
    happens every 429.5 seconds on any device. Whether the later id still sorts
    later is then a fact about the layout rather than about this machine.
    """
    now = int(time.time() * 1e7) + GREGORIAN_TICKS
    before = (now | 0xFFFFFFFF) - gap_ticks // 2
    return before, before + gap_ticks


def window_bounds(low_ms, high_ms):
    """The two ids that bracket a v7 millisecond window, inclusive, as text.

    A v7 id is a 48-bit Unix-millisecond timestamp followed by 80 bits of version,
    variant and randomness. So the smallest id that can exist in a millisecond is
    that millisecond shifted left by 80 bits, and the largest is one below the next
    millisecond's floor. Every id in the window sorts between them under plain text
    comparison, which is the whole argument for a v7 primary key.
    """
    return id_text(low_ms << 80), id_text(((high_ms + 1) << 80) - 1)


def range_scan(ids):
    """Count the ids in the middle third of the batch's span, two ways.

    One count compares id strings against a pair of computed bounds, the way a
    `WHERE id BETWEEN ? AND ?` would; the other decodes every timestamp and
    compares numbers. The two agree only if the key really is ordered by time, so
    this puts the claim and its check on one line.
    """
    stamps = [one.time for one in ids]
    low, high = min(stamps), max(stamps)
    span = high - low
    start, end = low + span // 3, high - span // 3
    low_text, high_text = window_bounds(start, end)
    by_text = sum(1 for one in ids if low_text <= str(one) <= high_text)
    by_time = sum(1 for stamp in stamps if start <= stamp <= end)
    return end - start + 1, by_text, by_time


def key_line(ids, scheme):
    """What this scheme's layout is worth to a key column, checked on this device."""
    if scheme == "v7":
        span, by_text, by_time = range_scan(ids)
        agree = "agree" if by_text == by_time else "DISAGREE"
        return (
            f"middle {span:,} ms by text compare: {by_text:,} ids, by decoded "
            f"timestamp: {by_time:,} — they {agree}"
        )
    if scheme == "v4":
        return (
            "no prefix to scan: 122 random bits scatter inserts across the whole index"
        )
    before, after = wrap_pair()
    if scheme == "v1":
        kept = v1_text(before) < v1_text(after)
        return (
            f"20 ms apart across a low-word wrap, the later id still sorts later: "
            f"{kept} — v1 restarts its text order every {WRAP_SECONDS:,.1f} s"
        )
    kept = v6_text(before) < v6_text(after)
    return (
        f"the same two instants in v6 keep their order: {kept} — but the prefix is "
        f"Gregorian ticks, so a Unix window needs converting first"
    )


def order_line(ids, scheme):
    """Whether the batch came out already sorted, and what decides it if not."""
    out = disorder(ids)
    pairs = len(ids) - 1
    if out == 0:
        return (
            f"as a key column: sorted as generated · 0 of {pairs:,} adjacent "
            f"pairs out of order"
        )
    if scheme == "v4":
        return (
            f"as a key column: unordered · {out:,} of {pairs:,} adjacent pairs "
            f"out of order"
        )
    return (
        f"as a key column: nearly sorted · {out:,} of {pairs:,} pairs out of "
        f"order — inside one 100-ns tick the order is the 14-bit clock "
        f"sequence, and it wraps"
    )


def stamp_line(ids, scheme):
    """What instant the first id carries, and how densely the batch packed."""
    millis = unix_millis(ids[0], scheme)
    if millis is None:
        return "carries no timestamp: a v4 id is 122 random bits and nothing else"
    drift = time.time() * 1000.0 - millis
    distinct, busiest = occupancy(ids, scheme)
    return (
        f"first id says {utc_text(millis)} ({drift:,.0f} ms ago) · "
        f"{distinct:,} distinct ms · {busiest:,} in the busiest one"
    )


def node_kind(node):
    """`random` when the multicast bit marks a stand-in, `MAC` when it does not.

    RFC 9562 requires the low bit of the first octet to be set on a node id that
    was invented rather than read off a network interface, so that one bit says
    which of the two happened.
    """
    return "random" if node & (1 << 40) else "MAC"


def node_identity():
    """Both `getnode()` implementations, with what each found and what it cost.

    Only v1 and v6 consult it, and the first call is the expensive one: the stdlib
    may shell out to `ip` and `ifconfig` before giving up. Both implementations
    cache the answer for the life of the process, so a second call is free and the
    milliseconds below are only meaningful on the first run.
    """
    started = time.perf_counter()
    try:
        node = uuid.getnode()
    except Exception as error:  # every getter in the chain is allowed to fail
        parts = [f"uuid.getnode() raised {type(error).__name__}"]
    else:
        cost = (time.perf_counter() - started) * 1000.0
        parts = [f"uuid {node:012x} {node_kind(node)} in {cost:,.1f} ms"]
    if uuid_utils is not None:
        started = time.perf_counter()
        node = uuid_utils.getnode()
        cost = (time.perf_counter() - started) * 1000.0
        parts.append(f"uuid_utils {node:012x} {node_kind(node)} in {cost:,.1f} ms")
    return "node · " + " · ".join(parts)


def interop():
    """Whether a uuid-utils id equals a stdlib id built from the same text.

    It does not, and the mismatch is the awkward shape: the two classes hash alike
    but compare unequal, so both go into one dict as two separate keys sharing a
    bucket. `uuid_utils.compat` is the way out — its functions return real
    `uuid.UUID` objects.
    """
    if uuid_utils is None:
        return "interop · uuid_utils absent"
    text = "018f0000-0000-7000-8000-000000000000"
    mine, theirs = uuid_utils.UUID(text), uuid.UUID(text)
    both = {mine: "rust", theirs: "stdlib"}
    compat = importlib.import_module("uuid_utils.compat")
    return (
        f"interop · same text, equal? {mine == theirs} · same hash? "
        f"{hash(mine) == hash(theirs)} · dict keys? {len(both)} · "
        f"compat.uuid7() is uuid.UUID? {isinstance(compat.uuid7(), uuid.UUID)}"
    )


def runtime():
    """Python, platform, and the state of the stdlib's optional `_uuid` helper.

    Worth showing because it differs between the two targets: Flet's Android
    runtime ships no `_uuid` and its iOS runtime does, which decides whether
    `uuid.uuid1()` runs in C or in Python. uuid-utils is Rust and needs neither,
    so its own row in the table should not move between the platforms.
    """
    try:
        importlib.import_module("_uuid")
    except Exception:
        helper = "no _uuid"
    else:
        helper = "_uuid present"
    path = "C" if getattr(uuid, "_generate_time_safe", None) else "Python"
    return (
        f"Python {platform.python_version()} · {sys.platform} · stdlib "
        f"{helper}, uuid1() runs in {path}"
    )


def implementation():
    """Which uuid-utils is loaded, or what stopped it."""
    if uuid_utils is None:
        return f"uuid_utils absent · {IMPORT_ERROR}"
    return f"uuid_utils {uuid_utils.__version__} · Rust extension"


def utc_text(millis):
    """A Unix-millisecond timestamp as a readable UTC instant."""
    when = datetime.datetime.fromtimestamp(millis / 1000.0, datetime.timezone.utc)
    return when.strftime("%Y-%m-%d %H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def rate_rows(scheme):
    """One row per available implementation: source, nanoseconds, ids per second.

    A batch comes back with the rows, because every other panel is computed from
    real ids rather than from a claim about them. It is uuid-utils' batch when the
    wheel loaded and the stdlib's otherwise, so the screen still says something
    useful when the wheel is missing.
    """
    rows, ids = [], None
    for label, make in (
        ("uuid-utils", rust_generator(scheme)),
        ("stdlib uuid", stdlib_generator(scheme)),
    ):
        if make is None:
            rows.append((label, "-", "unavailable here"))
            continue
        nanos, made = ns_per_id(make)
        rows.append((label, f"{nanos:,.0f}", f"{1e9 / nanos:,.0f}"))
        if ids is None:
            ids = made
    return rows, ids


def table_row(values, weights, size=11):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def sample_row(text):
    """One id in a monospace face, so a shared prefix lines up down the column."""
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def main(page: ft.Page):
    """Generate a batch under the chosen scheme and report what kind of key it is.

    Four questions, all answered from ids made on this device: what one id costs,
    whether the batch comes out already sorted, what instant an id carries, and
    whether a time window can be selected by comparing key text alone. The import
    is guarded, so a missing wheel falls back to the stdlib columns rather than
    ending the session.
    """
    shown = SCHEMES[0]  # the scheme the tables currently describe

    def start():
        """Send one scheme to the thread pool and lock the picker meanwhile.

        The guard is set here rather than in the worker because `run_thread` only
        schedules: a `disabled` set inside the worker would not have reached the
        client before a second tap could start an overlapping run. A tap that beats
        it is dropped and the picker is put back to the scheme being measured,
        because the client moves its own highlight the instant it is tapped.
        """
        nonlocal shown
        if picker.disabled:
            picker.selected = [shown]
            page.update()
            return
        shown = picker.selected[0]
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run, shown)

    def run(scheme):
        """Measure one scheme, then describe the batch it produced.

        The scheme is passed in rather than read off the picker, because the worker
        starts after the handler has returned and a tap landing in between would
        move `picker.selected` out from under it.

        Wrapped in try/except because `page.run_thread` discards whatever a worker
        raises — without this a failure would look like a screen that quietly
        stopped updating. The panels are cleared on the error path so that numbers
        from the previous scheme cannot be read as describing this one.
        """
        try:
            rows, ids = rate_rows(scheme)
            rates.controls = [
                table_row(("source", "ns / id", "ids / second"), RATE_WEIGHTS),
                ft.Divider(height=1),
                *(table_row(row, RATE_WEIGHTS) for row in rows),
            ]
            if ids is None:
                summary.value = f"{scheme} · nothing on this runtime generates it"
                ordering.value = stamps.value = window.value = ""
                samples.controls = []
            else:
                distinct = len({str(one) for one in ids})
                summary.value = f"{scheme} · {len(ids):,} ids · {distinct:,} distinct"
                ordering.value = order_line(ids, scheme)
                stamps.value = stamp_line(ids, scheme)
                window.value = key_line(ids, scheme)
                samples.controls = [sample_row(str(one)) for one in ids[:SAMPLE_ROWS]]
                samples.controls.append(sample_row(f"… {ids[-1]}"))
            nodes.value = node_identity()
        except Exception as error:  # the worker must never let one escape
            rates.controls = []
            samples.controls = []
            ordering.value = stamps.value = window.value = nodes.value = ""
            summary.value = f"{type(error).__name__}: {error}"

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("uuid-utils id generator"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        implementation(),
                        size=11,
                        color=ft.Colors.ERROR if uuid_utils is None else None,
                    ),
                    ft.Text(runtime(), size=11),
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                segments=[
                                    ft.Segment(value=name, label=ft.Text(name))
                                    for name in SCHEMES
                                ],
                                selected=[SCHEMES[0]],  # a set is not serialisable
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    rates := ft.Column(spacing=4),
                    summary := ft.Text(size=11),
                    ordering := ft.Text(size=11),
                    ft.Divider(),
                    samples := ft.Column(spacing=2),
                    stamps := ft.Text(size=11),
                    window := ft.Text(size=11),
                    ft.Divider(),
                    nodes := ft.Text(size=11),
                    ft.Text(interop(), size=11),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
