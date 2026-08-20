"""A Bloom filter on bitarray: its bits drawn as a bitmap, its error rate measured."""

import hashlib
import math
import platform
import struct
import sys
import time
import zlib

import flet as ft

try:
    import bitarray
    from bitarray.util import sc_encode, serialize, zeros

    IMPORT_ERROR = None
except Exception as error:
    bitarray = zeros = serialize = sc_encode = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

BITS = 1 << 16
SIDE = 256
PROBES = 50_000
MAX_HASHES = 8
KEY_COUNTS = (2_000, 5_000, 10_000, 20_000, 40_000)


def member(index):
    """The key of member `index`."""
    return b"user-%07d" % index


def outsider(index):
    """The key of probe `index`, disjoint from every member key by construction."""
    return b"probe-%07d" % index


def positions(key, hashes):
    """The `hashes` bit positions `key` occupies, by Kirsch-Mitzenmacher double hashing.

    One SHA-256 digest supplies two 64-bit values, and position i is
    `(first + i * step) % BITS`; `step` is forced odd so that it stays coprime
    with a power-of-two BITS and the positions cannot collapse onto each other.
    SHA-256 rather than the builtin `hash()`, which is salted per process and
    would make the same key land somewhere else on every launch — the numbers
    this screen reports are meant to be identical on every device.
    """
    digest = hashlib.sha256(key).digest()
    first = int.from_bytes(digest[:8], "big")
    step = int.from_bytes(digest[8:16], "big") | 1
    return [(first + i * step) % BITS for i in range(hashes)]


def hash_count(keys):
    """How many hashes minimise the error rate for `keys` members, capped at MAX_HASHES.

    The cap is a practical limit rather than a theoretical one: at 2,000 keys
    the optimum is 23 hashes, and buying an error rate that far below what
    PROBES samples can resolve is 23 lookups nobody sees the benefit of.
    """
    return min(MAX_HASHES, max(1, round(BITS / keys * math.log(2))))


def hashes_phrase(hashes):
    """`hashes` as English, since the bottom of the ladder really does use one."""
    return "1 hash" if hashes == 1 else f"{hashes} hashes"


def build(keys, hashes):
    """Set every member's bits in a fresh filter, and time the whole insertion."""
    started = time.perf_counter()
    filt = zeros(BITS)
    for index in range(keys):
        for position in positions(member(index), hashes):
            filt[position] = 1
    return filt, time.perf_counter() - started


def false_positives(filt, hashes):
    """How many of PROBES non-members the filter wrongly claims to hold, and how long."""
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
    pixel in the most significant bit — which is exactly how a big-endian
    bitarray packs its bits. So a scanline is a slice of `filt.tobytes()` behind
    a zero filter byte, and no per-pixel conversion happens anywhere below. Set
    bits come out white.
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


def rate_text(value):
    """A probability printed so that a very small one stays legible.

    The top of the ladder errs about once in two, the bottom about once in two
    hundred thousand; a single fixed number of decimals cannot show both, and
    rounding the small end to `0.00000` would hide the whole point of adding
    hashes.
    """
    if value == 0:
        return "0"
    return f"{value:.5f}" if value >= 1e-4 else f"{value:.2e}"


