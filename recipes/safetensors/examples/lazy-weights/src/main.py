"""Reads a 48 MB weights file four ways on device and prints what each one costs."""

import hashlib
import json
import os
import platform
import resource
import struct
import time

import flet as ft
import numpy as np
import safetensors
from safetensors import safe_open
from safetensors.numpy import load_file, save_file

DATA_DIR = os.getenv("FLET_APP_STORAGE_DATA", ".")
MODEL = os.path.join(DATA_DIR, "demo.safetensors")
PROBE = os.path.join(DATA_DIR, "probe.safetensors")
SEED = 20260818
BLOCKS = 12
SIDE = 1024

# ru_maxrss counts bytes on Darwin kernels and kilobytes on Linux ones. uname() asks the
# kernel, so it settles this without depending on what platform.system() reports for the
# Python version in use.
RSS_UNIT = 1 if os.uname().sysname == "Darwin" else 1024


def peak_mib():
    """Peak resident set size in MiB — a high-water mark, so it never falls back."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * RSS_UNIT / (1 << 20)


def digest(array):
    """sha256 over a contiguous array's own bytes: exact, and copies nothing."""
    return hashlib.sha256(memoryview(array)).hexdigest()[:12]


def build_blocks():
    """The 12 float32 blocks the file gets written from, regenerated from a fixed seed.

    ascontiguousarray is the load-bearing call here. safetensors reads `nbytes` straight
    from a tensor's data pointer and checks nothing, so a strided view would be written as
    silent garbage.
    """
    rng = np.random.default_rng(SEED)
    return {
        f"block.{i:02d}": np.ascontiguousarray(
            rng.standard_normal((SIDE, SIDE), dtype=np.float32)
        )
        for i in range(BLOCKS)
    }


def python_header(path):
    """The safetensors header read with nothing but struct and json.

    A model picker listing candidate files needs no more than this, and therefore need not
    load the extension at all.
    """
    with open(path, "rb") as handle:
        length = struct.unpack("<Q", handle.read(8))[0]
        return json.loads(handle.read(length))


