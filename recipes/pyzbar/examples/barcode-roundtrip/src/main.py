"""Encode three barcodes, decode them back with pyzbar, and show whether the round trip held."""

import base64
import ctypes
import platform
import random
import struct
import zlib
from ctypes.util import find_library

import flet as ft

# pyzbar builds a ctypes prototype for every zbar function at module scope, and the
# first one dlopens libzbar — so a missing library raises while this import statement
# is still running, not at the first decode() call.
IMPORT_ERROR = None
try:
    import pyzbar
    from pyzbar import wrapper
    from pyzbar.pyzbar import ZBarSymbol, decode
    from pyzbar.wrapper import ZBarConfig
except Exception as error:
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

# Code 128 symbol patterns 0-106, as bar/space module runs starting with a bar.
CODE128_WIDTHS = (
    "212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 "
    "221312 231212 112232 122132 122231 113222 123122 123221 223211 221132 "
    "221231 213212 223112 312131 311222 321122 321221 312212 322112 322211 "
    "212123 212321 232121 111323 131123 131321 112313 132113 132311 211313 "
    "231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 "
    "231131 213113 213311 213131 311123 311321 331121 312113 312311 332111 "
    "314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 "
    "112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 "
    "111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 "
    "214121 412121 111143 111341 131141 114113 114311 411113 411311 113141 "
    "114131 311141 411131 211412 211214 211232 2331112"
).split()
CODE128_START_B = 104
CODE128_STOP = 106

# EAN-13 digit alphabets: odd-parity left, even-parity left, right.
EAN_L = "0001101 0011001 0010011 0111101 0100011 0110001 0101111 0111011 0110111 0001011".split()
EAN_G = "0100111 0110011 0011011 0100001 0011101 0111001 0000101 0010001 0001001 0010111".split()
EAN_R = "1110010 1100110 1101100 1000010 1011100 1001110 1010000 1000100 1001000 1110100".split()
# Which alphabet each of the six left-hand digits uses, indexed by the first digit.
EAN_PARITY = (
    "LLLLLL LLGLGG LLGGLG LLGGGL LGLLGG LGGLLG LGGGLL LGLGLG LGLGGL LGGLGL".split()
)

# The 25x25 module matrix of QR_TEXT, one row per 4 bytes, MSB first.
QR_MATRIX = (
    "/kO/gIJWIIC6W66AuqougLp3roCC8CCA/qq/gADrgABiPzQAlY+1gN5JFoDtVJQAfkWwgCwh"
    "sYD+taaAIcrcANoz+QAA4oiA/gSogIJHiAC6efmAuhLLALrUHYCCzNgA/iXkgA=="
)
QR_SIZE = 25

CODE128_TEXT = "FLET-0.86.5"
EAN13_BODY = "590123412345"
QR_TEXT = "https://flet.dev"
MAX_FLIPS = 30
IMAGE_BOX = 340
MAX_IMAGE_HEIGHT = 240


def widths_to_modules(widths):
    """Expand one Code 128 width group ("212222") into '1' bars and '0' spaces."""
    return "".join(
        ("1" if position % 2 == 0 else "0") * int(width)
        for position, width in enumerate(widths)
    )


def code128_bits(text):
    """Code 128 code set B for `text`, as modules, plus the mod-103 checksum put in it.

    Returning the checksum is the point of computing it here: zbar recomputes it
    from the bars it read and refuses the symbol unless the two agree, so a
    successful decode is two independent implementations of the same spec
    agreeing rather than one implementation talking to itself.
    """
    values = [CODE128_START_B] + [ord(char) - 32 for char in text]
    checksum = sum(value * max(index, 1) for index, value in enumerate(values)) % 103
    values += [checksum, CODE128_STOP]
    return (
        "".join(widths_to_modules(CODE128_WIDTHS[value]) for value in values),
        checksum,
    )


def ean13_check_digit(body):
    """The mod-10 check digit for a 12-digit EAN-13 body."""
    total = sum(int(digit) * (3 if i % 2 else 1) for i, digit in enumerate(body))
    return (10 - total % 10) % 10


def ean13_bits(body):
    """EAN-13 for a 12-digit body, as modules, plus the full 13-digit value it encodes.

    The leading digit is never drawn: it is carried by which of the L and G
    alphabets each of the six left-hand digits uses, which is why the parity
    table exists.
    """
    full = body + str(ean13_check_digit(body))
    left = "".join(
        (EAN_L if parity == "L" else EAN_G)[int(digit)]
        for parity, digit in zip(EAN_PARITY[int(full[0])], full[1:7])
    )
    right = "".join(EAN_R[int(digit)] for digit in full[7:])
    return "101" + left + "01010" + right + "101", full