def analyse(keys):
    """Build a filter for `keys` members, measure its error rate, and price it.

    Everything the screen shows is produced here, so a single call is one
    self-contained experiment: no state survives between passes and re-running
    the same slider position gives the same numbers.
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
        "filter": filt,
        "image": image,
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


def main(page: ft.Page):
    """Show one Bloom filter at a time, and rebuild it when the slider is released.

    Every pass goes through `page.run_thread`, the first one included. A
    synchronous `main` runs on Flet's event loop thread and the socket writer is
    a task on that same loop, so a pass computed inline here holds the layout
    `page.add` queued until `main` returns — 980 ms of blank screen, measured on
    a desktop. Handing the first pass to the worker too is what puts the
    controls on screen first, and leaves one place where the two Flet rules
    below have to be honoured.
    """

    def caption_for(keys):
        """The slider's label: which filter this position stands for."""
        return (
            f"{keys:,} members in {BITS:,} bits — "
            f"{hashes_phrase(hash_count(keys))} each"
        )

    def line(label, value):
        """One result row, laid out so neither half can overflow a phone-width screen."""
        return ft.Row(
            controls=[
                ft.Text(label, size=11, expand=2, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(value, size=11, expand=5),
            ]
        )

    def report(found):
        """Turn one `analyse` result into the rows under the bitmap."""
        agrees = abs(found["wrong"] - found["expected"]) <= found["margin"]
        ratio = found["set_bytes"] / found["nbytes"]
        return [
            line(
                "filter",
                f"{BITS:,} bits · {found['nbytes']:,} B buffer · "
                f"{SIDE}×{BITS // SIDE} bitmap",
            ),
            line(
                "members",
                f"{found['keys']:,} keys · {hashes_phrase(found['hashes'])} each",
            ),
            line(
                "bits set",
                f"{found['set_bits']:,} ({found['fill']:.1%} full)",
            ),
            line(
                "false positives",
                f"{found['wrong']:,} of {PROBES:,} non-members = "
                f"{rate_text(found['measured'])}",
            ),
            line(
                "predicted",
                f"fill^k = {rate_text(found['predicted'])} → "
                f"{found['expected']:,.1f} ± {found['margin']:,.1f} expected",
            ),
            line(
                "agreement",
                "inside the 95% band" if agrees else "OUTSIDE the 95% band",
            ),
            line(
                "memory",
                f"{found['nbytes']:,} B filter vs {found['set_bytes']:,} B for "
                f"set(keys) — {ratio:,.0f}× · [False] × {BITS:,} is "
                f"{found['list_bytes']:,} B",
            ),
            line(
                "to store",
                f"serialize {found['serialized']:,} B · "
                f"sc_encode {found['compressed']:,} B · "
                f"this PNG {len(found['image']):,} B",
            ),
            line(
                "cost here",
                f"insert {found['build_ms']:.0f} ms · "
                f"{PROBES:,} probes {found['probe_ms']:.0f} ms · "
                f"bitmap {found['draw_ms']:.1f} ms",
            ),
        ]

    def refresh(keys):
        """Run one pass and move every control that depends on it."""
        found = analyse(keys)
        picture.src = found["image"]
        picture.visible = True
        rows.controls = report(found)
        caption.value = caption_for(keys)
        header.value = (
            f"bitarray {bitarray.__version__} · "
            f"{found['filter'].buffer_info().endian}-endian · "
            f"Python {platform.python_version()} · {page.platform.value}"
        )

    def worker(keys):
        """The whole of a pass, off the event loop thread.

        Two Flet rules meet here. `page.run_thread` never retrieves the
        worker's future, so an exception raised in this body would vanish
        without a log, a dialog or a crash — hence the bare `except`. And
        auto-update does not reach a background thread, so the explicit
        `page.update()` is what actually redraws the screen.
        """
        try:
            refresh(keys)
        except Exception as error:
            rows.controls = [line("failed", f"{type(error).__name__}: {error}")]
        finally:
            size.disabled = False
            page.update()

    def rebuild():
        """Start a pass on the slider's position, with the slider locked.

        Called on every release, and once by `main` for the first pass.
        Locking is what keeps two passes from overlapping: `run_thread`
        submits to a shared pool, so a second release during a run would
        genuinely execute alongside the first and both would write these same
        controls.
        """
        keys = KEY_COUNTS[int(size.value)]
        caption.value = f"building {caption_for(keys)}"
        size.disabled = True
        page.run_thread(worker, keys)

    def preview():
        """Say what the slider is currently pointing at, without building it."""
        caption.value = caption_for(KEY_COUNTS[int(size.value)])

    page.appbar = ft.AppBar(title=ft.Text("bitarray Bloom filter"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    header := ft.Text(size=11),
                    note := ft.Text(size=11, visible=False),
                    ft.Container(
                        border=ft.Border.all(1, ft.Colors.OUTLINE),
                        width=SIDE,
                        height=BITS // SIDE,
                        content=(
                            picture := ft.Image(
                                src=b"",
                                width=SIDE,
                                height=BITS // SIDE,
                                visible=False,
                                gapless_playback=True,
                                filter_quality=ft.FilterQuality.NONE,
                            )
                        ),
                    ),
                    ft.Text(
                        "one pixel per bit — the PNG's pixel data is the filter's "
                        "own buffer, white where a bit is set",
                        size=10,
                        italic=True,
                    ),
                    caption := ft.Text(size=11),
                    size := ft.Slider(
                        min=0,
                        max=len(KEY_COUNTS) - 1,
                        value=1,
                        divisions=len(KEY_COUNTS) - 1,
                        on_change=preview,
                        on_change_end=rebuild,
                    ),
                    rows := ft.Column(spacing=2),
                ],
            ),
        )
    )

    if bitarray is None:
        header.value = f"bitarray absent · Python {platform.python_version()}"
        note.value = (
            f'{IMPORT_ERROR}\nAdd "bitarray" to [project] dependencies — the '
            "package has desktop wheels as well as the mobile ones, so one entry "
            "covers `flet run` and `flet build` alike."
        )
        note.visible = True
        caption.value = "nothing to build without the package"
        size.disabled = True
        return

    rebuild()


if __name__ == "__main__":
    ft.run(main)
