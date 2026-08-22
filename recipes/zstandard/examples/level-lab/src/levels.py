"""The zstd work behind the level lab: the payloads, the sweeps and the numbers.

Everything here returns plain values — strings, tuples, numbers — so `main.py` only
has to put them on screen.
"""

import bz2
import hashlib
import json
import lzma
import os
import platform
import time
import zlib

import zstandard as z

LEVELS = (-5, -1, 1, 2, 3, 6, 10, 15, 19)

HEAVY_LEVEL = 15

RECORDS = 2000

DICT_BYTES = 16384

CHUNK = 65536

REPEAT_BUDGET_MS = 20.0

CACHE_NAME = "level-lab.zst"


def build_info(platform_name):
    """Two header lines saying which zstd this build actually has.

    `zstandard.backend` is the one to read on a phone: both a C and a CFFI backend
    ship in every wheel and only the C one is ever selected, so `cext` there is the
    evidence that the extension loaded. `compression.zstd` is the second: Python
    3.14 grew its own zstd, and whether this app's runtime has it is a fact about
    the runtime rather than something to predict.
    """
    libzstd = ".".join(str(part) for part in z.ZSTD_VERSION)
    return (
        f"zstandard {z.__version__} · libzstd {libzstd} · backend {z.backend}",
        f"Python {platform.python_version()} · {platform_name} · "
        f"stdlib compression.zstd {_stdlib_zstd()}",
    )


def build_payload():
    """Build the deterministic blob every codec is measured on.

    Half API-shaped JSON and half log lines, because those two shapes compress very
    differently and a single-shape payload flatters whichever codec happens to suit
    it. Generated rather than bundled so the same build produces the same bytes on
    every device and two phones can be compared directly.
    """
    document = json.dumps(
        {
            "generated": "2026-08-17T12:30:05.123456",
            "records": [
                {
                    "id": f"rec-{index:05d}",
                    "sensor": f"sensor-{index % 97}",
                    "value": 1.5 + (index % 1000) / 8.0,
                    "ratio": index / 7.0,
                    "enabled": bool(index % 3),
                    "note": None if index % 5 else "threshold exceeded",
                    "position": {
                        "lat": 48.8566 + index / 10000.0,
                        "lon": 2.3522 - index / 10000.0,
                    },
                    "tags": [f"tag-{index % 7}", f"zone-{index % 4}"],
                }
                for index in range(1500)
            ],
        },
        separators=(",", ":"),
    ).encode()
    lines = b"".join(
        f"2026-08-17T12:{index % 60:02d}:{index % 59:02d}Z INFO worker-{index % 17} "
        f"handled request {index} in {index % 900}ms "
        f"status={200 if index % 11 else 500}\n".encode()
        for index in range(8000)
    )
    return document + lines


def small_records():
    """Deterministic small JSON records, for the dictionary comparison.

    Records this size are where zstd on its own is useless: every frame pays for its
    own header and has no history behind it to match against.
    """
    return [
        json.dumps(
            {
                "id": f"rec-{index:05d}",
                "sensor": f"sensor-{index % 97}",
                "site": f"site-{index % 13}/rack-{index % 41}",
                "reading": {
                    "value": 1.5 + (index % 1000) / 8.0,
                    "unit": "degC",
                    "ratio": index / 7.0,
                },
                "recorded": f"2026-08-17T12:{index % 60:02d}:{index % 59:02d}.123456Z",
                "status": "ok" if index % 3 else "threshold exceeded",
                "tags": [f"tag-{index % 7}", f"zone-{index % 4}"],
            },
            separators=(",", ":"),
        ).encode()
        for index in range(2 * RECORDS)
    ]