def qr_modules():
    """Unpack the embedded 25x25 QR matrix into rows of '1' and '0'.

    The modules are carried as data rather than generated: a QR encoder means
    Reed-Solomon and mask selection, which teaches nothing about pyzbar. The
    decode below is what proves they are the right modules.
    """
    packed = base64.b64decode(QR_MATRIX)
    stride = (QR_SIZE + 7) // 8
    rows = []
    for y in range(QR_SIZE):
        value = int.from_bytes(packed[y * stride : (y + 1) * stride], "big")
        rows.append(bin(value)[2:].zfill(stride * 8)[:QR_SIZE])
    return rows


def flip_modules(rows, count):
    """Invert `count` randomly chosen modules — the damage the slider applies.

    Seeded from the count so every slider stop is reproducible: the same setting
    always produces the same picture and the same verdict, which is what makes
    the comparison between the symbologies worth reading.
    """
    if not count:
        return rows
    grid = [list(row) for row in rows]
    cells = [(y, x) for y in range(len(grid)) for x in range(len(grid[0]))]
    for y, x in random.Random(count).sample(cells, min(count, len(cells))):
        grid[y][x] = "0" if grid[y][x] == "1" else "1"
    return ["".join(row) for row in grid]


def raster(rows, scale, quiet):
    """Paint a module matrix into an 8-bit greyscale buffer: (pixels, width, height).

    That tuple is the only image pyzbar takes without an image library — one byte
    per pixel, 0 for a bar and 255 for a space. It has to be immutable `bytes`:
    pyzbar casts the object straight to a C pointer, and a `bytearray` or
    `memoryview` raises ctypes.ArgumentError from inside the wrapper instead of
    a PyZbarError.
    """
    width = (len(rows[0]) + 2 * quiet) * scale
    margin = b"\xff" * (width * quiet * scale)
    pad = b"\xff" * (quiet * scale)
    lines = [margin]
    for row in rows:
        painted = b"".join(
            (b"\x00" if module == "1" else b"\xff") * scale for module in row
        )
        lines.append((pad + painted + pad) * scale)
    lines.append(margin)
    pixels = b"".join(lines)
    return pixels, width, len(pixels) // width


def rotate_cw(pixels, width, height):
    """Turn the buffer 90 degrees clockwise, so the reported orientation changes."""
    turned = bytearray(len(pixels))
    for y in range(height):
        row = pixels[y * width : (y + 1) * width]
        for x, value in enumerate(row):
            turned[x * height + (height - 1 - y)] = value
    return bytes(turned), height, width


def to_png(pixels, width, height):
    """Wrap the same greyscale buffer in an 8-bit PNG for ft.Image(src=<bytes>).

    Twenty lines of zlib and struct instead of an image library, so that the
    picture on screen and the bytes handed to decode() are provably the same
    data and the example needs no assets directory.
    """
    scanlines = b"".join(
        b"\x00" + pixels[y * width : (y + 1) * width] for y in range(height)
    )

    def chunk(tag, body):
        """One PNG chunk: length, tag, payload, CRC-32 over tag and payload."""
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )


def libzbar_version():
    """Read the version out of the libzbar that pyzbar already loaded.

    Declared here with THREE arguments deliberately. pyzbar.wrapper.zbar_version
    declares two, but zbar 0.23 writes a patch level through a third pointer that
    was never passed — calling pyzbar's own binding killed CPython 3.12 and 3.13
    outright, and a native crash takes the Flet session down with no traceback to
    catch.

    Guarded because this is the only hand-declared FFI call in the app and it
    only feeds a caption: a libzbar that stopped exporting the symbol would
    otherwise raise inside main() and bring the whole screen up blank.
    """
    pointer = ctypes.POINTER(ctypes.c_uint)
    parts = (ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint())
    try:
        read = ctypes.CFUNCTYPE(ctypes.c_int, pointer, pointer, pointer)(
            ("zbar_version", wrapper.LIBZBAR)
        )
        if read(*(ctypes.byref(part) for part in parts)) != 0:
            return "unknown"
    except Exception:
        return "unknown"
    return ".".join(str(part.value) for part in parts)


