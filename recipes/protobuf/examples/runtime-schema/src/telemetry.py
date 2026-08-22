import hashlib
import json
import os
import platform
import time

from google.protobuf import (
    descriptor,
    descriptor_pb2,
    descriptor_pool,
    message_factory,
    proto,
    unknown_fields,
)
from google.protobuf.internal import api_implementation

TYPE = descriptor_pb2.FieldDescriptorProto

SIZES = (500, 2000, 8000, 20000)

LOG_NAME = "readings.pb"

MAP_KEYS = 30

IMPLEMENTATION = api_implementation.Type()


def add_field(message_proto, name, number, field_type, type_name=None, repeated=False):
    """Append one field to a message being described, with proto3 implicit presence."""
    field = message_proto.field.add()
    field.name = name
    field.number = number
    field.type = field_type
    field.label = TYPE.LABEL_REPEATED if repeated else TYPE.LABEL_OPTIONAL
    if type_name:
        field.type_name = type_name
    return field


def build_schema():
    """Describe the whole schema in Python and compile it into one private DescriptorPool.

    This is the one route to a schema that needs no protoc on any machine: there is no
    `.proto` file in the project, no generated `_pb2.py` and no compiler anywhere. A
    `FileDescriptorProto` is itself just a protobuf message, and `DescriptorPool.Add`
    compiles it into real message classes.

    It runs once, at import, for two reasons that both fail silently if you get them wrong.
    Messages built from two different pools never compare equal — `==` compares descriptor
    identity, not content — so a per-call rebuild gives an app whose equality checks always
    return False. And `descriptor_pool.Default()` refuses a second file registered under a
    name it already holds, which is why this pool is a private one rather than the default.
    """
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "runtime_schema/demo.proto"
    file_proto.package = "demo"
    file_proto.syntax = "proto3"

    reading = file_proto.message_type.add()
    reading.name = "Reading"
    for name, number, field_type in (
        ("id", 1, TYPE.TYPE_INT32),
        ("sensor", 2, TYPE.TYPE_STRING),
        ("celsius", 3, TYPE.TYPE_DOUBLE),
        ("ts", 4, TYPE.TYPE_INT64),
        ("ok", 5, TYPE.TYPE_BOOL),
    ):
        add_field(reading, name, number, field_type)

    newer = file_proto.message_type.add()
    newer.CopyFrom(reading)
    newer.name = "ReadingNext"
    add_field(newer, "label", 9, TYPE.TYPE_STRING)

    batch = file_proto.message_type.add()
    batch.name = "Batch"
    add_field(batch, "items", 1, TYPE.TYPE_MESSAGE, ".demo.Reading", repeated=True)

    # A map field is repeated messages underneath; `map_entry` is what makes it a dict.
    entry = file_proto.message_type.add()
    entry.name = "CountsEntry"
    entry.options.map_entry = True
    add_field(entry, "key", 1, TYPE.TYPE_STRING)
    add_field(entry, "value", 2, TYPE.TYPE_INT32)

    tally = file_proto.message_type.add()
    tally.name = "Tally"
    add_field(tally, "counts", 1, TYPE.TYPE_MESSAGE, ".demo.CountsEntry", repeated=True)

    # `optional` in proto3 is sugar for a one-field oneof, and has to be spelled out here.
    presence = file_proto.message_type.add()
    presence.name = "Presence"
    add_field(presence, "plain", 1, TYPE.TYPE_INT32)
    presence.oneof_decl.add(name="_tracked")
    tracked = add_field(presence, "tracked", 2, TYPE.TYPE_INT32)
    tracked.proto3_optional = True
    tracked.oneof_index = 0

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return tuple(
        message_factory.GetMessageClass(pool.FindMessageTypeByName(f"demo.{name}"))
        for name in ("Reading", "ReadingNext", "Batch", "Tally", "Presence")
    )


Reading, ReadingNext, Batch, Tally, Presence = build_schema()


def header(device):
    """One line of the three facts that flip together when the C extension is missing.

    None of them is the same question as "does `google._upb._message` import": the
    implementation name, the descriptor flavour and the module that actually built the
    message classes are decided independently at import, and a screen quoting only the
    first could still be running the fallback's code.
    """
    return (
        f"C descriptors {descriptor._USE_C_DESCRIPTORS} · "
        f"messages built by {type(Reading).__module__} · "
        f"Python {platform.python_version()} · {device}"
    )


