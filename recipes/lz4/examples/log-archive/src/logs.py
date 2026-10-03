import functools
import os
import random
import tempfile
import time
from dataclasses import dataclass

import lz4
import lz4.frame

# Below 3 is LZ4's fast codec; 3 and up is LZ4-HC, which liblz4 caps at 12.
LEVELS = {"Fast": 0, "HC 9": 9, "HC 12": 12}
CHUNK = 1 << 20


@dataclass
class Archive:
    raw: int
    packed: int
    write_s: float
    read_s: float
    intact: bool
    path: str


def library_version():
    """Version of the liblz4 compiled into the wheel."""
    return lz4.library_version_string()


@functools.cache
def sample_log(lines=60_000, seed=0):
    """Build a deterministic app log of about 4 MB, standing in for a real one.

    Seeded so every run compresses the same bytes and the levels compare fairly;
    cached so only the first tap pays for generating it.
    """
    rng = random.Random(seed)
    levels = ["DEBUG", "INFO", "INFO", "INFO", "WARN", "ERROR"]
    routes = ["/feed", "/profile", "/search", "/upload", "/settings"]
    stamp = 1_760_000_000.0
    out = []
    for i in range(lines):
        stamp += rng.expovariate(20)
        out.append(
            f"{stamp:.3f} {rng.choice(levels):5} req={i:06d} "
            f"route={rng.choice(routes)} status={rng.choice((200, 200, 304, 404, 500))} "
            f"ms={rng.randint(3, 900)}\n"
        )
    return "".join(out).encode()


def archive(data, level):
    """Write `data` to an .lz4 file at `level` a megabyte at a time, then read it
    back the same way, timing both ends and checking every byte.

    Chunked in both directions because that is how a log too large to hold twice
    would be handled; lz4.frame.open compresses as it is written to.
    """
    directory = os.getenv("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()
    path = os.path.join(directory, "app-log.lz4")
    view = memoryview(data)

    started = time.perf_counter()
    with lz4.frame.open(path, "wb", compression_level=level) as f:
        for i in range(0, len(data), CHUNK):
            f.write(view[i : i + CHUNK])
    write_s = time.perf_counter() - started

    started = time.perf_counter()
    intact, pos = True, 0
    with lz4.frame.open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            intact &= view[pos : pos + len(chunk)] == chunk
            pos += len(chunk)
    read_s = time.perf_counter() - started

    return Archive(
        len(data), os.path.getsize(path), write_s, read_s, intact and pos == len(data), path
    )
