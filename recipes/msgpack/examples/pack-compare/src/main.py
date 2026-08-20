"""Put msgpack next to json on the same objects: size, time and type fidelity."""

import base64
import datetime
import json
import math
import platform
import random
import sys
import time

import flet as ft

try:
    import msgpack
except Exception as error:  # the wheel may be missing or fail to load
    msgpack = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

PAYLOADS = ("api records", "sensor grid", "photo blobs")

SIZE_WEIGHTS = (4, 4, 3, 4, 4)

FIDELITY_WEIGHTS = (6, 5, 5)

CONVERSION_WEIGHTS = (7, 5)

FLIPS = 120

SEED = 20260820

STAMP = datetime.datetime(2026, 8, 20, 12, 34, 56, 789012, tzinfo=datetime.timezone.utc)


def api_records(count=2000):
    """A paged API response: short repeated keys, mixed value types, nesting."""
    return {
        "generated": "2026-08-20T12:30:05.123456Z",
        "next": "https://api.example.com/v2/readings?page=2",
        "results": [
            {
                "id": f"rec-{i:05d}",
                "sensor": f"sensor-{i % 97}",
                "value": 1.5 + (i % 1000) / 8.0,
                "unit": "degC",
                "enabled": bool(i % 3),
                "note": None if i % 5 else "threshold exceeded",
                "position": {
                    "lat": 48.8566 + i / 10000.0,
                    "lon": 2.3522 - i / 10000.0,
                },
                "tags": [f"tag-{i % 7}", f"zone-{i % 4}"],
            }
            for i in range(count)
        ],
    }


def sensor_grid(rows=400, cols=25):
    """Numbers and nothing else — where a text format pays most per value.

    json spells every float out in decimal digits; msgpack writes a tag and
    eight bytes. The grid is what a downsampled chart series or an
    accelerometer buffer looks like by the time it reaches Python.
    """
    rng = random.Random(SEED)
    return [[rng.random() * 1000 for _ in range(cols)] for _ in range(rows)]


def photo_blobs(count=200, size=8192):
    """Opaque bytes with a little metadata — the case json cannot express.

    json has no binary type, so the honest comparison is against what an app
    would really do: base64 the blobs and pay the third it costs.
    """
    rng = random.Random(SEED)
    return {
        "album": "field survey",
        "thumbnails": [rng.randbytes(size) for _ in range(count)],
    }


BUILDERS = {
    "api records": api_records,
    "sensor grid": sensor_grid,
    "photo blobs": photo_blobs,
}


def payload(name):
    """Build the chosen payload.

    Generated rather than bundled, so the same build produces the same bytes
    on every device and two phones can be compared with each other and with
    the desktop figures in the README.
    """
    return BUILDERS[name]()


def to_json_safe(obj):
    """Rewrite the parts of a payload json refuses, leaving the rest alone.

    Only `photo_blobs` needs it, but every payload goes through the same pair
    so the json column always measures a complete round trip rather than a
    convenient subset of one.
    """
    if isinstance(obj, dict) and "thumbnails" in obj:
        blobs = [base64.b64encode(b).decode() for b in obj["thumbnails"]]
        return {**obj, "thumbnails": blobs}
    return obj


def from_json_safe(obj):
    """Undo `to_json_safe`, so the round trip is comparable to the original."""
    if isinstance(obj, dict) and "thumbnails" in obj:
        blobs = [base64.b64decode(s) for s in obj["thumbnails"]]
        return {**obj, "thumbnails": blobs}
    return obj


def timed(work, reps=3):
    """Best of `reps` calls of `work`, in milliseconds, plus its last result."""
    best, result = None, None
    for _ in range(reps):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, result


def measure(obj):
    """Encode and decode `obj` both ways, timing each half and checking both.

    A size printed without its round trip verified would be the one number on
    screen worth distrusting, so nothing is reported until the decoded object
    has been compared with the original.

    The base64 step sits inside both json timings on purpose: it is what json
    costs to carry the bytes msgpack carries natively, and leaving it out of
    the encode while leaving it in the decode would flatter one half.
    """
    measured = []

    if msgpack is not None:
        pack_ms, packed = timed(lambda: msgpack.packb(obj))
        unpack_ms, restored = timed(lambda: msgpack.unpackb(packed))
        measured.append(("msgpack", len(packed), pack_ms, unpack_ms, restored == obj))

    dump_ms, text = timed(
        lambda: json.dumps(to_json_safe(obj), separators=(",", ":")).encode()
    )
    load_ms, back = timed(lambda: from_json_safe(json.loads(text)))
    measured.append(("json", len(text), dump_ms, load_ms, back == obj))

    reference = next(size for label, size, _, _, _ in measured if label == "json")
    rows = [
        (
            label,
            f"{size:,}",
            f"{size / reference:.2f}",
            f"{write_ms:,.2f}",
            f"{read_ms:,.2f}",
        )
        for label, size, write_ms, read_ms, _ in measured
    ]
    return rows, measured