def make_rows(count):
    """Build `count` sensor readings as plain dicts.

    Deterministic, so one slider position produces the same bytes on every install and two
    devices can be compared directly — and so the JSON baseline is measured on exactly the
    same values protobuf gets.
    """
    return [
        {
            "id": index,
            "sensor": f"sensor-{index % 16:02d}",
            "celsius": round(-10.0 + (index % 500) / 8.0, 3),
            "ts": 1700000000 + index * 7,
            "ok": bool(index % 5),
        }
        for index in range(count)
    ]


def timed(work, reps):
    """Best of `reps` calls of `work`, in milliseconds, plus what the last call returned."""
    best, outcome = None, None
    for _ in range(reps):
        started = time.perf_counter()
        outcome = work()
        elapsed = (time.perf_counter() - started) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, outcome


def read_protobuf(blob):
    """Parse `blob` and fold every field of every record into one number.

    The fold is the honest half of the comparison. upb's parse does not build Python
    objects for the fields, so a parse-only timing measures almost nothing; the work moves
    to attribute access, and only a run that touches every field is comparable with what
    `json.loads` already did.
    """
    total = 0.0
    for item in Batch.FromString(blob).items:
        total += item.id + item.celsius + item.ts + len(item.sensor) + item.ok
    return total


def read_json(blob):
    """Parse `blob` and fold the same five fields of every record into one number."""
    total = 0.0
    for row in json.loads(blob):
        total += row["id"] + row["celsius"] + row["ts"] + len(row["sensor"]) + row["ok"]
    return total


def cross_check(parsed, source):
    """Compare a parsed Batch field by field against the rows it was built from."""
    if len(parsed.items) != len(source):
        return f"COUNT MISMATCH: {len(parsed.items)} vs {len(source)}"
    for item, row in zip(parsed.items, source):
        if (item.id, item.sensor, item.celsius, item.ts, item.ok) != (
            row["id"],
            row["sensor"],
            row["celsius"],
            row["ts"],
            row["ok"],
        ):
            return f"FIELD MISMATCH at id={row['id']}"
    return "every field equal"


def write_log(batch):
    """Write every record to app storage as a length-prefixed log, then read it back.

    `serialize_length_prefixed` is the only file-shaped API protobuf ships, and it is what
    makes a log splittable again: bare `SerializeToString` output has no framing, so two
    concatenated messages parse as one merged message rather than as two records.
    """
    path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), LOG_NAME)
    with open(path, "wb") as handle:
        for item in batch.items:
            proto.serialize_length_prefixed(item, handle)
    recovered = 0
    with open(path, "rb") as handle:
        while proto.parse_length_prefixed(Reading, handle) is not None:
            recovered += 1
    return os.path.getsize(path), recovered


def plural(count):
    """`count` with a thousands separator and the right noun after it."""
    return f"{count:,} reading{'' if count == 1 else 's'}"


def compare(label, protobuf_value, json_value, share=False):
    """One comparison row: protobuf's figure, json's, and the ratio between them.

    `share` picks which way the last column reads — a percentage for bytes, where smaller
    is the win, and a speedup for milliseconds.
    """
    if share:
        return (
            label,
            f"{protobuf_value:,}",
            f"{json_value:,}",
            f"{100 * protobuf_value / json_value:.0f}%",
        )
    return (
        label,
        f"{protobuf_value:,.3f}",
        f"{json_value:,.3f}",
        f"{json_value / protobuf_value:.1f}x" if protobuf_value else "n/a",
    )


def measure(count):
    """Serialise, parse and verify one batch against json on identical values.

    Returns the four comparison rows, a line of checks and a line about the on-disk log.

    Two independent checks license the table. The parsed messages are compared field by
    field against the rows they came from, and the parsed batch is re-serialised and its
    bytes compared with the original blob — a faster column would otherwise be
    indistinguishable from a column that decoded less. `ByteSize()` is a third, cheap one:
    it has to agree with the length of what `SerializeToString` produced. The two folds
    are compared as well, so the timing columns are proven to have read the same numbers.
    """
    reps = 5 if count > 4000 else 20
    rows = make_rows(count)
    batch = Batch(items=[Reading(**row) for row in rows])

    blob = batch.SerializeToString()
    json_blob = json.dumps(rows, separators=(",", ":")).encode()
    encode_ms, _ = timed(batch.SerializeToString, reps)
    json_encode_ms, _ = timed(
        lambda: json.dumps(rows, separators=(",", ":")).encode(), reps
    )
    parse_ms, parsed = timed(lambda: Batch.FromString(blob), reps)
    json_parse_ms, _ = timed(lambda: json.loads(json_blob), reps)
    read_ms, total = timed(lambda: read_protobuf(blob), reps)
    json_read_ms, json_total = timed(lambda: read_json(json_blob), reps)

    comparisons = (
        compare("bytes", len(blob), len(json_blob), share=True),
        compare("serialise ms", encode_ms, json_encode_ms),
        compare("parse ms", parse_ms, json_parse_ms),
        compare("parse + read ms", read_ms, json_read_ms),
    )
    log_ms, (log_bytes, recovered) = timed(lambda: write_log(batch), 1)
    checks = (
        f"{plural(count)} · {cross_check(parsed, rows)} · "
        f"re-serialised bytes "
        f"{'identical' if parsed.SerializeToString() == blob else 'DIFFERENT'} · "
        f"ByteSize {'agrees' if parsed.ByteSize() == len(blob) else 'DISAGREES'} · "
        f"folds {'match' if abs(total - json_total) < 1e-6 else 'DIFFER'}"
    )
    storage = (
        f"length-prefixed log: {recovered:,} of {count:,} records read back in "
        f"{log_ms:,.1f} ms, {log_bytes:,} B on disk against {len(blob):,} B as one "
        "Batch message"
    )
    return comparisons, checks, storage


