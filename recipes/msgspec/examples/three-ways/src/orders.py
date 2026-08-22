"""Everything in this example that actually uses msgspec.

`main.py` owns the screen; this module owns the document, the three decoders and the
comparisons between them, and hands back plain values and preformatted lines for the
UI to print.
"""

import json
import platform
import time

import msgspec
import orjson

SIZES = (100, 250, 500, 1000, 2500, 5000)

PANEL_RECORDS = 8

BAD_INDEX = 3


class Order(msgspec.Struct):
    """One record of the document, and the schema every decode is checked against.

    A `Struct` rather than a dataclass for the two properties this app is about:
    msgspec decodes straight into it in a single pass, and the instance carries no
    `__dict__`, which is where the memory difference against a dict tree comes from.
    """

    id: int
    sku: str
    qty: int
    price: float
    note: str


class Report(msgspec.Struct):
    """One run's results: the table rows, and the three summary lines beneath them.

    Everything is already formatted, so the UI decides layout and nothing else. A
    `Struct` is used here as an ordinary return type — it is never encoded — to show
    that they work like any other class.
    """

    timings: tuple
    payload: str
    checks: str
    aborts: str


def make_document(records):
    """Build `records` order rows as plain dicts.

    Deterministic, so the same slider position produces the same bytes on every device
    and two phones can be compared directly. The keys are written in `Order`'s
    declaration order because the round-trip check below compares msgspec's re-encoded
    output byte-for-byte against orjson's, and msgspec emits struct fields in
    declaration order.
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

    Used both for the malformed-input panel and for the early-abort proof, so the
    broken document differs from the valid one in exactly one place and nothing else.
    """
    rows = make_document(records)
    rows[index][field] = value
    return msgspec.json.encode(rows)


def timed(work, reps):
    """Best of `reps` calls of `work` in ms, plus what the last call produced.

    `work` is expected to raise on the malformed documents this app feeds it, so the
    exception is caught and handed back as a value: a decode that gives up early is
    exactly what is being timed here, and letting it escape would take the worker
    thread with it.
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

    Both are rounded to the table's three decimals before dividing, because otherwise
    the ratio disagrees with the two columns it sits beside: 0.0295 ms against
    0.0110 ms prints as 0.029 and 0.011 but divides to 2.7x, where the printed pair
    gives 2.6x.
    """
    quick, slow = round(quick, 3), round(slow, 3)
    return f"{slow / quick:.1f}x" if quick else "n/a"


def plural(records):
    """`records` with a thousands separator and the right noun after it."""
    return f"{records:,} record{'' if records == 1 else 's'}"


def probe(work):
    """Run one codec call and report `ok`, or the exception type that stopped it.

    A real call rather than an import check, because the answer that matters — whether
    `msgspec.toml.decode` works with nothing but msgspec installed — depends on the
    stdlib `tomllib` being present in this runtime, which is a property of Flet's
    Python build rather than of the wheel.
    """
    try:
        work()
    except Exception as error:
        return type(error).__name__
    return "ok"


def native_origin():
    """Where the import system found `msgspec._core` on this device, as a short name.

    Read through `__file__` first and `__spec__.origin` second, because neither is
    dependable: Flet relocates native extensions out of site-packages, and which
    attribute survives varies by platform and by package.
    """
    module = msgspec._core
    origin = getattr(module, "__file__", None) or getattr(
        getattr(module, "__spec__", None), "origin", None
    )
    return origin.rsplit("/", 1)[-1] if origin else "unreported"


def runtime_line(platform_name):
    """The header line: versions, platform, and where the extension came from."""
    return (
        f"msgspec {msgspec.__version__} · Python {platform.python_version()} · "
        f"{platform_name} · native {native_origin()}"
    )