def size_note(measured):
    """A clause naming the saving, or nothing when msgpack is not loaded."""
    sizes = {label: size for label, size, _, _, _ in measured}
    if "msgpack" not in sizes:
        return ""
    return f" · msgpack is {1 - sizes['msgpack'] / sizes['json']:.0%} smaller"


def same(original, restored):
    """True when the round trip returned the same type and the same value.

    Type is checked separately from value because the whole point of the table
    is the pairs that compare equal while changing type — and because NaN is
    never equal to itself, so identical floats need the explicit case.
    """
    if type(original) is not type(restored):
        return False
    if isinstance(original, float) and math.isnan(original):
        return math.isnan(restored)
    return original == restored


def outcome(original, work):
    """Run one round trip and report it in a phone-width cell.

    A cell is either `exact`, the name of the exception that stopped it, or
    the type and value that came back instead — which is the answer this table
    exists for.
    """
    try:
        restored = work()
    except Exception as error:
        return type(error).__name__
    if same(original, restored):
        return "exact"
    text = repr(restored)
    if not text.startswith(type(restored).__name__):
        text = f"{type(restored).__name__} {text}"
    return text if len(text) <= 22 else text[:21] + "…"


def msgpack_trip(value, pack=None, unpack=None):
    """One msgpack round trip with explicit options on each half.

    The two halves are deliberately separate: several of the surprises on this
    screen come from packing with one setting and unpacking with the matching
    default, which a single symmetric helper would hide.
    """
    return msgpack.unpackb(msgpack.packb(value, **(pack or {})), **(unpack or {}))


def json_trip(value):
    """One json round trip, no options — json has no equivalent switches."""
    return json.loads(json.dumps(value))


def fidelity_cases():
    """The values worth checking, with the msgpack options each one needs."""
    return (
        ("b'\\x89PNG'", b"\x89PNG", None, None),
        ("'café ☕'", "café ☕", None, None),
        ("{1: 'a'}", {1: "a"}, None, None),
        ("{1: 'a'} lax key", {1: "a"}, None, {"strict_map_key": False}),
        ("(1, 2)", (1, 2), None, None),
        ("{1, 2}", {1, 2}, None, None),
        ("2**64 - 1", 2**64 - 1, None, None),
        ("2**64", 2**64, None, None),
        ("float('nan')", float("nan"), None, None),
        ("0.1 + 0.2", 0.1 + 0.2, None, None),
        ("datetime=True", STAMP, {"datetime": True}, None),
        ("… + timestamp=3", STAMP, {"datetime": True}, {"timestamp": 3}),
    )


def fidelity_rows():
    """What each format hands back for every case, as display cells."""
    rows = []
    for label, value, pack, unpack in fidelity_cases():
        left = (
            "-"
            if msgpack is None
            else outcome(value, lambda v=value, p=pack, u=unpack: msgpack_trip(v, p, u))
        )
        rows.append((label, left, outcome(value, lambda v=value: json_trip(v))))
    return rows


def conversion_rows():
    """The two options that change a value's type without raising anything.

    `use_bin_type=False` writes bytes as msgpack's pre-2013 raw type and the
    default unpacker decodes raw as text; `raw=True` is the same trade in
    reverse. Either is one keyword away from code that looks symmetric.
    """
    if msgpack is None:
        return [("msgpack absent", "-")]
    return [
        (
            "packb(b'id', use_bin_type=False)",
            outcome(b"id", lambda: msgpack_trip(b"id", {"use_bin_type": False})),
        ),
        (
            "unpackb(packb('id'), raw=True)",
            outcome("id", lambda: msgpack_trip("id", None, {"raw": True})),
        ),
    ]


def integrity():
    """Flip one bit at a time in each format's frame and count the outcomes.

    Neither format carries a checksum, so this is not a contest — it is the
    reason to keep a digest beside anything you persist. A binary encoding has
    more bits that mean something, so more of the damage lands on a value that
    still decodes.
    """
    doc = [
        {"id": f"rec-{i:05d}", "value": 1.5 + i / 8.0, "tags": [f"tag-{i % 7}"]}
        for i in range(200)
    ]
    rng = random.Random(SEED)
    text = json.dumps(doc, separators=(",", ":")).encode()
    frames = [("json", text, json.loads)]
    if msgpack is not None:
        frames.insert(0, ("msgpack", msgpack.packb(doc), msgpack.unpackb))
    verdicts = []
    for label, frame, load in frames:
        raised = wrong = intact = 0
        for _ in range(FLIPS):
            damaged = bytearray(frame)
            damaged[rng.randrange(len(damaged))] ^= 1 << rng.randrange(8)
            try:
                restored = load(bytes(damaged))
            except Exception:  # any failure at all counts as damage detected
                raised += 1
                continue
            if restored == doc:
                intact += 1
            else:
                wrong += 1
        verdicts.append(
            f"{label} {raised} raised / {wrong} silently wrong / {intact} unaffected"
        )
    return f"{FLIPS} single-bit flips: " + " · ".join(verdicts)