def symbology_support():
    """Ask this device's libzbar which symbologies it was actually compiled with.

    `zbar_image_scanner_set_config(..., CFG_ENABLE, 1)` returns 0 when the
    decoder is present and 1 when the build left it out, so this reports what the
    shipped library can read rather than what pyzbar's enum lists — the two do
    not agree. NONE and PARTIAL are skipped: they are scanner states, not
    symbologies.
    """
    scanner = wrapper.zbar_image_scanner_create()
    try:
        return {
            symbol.name: wrapper.zbar_image_scanner_set_config(
                scanner, symbol, ZBarConfig.CFG_ENABLE, 1
            )
            == 0
            for symbol in ZBarSymbol
            if symbol.name not in ("NONE", "PARTIAL")
        }
    finally:
        wrapper.zbar_image_scanner_destroy(scanner)


def build_symbols():
    """The three symbols this app encodes, each with the value that has to come back."""
    code128, checksum = code128_bits(CODE128_TEXT)
    ean13, full = ean13_bits(EAN13_BODY)
    return [
        {
            "name": "Code 128",
            "rows": [code128],
            "bars": 26,
            "scale": 2,
            "quiet": 8,
            "encoded": CODE128_TEXT,
            "self_check": f"mod-103 checksum {checksum}",
        },
        {
            "name": "EAN-13",
            "rows": [ean13],
            "bars": 26,
            "scale": 2,
            "quiet": 8,
            "encoded": full,
            "self_check": f"mod-10 check digit {full[-1]}",
        },
        {
            "name": "QR",
            "rows": qr_modules(),
            "bars": 1,
            "scale": 6,
            "quiet": 4,
            "encoded": QR_TEXT,
            "self_check": f"{QR_SIZE}x{QR_SIZE} modules, ECC level Q",
        },
    ]


def round_trip(symbol, flips, rotated):
    """Damage, rasterise, decode and judge one symbol; never raises.

    decode() reports bad input as ordinary Python exceptions from deep inside
    ctypes rather than as pyzbar's own error type, and an unhandled exception in
    a Flet handler ends the session with a crash screen — so the failure is
    turned into a line of text instead.
    """
    rows = flip_modules(symbol["rows"], flips) * symbol["bars"]
    pixels, width, height = raster(rows, symbol["scale"], symbol["quiet"])
    if rotated:
        pixels, width, height = rotate_cw(pixels, width, height)
    report = {
        "png": to_png(pixels, width, height),
        # Height that fits the buffer into a phone-width box, so a rotated 1-D
        # symbol stays legible instead of being squashed into the upright size.
        "display_height": min(MAX_IMAGE_HEIGHT, round(IMAGE_BOX * height / width)),
        "lines": [
            f"{symbol['name']} · encoded {symbol['encoded']!r} · "
            f"{symbol['self_check']} · {width}x{height} px"
        ],
    }
    try:
        found = decode((pixels, width, height))
    except Exception as error:
        report["lines"].append(f"{type(error).__name__}: {error}")
        return report
    if not found:
        report["lines"].append("no symbol found")
        return report
    result = found[0]
    text = result.data.decode("utf-8", "replace")
    corners = " ".join(f"({point.x},{point.y})" for point in result.polygon)
    report["type"] = result.type
    report["lines"] += [
        f"decoded {result.data!r} -> {text!r}",
        f"{result.type} · quality {result.quality} · orientation {result.orientation}",
        f"rect {result.rect.left},{result.rect.top} "
        f"{result.rect.width}x{result.rect.height} · polygon {corners}",
        "MATCH" if text == symbol["encoded"] else "MISMATCH",
    ]
    return report


def symbol_card():
    """The picture and the report line for one symbol, made once so the image swaps in place.

    `ft.Image` needs a `src` at construction and nothing has been rasterised yet,
    so it starts on a one-pixel PNG that the first redraw replaces — which is
    what `gapless_playback` is for. Nothing here touches pyzbar, so the cards can
    be built before the library is known to be importable.
    """
    return {
        "image": ft.Image(
            src=to_png(b"\xff", 1, 1),
            gapless_playback=True,
            filter_quality=ft.FilterQuality.NONE,
            fit=ft.BoxFit.CONTAIN,
        ),
        "report": ft.Text(size=12, selectable=True),
    }