def codec_line():
    """All four shipped codecs, called on this device, as `ok` or an exception type.

    `toml decode` and `yaml decode` are the two worth reading: the first works with
    nothing installed beyond msgspec if this runtime has the stdlib `tomllib`, and the
    second is expected to report `ImportError` because this example does not depend on
    PyYAML.
    """
    json_ok = probe(lambda: msgspec.json.decode(msgspec.json.encode([1])))
    pack_ok = probe(lambda: msgspec.msgpack.decode(msgspec.msgpack.encode([1])))
    toml_ok = probe(lambda: msgspec.toml.decode(b"a = 1"))
    yaml_ok = probe(lambda: msgspec.yaml.decode(b"a: 1"))
    return (
        f"codecs: json {json_ok} · msgpack {pack_ok} · "
        f"toml decode {toml_ok} · yaml decode {yaml_ok}"
    )


def benchmark(records):
    """Decode the same bytes three ways, then show msgspec stopping where data goes bad.

    The three decoders are handed one identical `bytes` object, and the two
    cross-checks are what license comparing them at all. msgspec's re-encoded structs
    have to be byte-for-byte orjson's re-encoded dicts, or the columns are describing
    different documents; and the MessagePack bytes whose length the payload line calls
    smaller have to decode back to the same records through the same `Order`, or
    "smaller" would be satisfied by having lost something. The early-abort pair is the
    same document twice with the bad field moved from the front to the back, so the
    difference between the two figures is single-pass validation and nothing else.
    """
    reps = 30 if records > 1000 else 120
    document = make_document(records)
    blob = msgspec.json.encode(document)
    packed = msgspec.msgpack.encode(document)

    stdlib_ms, _ = timed(lambda: json.loads(blob), reps)
    orjson_ms, parsed = timed(lambda: orjson.loads(blob), reps)
    typed_ms, rows = timed(lambda: msgspec.json.decode(blob, type=list[Order]), reps)

    early = corrupt(records, 1, "qty", "NOPE")
    late = corrupt(records, records - 1, "qty", "NOPE")
    early_ms, stopped = timed(
        lambda: msgspec.json.decode(early, type=list[Order]), reps
    )
    late_ms, _ = timed(lambda: msgspec.json.decode(late, type=list[Order]), reps)

    unpacked = msgspec.msgpack.decode(packed, type=list[Order])
    same_bytes = msgspec.json.encode(rows) == orjson.dumps(parsed)
    saved = 100 * (len(blob) - len(packed)) // len(blob)
    return Report(
        timings=(
            ("decoder", "ms", "vs json", "checks"),
            ("json.loads", f"{stdlib_ms:,.3f}", "1.0x", "no"),
            ("orjson.loads", f"{orjson_ms:,.3f}", ratio(orjson_ms, stdlib_ms), "no"),
            ("msgspec type=", f"{typed_ms:,.3f}", ratio(typed_ms, stdlib_ms), "yes"),
        ),
        payload=(
            f"{plural(records)} · {len(blob):,} B as JSON · "
            f"{len(packed):,} B as msgpack ({saved}% smaller)"
        ),
        checks=(
            "round trip vs orjson: "
            + ("identical bytes" if same_bytes else "DIFFERENT BYTES")
            + " · msgpack through the same Order: "
            + ("same records" if unpacked == rows else "DIFFERENT RECORDS")
        ),
        aborts=(
            f"same document, bad field at record 1: {early_ms:,.3f} ms · "
            f"at record {records - 1:,}: {late_ms:,.3f} ms · "
            f"all valid: {typed_ms:,.3f} ms\n{stopped}"
        ),
    )


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


def malformed_report():
    """Three malformed documents, each with what all three libraries did with it.

    Two are rejections and the third is the trap: an unknown field is ignored by
    default, so the only visible sign is a value that is not there. Every call is made
    here, on the device, rather than described.
    """
    cases = (
        ('qty sent as "NOPE"', "qty", "NOPE"),
        ("price sent as null", "price", None),
        ('extra field "discount"', "discount", 5),
    )
    report = []
    for label, field, value in cases:
        payload = corrupt(PANEL_RECORDS, BAD_INDEX, field, value)
        report.append(
            (
                label,
                (
                    ("msgspec", typed_outcome(payload, field)),
                    ("orjson", untyped_outcome(orjson.loads, payload, field)),
                    ("json", untyped_outcome(json.loads, payload, field)),
                ),
            )
        )
    return report
