"""Decode one document three ways on this device and show which one validates it."""

import json
import platform
import time

import flet as ft
import msgspec
import orjson

SIZES = (100, 250, 500, 1000, 2500, 5000)

TIMING_WEIGHTS = (6, 3, 3, 3)

PANEL_WEIGHTS = (3, 10)

PANEL_RECORDS = 8

BAD_INDEX = 3


class Order(msgspec.Struct):
    """One record of the generated document, and the schema every decode is checked against.

    A `Struct` rather than a dataclass for the two properties this app is about: msgspec
    decodes straight into it in a single pass, and the instance carries no `__dict__`, which
    is where the memory difference against a dict tree comes from.
    """

    id: int
    sku: str
    qty: int
    price: float
    note: str


def make_document(records):
    """Build `records` order rows as plain dicts.

    Deterministic, so the same slider position produces the same bytes on every device and
    two phones can be compared directly. The keys are written in `Order`'s declaration order
    because the round-trip check below compares msgspec's re-encoded output byte-for-byte
    against orjson's, and msgspec emits struct fields in declaration order.
    """
    return [
        {
            "id": index,
            "sku": f"SKU-{index:05d}",
            "qty": index % 9 + 1,
            "price": round(1.5 + (index % 400) / 8.0, 2),
            "note": "ok" if index % 5 else "backorder",
        }
        for index in range(records)
    ]


def corrupt(records, index, field, value):
    """The same document with one field of one record set to `value`, as JSON bytes.

    Used both for the malformed-input panel and for the early-abort proof, so the broken
    document differs from the valid one in exactly one place and nothing else.
    """
    rows = make_document(records)
    rows[index][field] = value
    return msgspec.json.encode(rows)


def timed(work, reps):
    """Best of `reps` calls of `work` in milliseconds, plus what the last call produced.

    `work` is expected to raise on the malformed documents this app feeds it, so the
    exception is caught and handed back as a value: a decode that gives up early is exactly
    what is being timed here, and letting it escape would take the worker thread with it.
    """
    best, outcome = None, None
    for _ in range(reps):
        started = time.perf_counter()
        try:
            outcome = work()
        except Exception as error:
            outcome = error
        elapsed = (time.perf_counter() - started) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, outcome


def ratio(quick, slow):
    """How many times faster `quick` is than `slow`, from the values the table prints.

    Both are rounded to the table's three decimals before dividing, because otherwise the
    ratio disagrees with the two columns it sits beside: 0.0295 ms against 0.0110 ms prints
    as 0.029 and 0.011 but divides to 2.7x, where the printed pair gives 2.6x.
    """
    quick, slow = round(quick, 3), round(slow, 3)
    return f"{slow / quick:.1f}x" if quick else "n/a"


def probe(work):
    """Run one codec call and report `ok`, or the exception type that stopped it.

    Four of these make up the second header line. They are real calls rather than an import
    check because the answer that matters — whether `msgspec.toml.decode` works with nothing
    but msgspec installed — depends on the stdlib `tomllib` being present in this runtime,
    which is a property of Flet's Python build rather than of the wheel.
    """
    try:
        work()
    except Exception as error:
        return type(error).__name__
    return "ok"


def native_origin():
    """Where the import system found `msgspec._core` on this device, as a short name.

    Read through `__file__` first and `__spec__.origin` second, because neither is
    dependable: Flet relocates native extensions out of site-packages, and which attribute
    survives varies by platform and by package.
    """
    module = msgspec._core
    origin = getattr(module, "__file__", None) or getattr(
        getattr(module, "__spec__", None), "origin", None
    )
    return origin.rsplit("/", 1)[-1] if origin else "unreported"


def typed_outcome(payload, field):
    """What a typed msgspec decode makes of the bad record's `field`, in one line."""
    try:
        rows = msgspec.json.decode(payload, type=list[Order])
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    if not hasattr(rows[BAD_INDEX], field):
        return "accepted, field silently dropped"
    value = getattr(rows[BAD_INDEX], field)
    return f"accepted, {field}={value!r} ({type(value).__name__})"


def untyped_outcome(loads, payload, field):
    """What a parse-only library makes of the bad record's `field`, in one line."""
    try:
        record = loads(payload)[BAD_INDEX]
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    if field not in record:
        return "parsed, field absent"
    value = record[field]
    return f"parsed, {field}={value!r} ({type(value).__name__})"


def malformed_cases():
    """The three malformed documents the panel walks, as label, field and payload.

    Two of them are rejections and the third is the trap: an unknown field is ignored by
    default, so the only visible sign is a value that is not there.
    """
    return (
        ('qty sent as "NOPE"', "qty", corrupt(PANEL_RECORDS, BAD_INDEX, "qty", "NOPE")),
        (
            "price sent as null",
            "price",
            corrupt(PANEL_RECORDS, BAD_INDEX, "price", None),
        ),
        (
            'extra field "discount"',
            "discount",
            corrupt(PANEL_RECORDS, BAD_INDEX, "discount", 5),
        ),
    )


def plural(records):
    """`records` with a thousands separator and the right noun after it."""
    return f"{records:,} record{'' if records == 1 else 's'}"