def timed(work):
    """Best of up to three calls of `work`, in milliseconds, plus its last result.

    Repeating is only worth it while the work is cheap. A cheap call is timed three
    times so a scheduler hiccup does not become the reported number, but level 19
    costs a quarter of a second on this payload and three of those per codec would
    turn one slider release into a visible stall.
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


def sweep(level):
    """Measure every codec at one level and return what the four result lines say.

    The compressor and the decompressor are built here, inside the call the worker
    thread makes, and neither is shared: one `ZstdCompressor` used from two threads
    at once kills the process with a native signal that no `try/except` catches, and
    one `ZstdDecompressor` quietly returns the wrong bytes.

    The checks line is what makes the timings worth printing. Every codec's output
    has to decompress back to the exact source bytes; `frame_content_size` has to
    agree with the payload length by a second route that never decompresses
    anything; and a SHA-256 of the source has to match one of the zstd round trip.
    """
    payload = build_payload()
    digest = hashlib.sha256(payload).hexdigest()

    rows, verified, zstd_frame = [], 0, None
    for index, (label, compress, decompress) in enumerate(_codecs(level)):
        compress_ms, frame = timed(lambda w=compress: w(payload))
        decompress_ms, back = timed(lambda w=decompress, f=frame: w(f))
        if back == payload:
            verified += 1
        if index == 0:  # zstd leads the table; its frame feeds the checks
            zstd_frame = frame
        rows.append(
            (
                label,
                f"{len(frame):,}",
                f"{len(payload) / len(frame):.2f}",
                f"{compress_ms:,.1f}",
                f"{decompress_ms:,.1f}",
            )
        )

    declared = z.frame_content_size(zstd_frame)
    replay = hashlib.sha256(z.ZstdDecompressor().decompress(zstd_frame)).hexdigest()
    checks = " · ".join(
        (
            f"{verified}/{len(rows)} codecs round-tripped exactly"
            + ("" if verified == len(rows) else " ← FAILURE"),
            f"frame_content_size {declared:,} vs payload {len(payload):,}"
            f" ({_agreement(declared == len(payload))})",
            f"sha256 {digest[:12]} vs {replay[:12]}"
            f" ({_agreement(digest == replay)})",
        )
    )
    memory = (
        f"level {level} reserves {_context_mb(level, len(payload)):.1f} MB to compress "
        f"{len(payload):,} B; decompression reserves "
        f"{z.estimate_decompression_context_size() / 1e3:.0f} KB at every level"
    )
    return rows, checks, memory, _stream_roundtrip(payload, level)


def dictionary_sweep(level):
    """Compress small records three ways and report bytes, ratio and milliseconds.

    The three ways are the whole point: a frame per record with no dictionary, a
    frame per record with a trained one, and every record in a single frame. The
    first is the naive shape and it barely compresses at all; the second is what a
    dictionary buys when records must stay independently addressable; the third is
    what batching buys when they need not. Returns the rows and a note carrying the
    dictionary's own id and size.
    """
    records = small_records()
    train, test = records[:RECORDS], records[RECORDS:]
    total = sum(len(record) for record in test)
    train_ms, trained = timed(lambda: z.train_dictionary(DICT_BYTES, train))

    plain = z.ZstdCompressor(level=level)
    keyed = z.ZstdCompressor(level=level, dict_data=trained)
    batch = z.ZstdCompressor(level=level)
    joined = b"".join(test)
    rows = []
    for label, work in (
        ("frame per record", lambda: [plain.compress(r) for r in test]),
        ("+ dictionary", lambda: [keyed.compress(r) for r in test]),
        ("all in one frame", lambda: [batch.compress(joined)]),
    ):
        elapsed, frames = timed(work)
        size = sum(len(frame) for frame in frames)
        rows.append((label, f"{size:,}", f"{total / size:.2f}", f"{elapsed:,.1f}"))

    note = (
        f"{total:,} B of records · dict id {trained.dict_id()}, "
        f"{len(trained.as_bytes()):,} B, trained in {train_ms:,.1f} ms · "
        f"wrong dictionary → {_mismatch_message(trained, records, level)}"
    )
    return rows, note


def _stdlib_zstd():
    """The libzstd version this Python's own `compression.zstd` carries, if any."""
    try:
        from compression import zstd
    except ImportError:
        return "absent"
    return zstd.zstd_version


def _codecs(level):
    """Label, compress and decompress for every codec in the table."""
    return (
        (
            f"zstd {level}",
            lambda data: z.ZstdCompressor(level=level).compress(data),
            lambda frame: z.ZstdDecompressor().decompress(frame),
        ),
        ("zlib 9", lambda data: zlib.compress(data, 9), zlib.decompress),
        ("bz2 9", lambda data: bz2.compress(data, 9), bz2.decompress),
        ("lzma p1", lambda data: lzma.compress(data, preset=1), lzma.decompress),
    )


def _agreement(ok):
    """Word for a check that either agreed or did not, loud in the second case."""
    return "match" if ok else "MISMATCH"


def _context_mb(level, source_size):
    """Memory zstd reserves to compress `source_size` bytes at `level`, in MB.

    Read off the library rather than quoted from a benchmark, because this is the
    one number on the dial that can kill the app instead of merely being slow.
    Decimal MB, so it can be compared with what a package index reports.
    """
    params = z.ZstdCompressionParameters.from_level(level, source_size=source_size)
    return params.estimated_compression_context_size() / 1e6


def _mismatch_message(trained, records, level):
    """What decompressing a dictionary frame with the wrong dictionary does.

    Shown because the answer is the reassuring one: the dictionary id travels in the
    frame header, so the wrong dictionary raises instead of handing back
    plausible-looking garbage.
    """
    frame = z.ZstdCompressor(level=level, dict_data=trained).compress(records[-1])
    other = z.train_dictionary(DICT_BYTES, records[RECORDS:])
    try:
        z.ZstdDecompressor(dict_data=other).decompress(frame)
        return "no error raised — unexpected"
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def _stream_roundtrip(payload, level):
    """Write one frame to the app cache with `size=`, read it back in chunks.

    Two habits in one pass. Passing `size=` puts the content size in the frame
    header, which keeps a high level from reserving a huge compression context and
    lets a plain `decompress()` read the file back later. Reading through
    `stream_reader` in fixed chunks is what keeps an oversized frame from
    materialising in a single allocation. The file is removed again, because this is
    a demonstration and not a cache.
    """
    directory = os.getenv("FLET_APP_STORAGE_CACHE", ".")
    path = os.path.join(directory, CACHE_NAME)
    cctx = z.ZstdCompressor(level=level, write_checksum=True)
    started = time.perf_counter()
    with open(path, "wb") as handle:
        with cctx.stream_writer(handle, size=len(payload)) as writer:
            writer.write(payload)
    written = os.path.getsize(path)
    read_back = 0
    with open(path, "rb") as handle:
        reader = z.ZstdDecompressor().stream_reader(handle)
        while True:
            chunk = reader.read(CHUNK)
            if not chunk:
                break
            read_back += len(chunk)
    elapsed = (time.perf_counter() - started) * 1000.0
    with open(path, "rb") as handle:
        declared = z.frame_content_size(handle.read(32))
    os.remove(path)
    return (
        f"cache file {written:,} B, declared content size {declared:,}, "
        f"read back {read_back:,} B in {CHUNK:,}-byte chunks, {elapsed:,.1f} ms total"
    )
