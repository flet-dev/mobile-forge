"""The comparison itself: payloads, codecs, timings and the bit-flip sweep."""

import bz2
import gzip
import hashlib
import json
import lzma
import random
import time
import zlib

try:
    import brotli
except Exception as error:  # the wheel may be missing or fail to load
    brotli = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

HAVE_BROTLI = brotli is not None

PAYLOADS = ("web page", "api json", "log lines")

REPEAT_BUDGET_MS = 20.0

FLIPS = 120

DICTIONARY_BYTES = 122784  # data_size in libbrotli's c/common/dictionary.c

SEED = 20260819


def web_page(sections=1200):
    """Markup, the shape brotli's built-in dictionary was trained on.

    Tag names, attribute names and the boilerplate in the head are all words the
    dictionary already holds, so this is the payload where brotli's structural
    advantage over deflate should be widest.
    """
    head = (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Field report</title>\n"
        '<link rel="stylesheet" href="/static/app.css">\n'
        '<script src="/static/app.js" defer></script>\n</head>\n<body>\n'
    )
    body = "".join(
        f'<section class="card" id="card-{i:03d}" data-index="{i}">\n'
        f'  <h2 class="card__title">Station {i % 37}</h2>\n'
        f'  <p class="card__body">Reading {i} recorded at 2026-08-19T'
        f'{i % 24:02d}:{i % 60:02d}:00Z by <a href="/stations/{i % 37}">'
        f"station {i % 37}</a>.</p>\n"
        f'  <ul class="card__tags"><li>zone-{i % 4}</li><li>tag-{i % 7}</li></ul>\n'
        "</section>\n"
        for i in range(sections)
    )
    return (head + body + "</body>\n</html>\n").encode()


def api_json(records=2000):
    """An API response: short repeated keys wrapped around values that keep changing."""
    return json.dumps(
        {
            "generated": "2026-08-19T12:30:05.123456Z",
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
                for i in range(records)
            ],
        },
        separators=(",", ":"),
    ).encode()


def log_lines(lines=3400):
    """Log output: long-range repetition that rewards a large sliding window."""
    return b"".join(
        f"2026-08-19T12:{i % 60:02d}:{i % 59:02d}.{i % 1000:03d}Z INFO "
        f"worker-{i % 17} handled GET /v2/readings/{i} in {i % 900}ms "
        f"status={200 if i % 11 else 500} bytes={512 + i % 4096}\n".encode()
        for i in range(lines)
    )


BUILDERS = {"web page": web_page, "api json": api_json, "log lines": log_lines}


def payload(name):
    """Build the chosen payload.

    Generated rather than bundled, so the same build produces the same bytes on
    every device and two phones can be compared with each other and with the
    desktop figures in the README.
    """
    return BUILDERS[name]()


def small_inputs():
    """Inputs too short to build a history from, plus one that is pure noise.

    The five snippets are where brotli's built-in dictionary does the work:
    deflate has nothing but the input itself to match against and spends more
    bytes on framing than it saves. The random block is the control - no
    dictionary helps there and every codec has to give bytes back.
    """
    return (
        (
            "html fragment",
            b'<div class="card"><h2>Station 12</h2>'
            b"<p>Reading 4821 at 2026-08-19T09:14:00Z</p></div>",
        ),
        (
            "http headers",
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\n"
            b"Cache-Control: no-cache\r\nContent-Encoding: br\r\n\r\n",
        ),
        (
            "json record",
            b'{"id":"rec-00421","sensor":"sensor-33","value":42.5,'
            b'"unit":"degC","enabled":true}',
        ),
        (
            "url list",
            b"https://www.example.com/index.html "
            b"https://www.example.com/about.html "
            b"https://www.example.com/contact.html",
        ),
        (
            "log line",
            b"2026-08-19T12:14:37.221Z INFO worker-7 "
            b"handled GET /v2/readings/4821 in 37ms status=200\n",
        ),
        ("random 4 KiB", random.Random(SEED).randbytes(4096)),
    )


def timed(work):
    """Best of up to three calls of `work`, in milliseconds, plus its last result.

    Repeating only pays while the work is cheap. Quality 11 costs hundreds of
    milliseconds on these payloads, and three of those per codec would turn one
    tap into a visible stall, so the loop stops once a call exceeds the budget.
    """
    best, result = None, None
    for _ in range(3):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
        if best > REPEAT_BUDGET_MS:
            break
    return best, result


def codec_table():
    """Label, compress and decompress for every row of the main table.

    zlib and gzip sit next to each other deliberately: they are the same deflate
    stream in different containers, so the pair separates what the framing costs
    from what the algorithm does. `mtime=0` keeps gzip reproducible, since its
    header otherwise records the current time.
    """
    entries = []
    if brotli is not None:
        entries += [
            (
                f"brotli q{quality}",
                lambda data, q=quality: brotli.compress(data, quality=q),
                brotli.decompress,
            )
            for quality in (1, 5, 9, 11)
        ]
    entries += [
        ("zlib 9", lambda data: zlib.compress(data, 9), zlib.decompress),
        ("gzip 9", lambda data: gzip.compress(data, 9, mtime=0), gzip.decompress),
        ("lzma p6", lzma.compress, lzma.decompress),
        ("bz2 9", lambda data: bz2.compress(data, 9), bz2.decompress),
    ]
    return entries


