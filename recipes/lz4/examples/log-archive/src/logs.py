import functools
import os
import random
import tempfile
import time
from dataclasses import dataclass

import lz4.frame

# Below 3 is LZ4's fast codec; 3 to 16 is LZ4-HC. Decompression speed is the same for all.
LEVELS = {"Fast": 0, "HC 9": 9, "HC 16": lz4.frame.COMPRESSIONLEVEL_MAX}


@dataclass
class Archive:
    raw: int
    packed: int
    write_s: float
    read_s: float
    intact: bool
    path: str


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
    """Stream `data` into an .lz4 file at `level`, read it back, and time both ends.

    lz4.frame.open writes the standard LZ4 frame format, so the file also opens with
    the lz4 command-line tool once copied off the device.
    """
    directory = os.getenv("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()
    path = os.path.join(directory, "app-log.lz4")

    started = time.perf_counter()
    with lz4.frame.open(path, "wb", compression_level=level) as f:
        f.write(data)
    write_s = time.perf_counter() - started

    started = time.perf_counter()
    with lz4.frame.open(path, "rb") as f:
        restored = f.read()
    read_s = time.perf_counter() - started

    return Archive(
        len(data), os.path.getsize(path), write_s, read_s, restored == data, path
    )