def main(page: ft.Page):
    """One screen that writes a weights file, then reads it four ways.

    Every stage prints elapsed time and peak resident memory beside its result, and every
    value read back is checked against a fingerprint taken from the arrays *before* they
    were written — the file is never trusted to describe itself.
    """
    marks = {}

    def prepare():
        """Write the file, remember what went into it, then read back only the header."""
        blocks = build_blocks()
        for name, block in blocks.items():
            marks[name] = (digest(block), digest(block[0:1]))
        save_file(blocks, MODEL, metadata={"blocks": str(BLOCKS), "seed": str(SEED)})
        del blocks
        built.value = (
            f"1 · wrote {os.path.getsize(MODEL) / (1 << 20):.2f} MB to "
            f"{os.path.basename(MODEL)}, peak {peak_mib():.1f} MiB"
        )

        started = time.perf_counter()
        with safe_open(MODEL, framework="numpy") as handle:
            meta = handle.metadata()
            shapes = []
            for name in handle.keys():
                view = handle.get_slice(name)
                shapes.append((name, tuple(view.get_shape()), view.get_dtype()))
        opened = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        python_header(MODEL)
        plain = (time.perf_counter() - started) * 1000

        declared = sum(int(np.prod(shape)) * 4 for _, shape, _ in shapes)
        header.value = (
            f"2 · header only: {len(shapes)} tensors declaring "
            f"{declared / (1 << 20):.2f} MB of tensor data, metadata={meta} — "
            f"{opened:.3f} ms via safe_open, {plain:.3f} ms with struct+json alone, "
            f"peak {peak_mib():.1f} MiB"
        )
        table.value = "\n".join(
            f"{name}  {shape}  {dtype}  {int(np.prod(shape)) * 4 / (1 << 10):.0f} KiB"
            for name, shape, dtype in shapes
        )

    def read_slice():
        """Pull one 4 KiB row out of one 4 MiB tensor and check it against its fingerprint."""
        name = f"block.{int(slider.value):02d}"
        started = time.perf_counter()
        with safe_open(MODEL, framework="numpy") as handle:
            view = handle.get_slice(name)
            whole = int(np.prod(view.get_shape())) * 4
            row = view[0:1]
        elapsed = (time.perf_counter() - started) * 1000
        verdict = "matches" if digest(row) == marks[name][1] else "DOES NOT MATCH"
        sliced.value = (
            f"3 · {name} row 0: {row.nbytes / (1 << 10):.0f} KiB out of a "
            f"{whole / (1 << 20):.0f} MiB tensor, first value {row[0, 0]:+.6f} — {verdict} "
            f"what was written, {elapsed:.3f} ms, peak {peak_mib():.1f} MiB"
        )

    def load_all():
        """Load every tensor and cross-check all twelve — the expensive path, for contrast."""
        started = time.perf_counter()
        loaded = load_file(MODEL)
        elapsed = (time.perf_counter() - started) * 1000
        matched = sum(digest(loaded[name]) == marks[name][0] for name in loaded)
        del loaded
        loaded_line.value = (
            f"4 · load_file: {matched}/{BLOCKS} tensors match what was written, "
            f"{elapsed:.1f} ms, peak {peak_mib():.1f} MiB"
        )

    def damage():
        """Damage a small copy two ways and show that only one of them is detectable."""
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
            first = "truncated copy: opened without complaint"
        except Exception as error:
            first = f"truncated copy: {type(error).__name__}: {error}"

        rotted = bytearray(raw)
        rotted[start + 3] ^= 0x40  # one bit of probe[0, 0]'s exponent
        flipped = PROBE + ".flipped"
        with open(flipped, "wb") as handle:
            handle.write(bytes(rotted))
        with safe_open(flipped, framework="numpy") as handle:
            got = handle.get_tensor("probe")

        for path in (cut, flipped, PROBE):
            os.unlink(path)
        damaged.value = (
            f"5 · {first}\n"
            f"     bit-flipped copy: opened cleanly, probe[0, 0] = {got[0, 0]:g} where "
            f"{probe[0, 0]:g} was written — digest match "
            f"{digest(got) == digest(probe)}"
        )

    def work(body, *controls):
        """Run body in the thread pool with controls disabled and the spinner up.

        page.run_thread never retrieves the worker's future, so anything the body raised
        would otherwise vanish without a trace; catching it here puts it on screen.
        """

        def run():
            """The worker, plus the update a background thread has to issue itself."""
            try:
                body()
            except Exception as error:
                status.value = f"{type(error).__name__}: {error}"
            finally:
                for control in controls:
                    control.disabled = False
                spinner.visible = False
                page.update()

        status.value = ""
        for control in controls:
            control.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def pick():
        """Slider release: one read per gesture, rather than one per pixel dragged."""
        work(read_slice, slider)

    def load_everything():
        """The whole-file button."""
        work(load_all, load_button)

    def break_a_copy():
        """The corruption button."""
        work(damage, damage_button)

    page.appbar = ft.AppBar(
        title=ft.Text("safetensors lazy weights"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"safetensors {safetensors.__version__} · numpy {np.__version__} · "
                        f"Python {platform.python_version()} · {page.platform.value} "
                        f"{platform.machine()} · backend=mmap",
                        size=11,
                    ),
                    built := ft.Text("1 · building…"),
                    header := ft.Text("2 · waiting for the file"),
                    table := ft.Text("", size=11, font_family="monospace"),
                    ft.Row(
                        controls=[
                            ft.Text("block"),
                            slider := ft.Slider(
                                min=0,
                                max=BLOCKS - 1,
                                divisions=BLOCKS - 1,
                                label="{value}",
                                expand=True,
                                on_change_end=pick,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    sliced := ft.Text("3 · drag the slider to read one row"),
                    loaded_line := ft.Text("4 · not loaded yet"),
                    damaged := ft.Text("5 · not damaged yet"),
                    ft.Row(
                        # Both labels on one line measure 353 dp; a 360 dp-wide phone
                        # (the whole Galaxy S/A range) leaves 340 after the page padding.
                        wrap=True,
                        controls=[
                            load_button := ft.Button(
                                "Load every tensor",
                                icon=ft.Icons.DOWNLOAD_FOR_OFFLINE,
                                on_click=load_everything,
                            ),
                            damage_button := ft.Button(
                                "Damage a copy",
                                icon=ft.Icons.BROKEN_IMAGE,
                                on_click=break_a_copy,
                            ),
                        ],
                    ),
                    status := ft.Text("", color=ft.Colors.ERROR),
                ],
            ),
        )
    )
    work(prepare, slider, load_button, damage_button)


if __name__ == "__main__":
    ft.run(main)
