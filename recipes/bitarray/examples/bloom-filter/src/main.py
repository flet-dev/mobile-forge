"""A Bloom filter on bitarray: its bits drawn as a bitmap, its error rate measured."""

import flet as ft
from bloom import BITS, KEY_COUNTS, PROBES, ROWS, SIDE, VERSION, analyse, hash_count


def hashes_phrase(hashes):
    """`hashes` as English, since the bottom of the ladder really does use one."""
    return "1 hash" if hashes == 1 else f"{hashes} hashes"


def caption_for(keys):
    """The slider's label: which filter this position stands for."""
    return f"{keys:,} members in {BITS:,} bits — {hashes_phrase(hash_count(keys))} each"


def rate_text(value):
    """A probability printed so that a very small one stays legible.

    The ladder spans about one error in two to one in two hundred thousand.
    """
    if value == 0:
        return "0"
    return f"{value:.5f}" if value >= 1e-4 else f"{value:.2e}"


def line(label, value):
    """One result row, laid out so neither half can overflow a phone-width screen."""
    return ft.Row(
        controls=[
            ft.Text(label, size=11, expand=2, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(value, size=11, expand=5),
        ]
    )


def report(found):
    """Turn one `analyse` result into the label/value rows under the bitmap."""
    agrees = abs(found["wrong"] - found["expected"]) <= found["margin"]
    band = f"{found['expected']:,.1f} ± {found['margin']:,.1f} expected"
    memory = (
        f"{found['nbytes']:,} B filter vs {found['set_bytes']:,} B for set(keys) — "
        f"{found['set_bytes'] / found['nbytes']:,.0f}× · [False] × {BITS:,} is "
        f"{found['list_bytes']:,} B"
    )
    stored = (
        f"serialize {found['serialized']:,} B · sc_encode "
        f"{found['compressed']:,} B · this PNG {len(found['image']):,} B"
    )
    cost = (
        f"insert {found['build_ms']:.0f} ms · {PROBES:,} probes "
        f"{found['probe_ms']:.0f} ms · bitmap {found['draw_ms']:.1f} ms"
    )
    rows = (
        ("filter", f"{BITS:,} bits · {found['nbytes']:,} B · {SIDE}×{ROWS} px"),
        ("members", f"{found['keys']:,} keys · {hashes_phrase(found['hashes'])} each"),
        ("bits set", f"{found['set_bits']:,} ({found['fill']:.1%} full)"),
        ("false positives", f"{found['wrong']:,} of {PROBES:,} non-members"),
        ("measured rate", rate_text(found["measured"])),
        ("fill^k predicts", f"{rate_text(found['predicted'])} → {band}"),
        ("agreement", "inside the 95% band" if agrees else "OUTSIDE the 95% band"),
        ("memory", memory),
        ("to store", stored),
        ("cost here", cost),
    )
    return [line(label, value) for label, value in rows]


def main(page: ft.Page):
    """Show one Bloom filter at a time, and rebuild it when the slider is released.

    Every pass goes through `page.run_thread`, the first one included: a synchronous
    `main` runs on Flet's event loop thread, so a pass computed inline here would hold
    the layout `page.add` queued until `main` returns — 980 ms of blank screen, measured
    on a desktop.
    """

    def refresh(keys):
        """Run one pass and move every control that depends on it."""
        found = analyse(keys)
        picture.src = found["image"]
        picture.visible = True
        results.controls = report(found)
        caption.value = caption_for(keys)
        header.value = f"{VERSION} · {found['endian']}-endian · {page.platform.value}"

    def worker(keys):
        """The whole of a pass, off the event loop thread.

        `page.run_thread` never retrieves the worker's future, so an exception raised
        here would vanish without a log, a dialog or a crash — hence the bare `except`;
        and auto-update does not reach a background thread, so the explicit
        `page.update()` is what redraws the screen.
        """
        try:
            refresh(keys)
        except Exception as error:
            results.controls = [line("failed", f"{type(error).__name__}: {error}")]
        finally:
            size.disabled = False
            page.update()

    def rebuild():
        """Start a pass on the slider's position, with the slider locked.

        Locking is what keeps two passes from overlapping: `run_thread` submits to a
        shared pool, so a second release during a run would genuinely execute alongside
        the first and both would write these same controls.
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
                    header := ft.Text(VERSION, size=11),
                    ft.Container(
                        border=ft.Border.all(1, ft.Colors.OUTLINE),
                        width=SIDE,
                        height=ROWS,
                        content=(
                            picture := ft.Image(
                                src=b"",
                                width=SIDE,
                                height=ROWS,
                                visible=False,
                                gapless_playback=True,
                                filter_quality=ft.FilterQuality.NONE,
                            )
                        ),
                    ),
                    ft.Text(
                        "one pixel per bit — the PNG's pixel data is the buffer itself",
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
                    results := ft.Column(spacing=2),
                ],
            ),
        )
    )

    rebuild()


if __name__ == "__main__":
    ft.run(main)