def table_row(values, weights, size=11):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Time three decoders on identical bytes, then show what each did with bad data.

    The timing table is only half the point. Two of the three decoders are parsing and
    nothing more, so the row that matters is the last column: msgspec is the only one that
    checked the document against a type, and it did so in the same pass. The panel
    underneath is the other half — the same three libraries on a document with one wrong
    field, where the two fast parsers hand back a wrong-typed value and say nothing.
    """

    def show_count():
        """Report the document size the next run will use, as the slider moves."""
        caption.value = f"{plural(SIZES[int(size.value)])} per document"

    def start():
        """Hand one run to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end, which fires once on release, so one gesture
        means one run. The guard is tested and set here rather than inside `run` because
        this body is synchronous where `run_thread` only schedules: a `disabled` set inside
        the worker would not have happened yet when this handler returns and Flet pushes the
        control states, so a second release would be accepted and two runs would rewrite the
        same table.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Decode the same bytes three ways, then prove msgspec stops where the data goes bad.

        The three decoders are handed one identical `bytes` object, and the two checks are
        what license comparing them at all. msgspec's re-encoded structs have to be
        byte-for-byte orjson's re-encoded dicts, or the columns are describing different
        documents; and the MessagePack bytes whose length the size line calls smaller have
        to decode back to the same records through the same `Order`, or "smaller" would be
        satisfied by having lost something. The early-abort pair is the same document twice
        with the bad field moved from the front to the back, so the difference between the
        two figures is single-pass validation and nothing else.

        The try/except is load-bearing: `page.run_thread` discards whatever a worker raises,
        so a mistake in here would look like a screen that quietly stopped updating. It
        clears the table on the way out, because timings left over from the previous run
        read as though they described the error.
        """
        try:
            records = SIZES[int(size.value)]
            reps = 30 if records > 1000 else 120
            document = make_document(records)
            blob = msgspec.json.encode(document)
            packed = msgspec.msgpack.encode(document)

            stdlib_ms, _ = timed(lambda: json.loads(blob), reps)
            orjson_ms, parsed = timed(lambda: orjson.loads(blob), reps)
            typed_ms, rows = timed(
                lambda: msgspec.json.decode(blob, type=list[Order]), reps
            )

            early = corrupt(records, 1, "qty", "NOPE")
            late = corrupt(records, records - 1, "qty", "NOPE")
            early_ms, stopped = timed(
                lambda: msgspec.json.decode(early, type=list[Order]), reps
            )
            late_ms, _ = timed(
                lambda: msgspec.json.decode(late, type=list[Order]), reps
            )

            timings.controls = [
                table_row(("decoder", "ms", "vs json", "checks"), TIMING_WEIGHTS),
                ft.Divider(height=1),
                table_row(
                    ("json.loads", f"{stdlib_ms:,.3f}", "1.0x", "no"), TIMING_WEIGHTS
                ),
                table_row(
                    (
                        "orjson.loads",
                        f"{orjson_ms:,.3f}",
                        ratio(orjson_ms, stdlib_ms),
                        "no",
                    ),
                    TIMING_WEIGHTS,
                ),
                table_row(
                    (
                        "msgspec type=",
                        f"{typed_ms:,.3f}",
                        ratio(typed_ms, stdlib_ms),
                        "yes",
                    ),
                    TIMING_WEIGHTS,
                ),
            ]
            payload_line.value = (
                f"{plural(records)} · {len(blob):,} B as JSON · "
                f"{len(packed):,} B as msgpack "
                f"({100 * (len(blob) - len(packed)) // len(blob)}% smaller)"
            )
            unpacked = msgspec.msgpack.decode(packed, type=list[Order])
            checks.value = (
                "round trip vs orjson: "
                + (
                    "identical bytes"
                    if msgspec.json.encode(rows) == orjson.dumps(parsed)
                    else "DIFFERENT BYTES"
                )
                + " · msgpack through the same Order: "
                + ("same records" if unpacked == rows else "DIFFERENT RECORDS")
            )
            aborts.value = (
                f"same document, bad field at record 1: {early_ms:,.3f} ms · "
                f"at record {records - 1:,}: {late_ms:,.3f} ms · "
                f"all valid: {typed_ms:,.3f} ms\n{stopped}"
            )
        except Exception as error:
            timings.controls = []
            payload_line.value = ""
            checks.value = ""
            aborts.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def fill_panel():
        """Build the malformed-input panel by making every call on this device."""
        panel.controls = []
        for label, field, payload in malformed_cases():
            panel.controls.append(ft.Text(label, size=11, weight=ft.FontWeight.BOLD))
            panel.controls.append(
                table_row(("msgspec", typed_outcome(payload, field)), PANEL_WEIGHTS, 10)
            )
            panel.controls.append(
                table_row(
                    ("orjson", untyped_outcome(orjson.loads, payload, field)),
                    PANEL_WEIGHTS,
                    10,
                )
            )
            panel.controls.append(
                table_row(
                    ("json", untyped_outcome(json.loads, payload, field)),
                    PANEL_WEIGHTS,
                    10,
                )
            )

    page.appbar = ft.AppBar(title=ft.Text("msgspec three ways"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"msgspec {msgspec.__version__} · "
                        f"Python {platform.python_version()} · {page.platform.value} · "
                        f"native {native_origin()}",
                        size=11,
                    ),
                    ft.Text(
                        "codecs: json "
                        f"{probe(lambda: msgspec.json.decode(msgspec.json.encode([1])))}"
                        " · msgpack "
                        f"{probe(lambda: msgspec.msgpack.decode(msgspec.msgpack.encode([1])))}"
                        f" · toml decode {probe(lambda: msgspec.toml.decode(b'a = 1'))}"
                        f" · yaml decode {probe(lambda: msgspec.yaml.decode(b'a: 1'))}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=0,
                        max=len(SIZES) - 1,
                        value=3,
                        divisions=len(SIZES) - 1,
                        on_change=show_count,
                        on_change_end=start,
                    ),
                    timings := ft.Column(spacing=4),
                    payload_line := ft.Text(size=11),
                    checks := ft.Text(size=11),
                    aborts := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("one record sent wrong, three libraries", size=11),
                    panel := ft.Column(spacing=2),
                ],
            ),
        )
    )

    show_count()
    fill_panel()
    start()


if __name__ == "__main__":
    ft.run(main)
