"""Everything the app does with safetensors: write a weights file, then read it three ways."""

import hashlib
import json
import os
import platform
import resource
import struct
import time

import numpy as np
import safetensors
from safetensors import safe_open
from safetensors.numpy import load_file, save_file

DATA_DIR = os.getenv("FLET_APP_STORAGE_DATA", ".")
MODEL = os.path.join(DATA_DIR, "demo.safetensors")
MODEL_NAME = os.path.basename(MODEL)
PROBE = os.path.join(DATA_DIR, "probe.safetensors")
SEED = 20260818
BLOCKS = 12
SIDE = 1024

VERSION = (
    f"safetensors {safetensors.__version__} · numpy {np.__version__} · "
    f"Python {platform.python_version()} · {platform.machine()} · backend=mmap"
)

# ru_maxrss counts bytes on Darwin kernels and kilobytes on Linux ones, so getting
# this wrong is a 1024x error between iOS and Android. uname() asks the kernel,
# which settles it without depending on what platform.system() reports.
RSS_UNIT = 1 if os.uname().sysname == "Darwin" else 1024

# sha256 of every block and of its first row, taken before anything is written.
# Nothing read back off disk is ever trusted to describe itself.
MARKS = {}


def peak_mb():
    """Peak resident set size in MB — a high-water mark, so it never falls back."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * RSS_UNIT / 1e6


def digest(array):
    """sha256 over a contiguous array's own bytes: exact, and copies nothing."""
    return hashlib.sha256(memoryview(array)).hexdigest()[:12]


def build_blocks():
    """The float32 blocks the file is written from, regenerated from a fixed seed.

    ascontiguousarray is the load-bearing call. safetensors reads `nbytes` straight
    from a tensor's data pointer and checks nothing, so a strided view would be
    written as silent garbage.
    """
    rng = np.random.default_rng(SEED)
    return {
        f"block.{index:02d}": np.ascontiguousarray(
            rng.standard_normal((SIDE, SIDE), dtype=np.float32)
        )
        for index in range(BLOCKS)
    }


def python_header(path):
    """The safetensors header read with nothing but struct and json.

    A model picker listing candidate files needs no more than this, and therefore
    need not load the extension at all.
    """
    with open(path, "rb") as handle:
        length = struct.unpack("<Q", handle.read(8))[0]
        return json.loads(handle.read(length))


def write_file():
    """Write the file, fingerprinting every block on the way in."""
    blocks = build_blocks()
    for name, block in blocks.items():
        MARKS[name] = (digest(block), digest(block[0:1]))
    save_file(blocks, MODEL, metadata={"blocks": str(BLOCKS), "seed": str(SEED)})
    del blocks
    return {"size": os.path.getsize(MODEL), "peak": peak_mb()}


def read_header():
    """Open the file and read only its header — once through safe_open, once by hand."""
    started = time.perf_counter()
    with safe_open(MODEL, framework="numpy") as handle:
        meta = handle.metadata()
        tensors = []
        for name in handle.keys():
            view = handle.get_slice(name)
            shape = tuple(view.get_shape())
            # get_dtype() returns the format's own code ("F32"), not a numpy dtype;
            # every block here is float32, so 4 bytes per element.
            tensors.append((name, shape, view.get_dtype(), int(np.prod(shape)) * 4))
    opened = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    python_header(MODEL)
    plain = (time.perf_counter() - started) * 1000

    return {
        "meta": meta,
        "tensors": tensors,
        "declared": sum(nbytes for *_, nbytes in tensors),
        "opened": opened,
        "plain": plain,
        "peak": peak_mb(),
    }


def read_row(index):
    """Pull row 0 out of one block and check it against the fingerprint kept at write time."""
    name = f"block.{index:02d}"
    started = time.perf_counter()
    with safe_open(MODEL, framework="numpy") as handle:
        view = handle.get_slice(name)
        whole = int(np.prod(view.get_shape())) * 4
        row = view[0:1]
    return {
        "name": name,
        "bytes": row.nbytes,
        "whole": whole,
        "first": float(row[0, 0]),
        "matches": digest(row) == MARKS[name][1],
        "ms": (time.perf_counter() - started) * 1000,
        "peak": peak_mb(),
    }


def read_all():
    """Load every tensor and cross-check all of them — the expensive path, for contrast."""
    started = time.perf_counter()
    loaded = load_file(MODEL)
    elapsed = (time.perf_counter() - started) * 1000
    matched = sum(digest(loaded[name]) == MARKS[name][0] for name in loaded)
    del loaded
    return {"matched": matched, "total": BLOCKS, "ms": elapsed, "peak": peak_mb()}


def damage_probe():
    """Damage a small copy two ways and report which of the two the format can detect."""
    probe = np.ascontiguousarray(np.arange(256, dtype=np.float32).reshape(16, 16))
    save_file({"probe": probe}, PROBE)
    with open(PROBE, "rb") as handle:
        raw = handle.read()
    length = struct.unpack("<Q", raw[:8])[0]
    start = 8 + length + json.loads(raw[8 : 8 + length])["probe"]["data_offsets"][0]

    cut = PROBE + ".cut"
    with open(cut, "wb") as handle:
        handle.write(raw[:-64])
    try:
        with safe_open(cut, framework="numpy") as handle:
            handle.keys()
        truncated = "opened without complaint"
    except Exception as error:
        # Neither family is an OSError, so the catch has to be broad.
        truncated = f"{type(error).__name__}: {error}"

    rotted = bytearray(raw)
    rotted[start + 3] ^= 0x40  # one bit of probe[0, 0]'s exponent
    flipped = PROBE + ".flipped"
    with open(flipped, "wb") as handle:
        handle.write(bytes(rotted))
    with safe_open(flipped, framework="numpy") as handle:
        got = handle.get_tensor("probe")

    for path in (cut, flipped, PROBE):
        os.unlink(path)
    return {
        "truncated": truncated,
        "written": float(probe[0, 0]),
        "read_back": float(got[0, 0]),
        "digest_match": digest(got) == digest(probe),
    }