def corrupt_cases(blob):
    """Three ways a message can arrive wrong, as label and bytes."""
    flipped = bytearray(blob)
    flipped[len(flipped) // 2] ^= 0xFF
    return (
        ("truncated to half", blob[: len(blob) // 2]),
        ("one byte flipped", bytes(flipped)),
        ("a JSON payload", b'{"id": 7, "sensor": "hello"}'),
    )


def parse_outcome(payload):
    """What a Reading makes of `payload`, as one line.

    Catches broad `Exception` rather than `DecodeError` for two reasons: an invalid UTF-8
    string field raises `UnicodeDecodeError` instead if this runtime ever falls back to the
    pure-Python implementation, and an unhandled exception in a Flet handler crashes the
    session. The "no error" branch is not dead code — protobuf's wire format is not
    self-describing enough to reject every blob.
    """
    try:
        Reading.FromString(payload)
    except Exception as error:
        return f"{type(error).__name__}"
    return "no error, parsed as a message"


def map_digests():
    """Hash one 30-entry map field serialised the default way and deterministically.

    Map fields have no defined order on the wire and upb picks one per process, so the left
    digest moves when the app is relaunched while the right one never does. Neither
    `PYTHONHASHSEED` nor re-encoding in the same process exposes it, which is exactly why
    hashing, signing or content-addressing a serialised message goes wrong so quietly.
    """
    tally = Tally()
    for index in range(MAP_KEYS):
        tally.counts[f"key-{index:02d}"] = index
    plain = hashlib.sha256(tally.SerializeToString()).hexdigest()[:16]
    fixed = hashlib.sha256(tally.SerializeToString(deterministic=True)).hexdigest()[:16]
    return plain, fixed


def schema_drift():
    """Send a record through a schema that has never heard of one of its fields.

    Field 9 exists only on `ReadingNext`. `Reading` parses the bytes without complaint,
    keeps what it could not name, and hands it back intact when the newer class reads its
    re-serialised output — which is what makes adding a field to a backend safe for the
    copies of your app already on people's phones.
    """
    blob = ReadingNext(
        id=1, sensor="sensor-00", label="from-the-future"
    ).SerializeToString()
    old = Reading.FromString(blob)
    kept = [
        (item.field_number, item.data) for item in unknown_fields.UnknownFieldSet(old)
    ]
    return kept, ReadingNext.FromString(old.SerializeToString()).label


def presence_line():
    """Bytes on the wire for a plain proto3 scalar set to 0 and an `optional` one set to 0."""
    tracked = Presence()
    tracked.tracked = 0
    return (
        f"plain=0 serialises to {Presence(plain=0).SerializeToString()!r} · "
        f"optional=0 serialises to {tracked.SerializeToString()!r}, "
        f"HasField {tracked.HasField('tracked')}"
    )


def probes():
    """Every question this device can answer without a timing run, as four values.

    The corrupt payloads come back as label/outcome pairs for a table; the rest are single
    lines. Each one is computed here rather than quoted, so a case that stopped being true
    on some platform or some protobuf release prints its new answer.
    """
    blob = Reading(id=7, sensor="sensor-07", celsius=21.5).SerializeToString()
    cases = tuple(
        (f"{label} ({len(payload)} B)", parse_outcome(payload))
        for label, payload in corrupt_cases(blob)
    )
    kept, recovered = schema_drift()
    drift = f"unknown fields kept: {kept} · recovered: {recovered!r}"
    plain, fixed = map_digests()
    digests = (
        f"{MAP_KEYS}-entry map · default sha256 {plain} · deterministic=True {fixed}\n"
        "map order is not guaranteed: under upb the left digest moves on every relaunch"
    )
    return cases, drift, digests, presence_line()