def measure(data):
    """Time every codec on `data` and check each frame decodes back to it exactly.

    Returns the display rows, a `(label, size, read_ms, exact)` tuple per codec
    for the summary line, and the first codec's round-trip output - a ratio
    printed beside an unverified round trip would be worse than no number at all.
    """
    rows, results, replay = [], [], b""
    for index, (label, compress, decompress) in enumerate(codec_table()):
        write_ms, frame = timed(lambda work=compress: work(data))
        read_ms, back = timed(lambda work=decompress, f=frame: work(f))
        if index == 0:
            replay = back
        results.append((label, len(frame), read_ms, back == data))
        rows.append(
            (
                label,
                f"{len(frame):,}",
                f"{len(data) / len(frame):.2f}",
                f"{write_ms:,.1f}",
                f"{read_ms:,.2f}",
            )
        )
    return rows, results, replay


def small_rows():
    """Every short input compressed three ways, in bytes rather than ratios.

    Sizes below one-to-one are the point here, and absolute bytes show it more
    plainly: any number larger than the raw column is a codec that grew the input.
    """
    rows = []
    for name, data in small_inputs():
        packed = "-" if brotli is None else f"{len(brotli.compress(data)):,}"
        rows.append(
            (
                name,
                f"{len(data):,}",
                packed,
                f"{len(zlib.compress(data, 9)):,}",
                f"{len(gzip.compress(data, 9, mtime=0)):,}",
            )
        )
    return rows


def integrity(data):
    """Flip one bit per trial in a brotli frame and a gzip frame; report the outcome.

    A brotli frame carries no checksum, so damage can decode to the wrong bytes
    without raising anything. gzip's CRC32 trailer is the control here: it should
    catch every flip. The seed is fixed, so one device gives the same answer twice.
    """
    if brotli is None:
        return "brotli absent - integrity sweep skipped"
    rng = random.Random(SEED)
    verdicts = []
    for label, frame, decompress in (
        ("brotli q5", brotli.compress(data, quality=5), brotli.decompress),
        ("gzip 9", gzip.compress(data, 9, mtime=0), gzip.decompress),
    ):
        raised = wrong = intact = 0
        for _ in range(FLIPS):
            damaged = bytearray(frame)
            damaged[rng.randrange(len(damaged))] ^= 1 << rng.randrange(8)
            try:
                out = decompress(bytes(damaged))
            except Exception:  # any failure at all counts as "damage detected"
                raised += 1
                continue
            if out == data:
                intact += 1
            else:
                wrong += 1
        verdicts.append(
            f"{label} {raised} raised / {wrong} silently wrong / {intact} unaffected"
        )
    return f"{FLIPS} single-bit flips: " + " - ".join(verdicts)


def summarise(data, results):
    """One line naming the smallest frame, the fastest read and the head-to-head.

    The head-to-head is the choice an app author actually faces: brotli at a
    quality costing roughly what deflate costs, against deflate at its best.
    """
    smallest = min(results, key=lambda row: row[1])
    fastest = min(results, key=lambda row: row[2])
    sizes = {row[0]: row[1] for row in results}
    head = ""
    if "brotli q5" in sizes:
        gain = 1 - sizes["brotli q5"] / sizes["zlib 9"]
        head = f" - brotli q5 is {gain:.0%} smaller than zlib 9"
    return (
        f"{len(data):,} B source - smallest {smallest[0]} at {smallest[1]:,} B, "
        f"fastest read {fastest[0]} at {fastest[2]:,.2f} ms{head}"
    )


def verified(data, results, replay):
    """How many codecs round-tripped, with a digest of the source and of the replay.

    A size printed without its round trip verified would be the one number on
    screen worth distrusting, so this line is what the caller should say out loud
    above the table.
    """
    exact = sum(1 for row in results if row[3])
    digest = hashlib.sha256(data).hexdigest()
    replayed = hashlib.sha256(replay).hexdigest()
    return (
        f"{exact}/{len(results)} codecs round-tripped exactly - "
        f"sha256 {digest[:12]} vs {replayed[:12]} "
        f"({'match' if digest == replayed else 'MISMATCH'})"
    )


def library():
    """Which libbrotli is loaded, or what stopped it loading.

    `brotli.__version__` comes from `BrotliDecoderVersion()` rather than from
    package metadata, so it names the C library actually compiled into the wheel
    this device resolved.
    """
    if brotli is None:
        return f"brotli absent - {IMPORT_ERROR}"
    return (
        f"libbrotli {brotli.__version__} - built-in dictionary "
        f"{DICTIONARY_BYTES:,} B"
    )