def capability_report(decoded_types):
    """What this build can read, and whether that agrees with what just decoded.

    The PDF417 line is the consumer-facing half of the same fact: a symbology
    this libzbar lacks does not raise when you filter on it, it silently returns
    nothing. The last line is the cross-check — every symbology that decoded
    above has to be one the library reports as compiled in, one answer coming
    from the decoder and the other from the library's own configuration.

    The probe is guarded for the same reason round_trip() is: it is the least
    travelled path in the app — the only place that drives libzbar's config API
    directly — and a raise here would replace the answer with a crash screen.
    """
    try:
        support = symbology_support()
        filtered = decode((b"\xff" * 64 * 64, 64, 64), symbols=[ZBarSymbol.PDF417])
    except Exception as error:
        return f"capability probe failed — {type(error).__name__}: {error}"
    compiled = [name for name, present in support.items() if present]
    missing = [name for name, present in support.items() if not present]
    if decoded_types:
        agreement = (
            f"{', '.join(sorted(decoded_types))} — "
            f"{'all compiled in' if all(support.get(n) for n in decoded_types) else 'INCONSISTENT'}"
        )
    else:
        agreement = "nothing at this damage level"
    return (
        f"compiled in ({len(compiled)}): {', '.join(compiled)}\n"
        f"not compiled in ({len(missing)}): {', '.join(missing) or 'none'}\n"
        f"decode(symbols=[PDF417]) returned {filtered!r} — asking for a symbology "
        f"this build lacks returns nothing rather than raising\n"
        f"decoded above: {agreement}"
    )


def blocked_reason():
    """Why the screen cannot run, or None if it can.

    Only ever set off-device: `flet run` on a desktop resolves pyzbar from PyPI,
    which ships no libzbar and asks ctypes.util.find_library('zbar') for a system
    one. The mobile wheels carry theirs, so this message is what a desktop run
    without `brew install zbar` / `apt install libzbar0` shows instead of failing
    to launch.
    """
    if IMPORT_ERROR is None:
        return None
    return (
        f"pyzbar did not import — {IMPORT_ERROR}\n\n"
        "On Android and iOS the libzbar this needs travels with the wheel. On a "
        "desktop it does not: install zbar system-wide (brew install zbar, or "
        "apt install libzbar0) and, on macOS, run with "
        "DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib."
    )


def main(page: ft.Page):
    """Encode three barcodes, decode them back, and report whether each round trip held.

    Everything is computed on the device from constants in this file: no camera,
    no network, no assets and no image library. The slider damages whole modules
    before rasterising, which is what separates a symbology that only detects
    errors from one that corrects them.
    """
    symbols = build_symbols()
    cards = [symbol_card() for _ in symbols]

    def render():
        """Run all three round trips at the current slider and switch settings."""
        flips = int(damage.value)
        rotated = bool(turn.value)
        decoded_types = set()
        for symbol, card in zip(symbols, cards):
            report = round_trip(symbol, flips, rotated)
            decoded_types.add(report.get("type"))
            card["image"].src = report["png"]
            card["image"].height = report["display_height"]
            card["report"].value = "\n".join(report["lines"])
        decoded_types.discard(None)
        capability.value = capability_report(decoded_types)

    def redraw():
        """Re-run the round trips after the slider is released or the switch is flipped."""
        preview()
        render()

    def preview():
        """Caption the damage level under the thumb while the slider is still moving."""
        flips = int(damage.value)
        caption.value = (
            f"{flips} module{'' if flips == 1 else 's'} inverted before rasterising"
        )

    page.appbar = ft.AppBar(title=ft.Text("Barcode round trip"), center_title=True)
    blocked = blocked_reason()
    if blocked:
        page.add(
            ft.SafeArea(
                expand=True,
                content=ft.Card(
                    content=ft.Container(padding=16, content=ft.Text(blocked, size=13))
                ),
            )
        )
        return

    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"pyzbar {pyzbar.__version__} · libzbar {libzbar_version()} · "
                        f"{page.platform.value} · CPython {platform.python_version()} · "
                        f"find_library('zbar') = {find_library('zbar')!r}",
                        size=11,
                        selectable=True,
                    ),
                    caption := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    damage := ft.Slider(
                        value=0,
                        min=0,
                        max=MAX_FLIPS,
                        divisions=MAX_FLIPS,
                        label="{value}",
                        on_change=preview,
                        on_change_end=redraw,
                    ),
                    turn := ft.Switch(label="rotate 90° clockwise", on_change=redraw),
                    *[
                        ft.Column(spacing=4, controls=[card["image"], card["report"]])
                        for card in cards
                    ],
                    ft.Text(
                        "what this build can read", size=12, weight=ft.FontWeight.BOLD
                    ),
                    capability := ft.Text(size=12, selectable=True),
                ],
            ),
        )
    )

    redraw()


if __name__ == "__main__":
    ft.run(main)