def sharing():
    """Whether Flet's control protocol is using this same msgpack module.

    Flet encodes every control message with msgpack, so a Flet app already has
    the package loaded by the time `main` runs. Comparing the module objects
    is what shows the app is not carrying a second copy of anything.
    """
    protocol = sys.modules.get("flet.messaging.protocol")
    if protocol is None:
        return "Flet protocol not loaded yet"
    if getattr(protocol, "msgpack", None) is msgpack:
        return "same module Flet encodes controls with"
    return "separate from Flet's msgpack"


def implementation():
    """Which msgpack is loaded, and whether Flet is sharing it.

    `msgpack.Packer.__module__` is the only reliable answer to the first half:
    `__init__.py` falls back to the pure-Python packer without a word when the
    extension will not import, and that fallback is an order of magnitude
    slower.
    """
    if msgpack is None:
        return f"msgpack absent · {IMPORT_ERROR}"
    where = msgpack.Packer.__module__.rsplit(".", 1)[-1]
    kind = "C extension" if where == "_cmsgpack" else "pure-Python fallback"
    return f"msgpack {msgpack.__version__} · {kind} ({where}) · {sharing()}"


def table_row(values, weights, size=10):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Measure both formats on this device and show where they disagree.

    Three things are on screen: what each format costs in bytes and
    milliseconds, what survives a round trip unchanged, and what a damaged
    frame does. Everything is computed here rather than bundled, and the
    import is guarded so a missing wheel degrades to a json-only screen
    instead of a crash.
    """
    shown = PAYLOADS[0]  # the payload the size table currently describes

    def start():
        """Send one comparison to the thread pool and lock the picker meanwhile.

        The guard is set in this synchronous handler rather than in the worker:
        `run_thread` only schedules, so a `disabled` set inside the worker
        would not have reached the client before a second tap could start an
        overlapping run. A tap that beats it is dropped and the picker is put
        back to the payload being measured, because the client moves its own
        highlight the instant it is tapped.
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

    def run(name):
        """Measure one payload, then the fidelity cases and the bit flips.

        The payload name is passed in rather than read off the picker, because
        the worker starts after the handler returns and a tap landing in
        between would move `picker.selected` out from under it.

        Wrapped in try/except because `page.run_thread` discards whatever a
        worker raises — without this, a failure would look like a screen that
        quietly stopped updating. The tables are cleared on the error path so
        numbers from the previous run cannot be read as describing the error.
        """
        try:
            rows, measured = measure(payload(name))
            sizes.controls = [
                table_row(
                    ("format", "bytes", "vs json", "pack ms", "unpack ms"),
                    SIZE_WEIGHTS,
                ),
                ft.Divider(height=1),
                *(table_row(row, SIZE_WEIGHTS) for row in rows),
            ]
            exact = sum(1 for row in measured if row[4])
            summary.value = (
                f"{name} · {exact}/{len(measured)} formats decoded back to an "
                f"equal object{size_note(measured)}"
            )
            fidelity.controls = [
                table_row(("value", "msgpack", "json"), FIDELITY_WEIGHTS),
                ft.Divider(height=1),
                *(table_row(row, FIDELITY_WEIGHTS) for row in fidelity_rows()),
            ]
            silent.controls = [
                table_row(row, CONVERSION_WEIGHTS) for row in conversion_rows()
            ]
            damage.value = integrity()
        except Exception as error:  # the worker must never let one escape
            sizes.controls = []
            fidelity.controls = []
            silent.controls = []
            damage.value = ""
            summary.value = f"{type(error).__name__}: {error}"

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("msgpack vs json"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        implementation(),
                        size=11,
                        color=ft.Colors.ERROR if msgpack is None else None,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} · {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                segments=[
                                    ft.Segment(value=name, label=ft.Text(name))
                                    for name in PAYLOADS
                                ],
                                selected=[PAYLOADS[0]],  # a set dies in msgpack
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    sizes := ft.Column(spacing=4),
                    summary := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("what survives a round trip", size=11),
                    fidelity := ft.Column(spacing=4),
                    ft.Divider(),
                    ft.Text("same bytes, different type", size=11),
                    silent := ft.Column(spacing=4),
                    ft.Divider(),
                    damage := ft.Text(size=11),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
