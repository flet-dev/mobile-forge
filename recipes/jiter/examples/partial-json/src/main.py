import time

import flet as ft
from stream import DOCUMENT, MODES, VERSION, decode, measure, outline, prefixes, stdlib

PACE = 0.05  # seconds between simulated chunks


def row(label, value):
    """One line of the comparison table: a label and the measured value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3, size=12), ft.Text(value, expand=2, size=12)]
    )


def main(page: ft.Page):
    """Replay a JSON document chunk by chunk and parse every prefix of it."""
    state = {"mode": "trailing-strings"}

    def on_mode(e):
        """Switch partial mode and replay the stream under it."""
        state["mode"] = e.control.selected[0]  # 0.86: selected is a list, not a set
        start()

    def start():
        """Lock the controls and hand the replay to a background thread.

        The mode buttons lock too. run_thread uses a pool, so a mode changed
        mid-replay would start a second feed() writing the same controls.
        """
        button.disabled = True
        modes.disabled = True
        spinner.visible = True
        results.controls = []
        page.update()
        page.run_thread(feed)

    def feed():
        """Show every growing prefix to both parsers, then compare them on bulk.

        The loop is deliberately naive: it re-parses the whole buffer on every
        chunk. That is fine for a few hundred bytes at 20 frames a second, and
        it is the wrong shape for a megabyte -- the work per chunk grows with
        the buffer, so a long stream wants a slower cadence than this one.
        """
        for prefix in prefixes():
            value, error = decode(prefix, state["mode"])
            refused = stdlib(prefix)
            # errors="replace" because a real stream cuts UTF-8 characters in half
            wire.value = prefix.decode(errors="replace")
            received.value = f"{len(prefix)} of {len(DOCUMENT)} bytes"
            fields.value = (
                ("\n".join(outline(value)) or "nothing decodable yet")
                if value is not None
                else error
            )
            blocked.value = f"json.loads: {refused or 'parsed'}"
            blocked.color = ft.Colors.ERROR if refused else ft.Colors.PRIMARY
            page.update()
            time.sleep(PACE)

        size, timings, unique = measure()
        results.controls = [
            row(f"parsing {size // 1024} KB of repetitive JSON", ""),
            ft.Divider(height=1),
            *(row(label, f"{ms:.1f} ms") for label, ms in timings),
            ft.Divider(height=1),
            row("distinct str objects, cache_mode='all'", str(unique["all"])),
            row("distinct str objects, cache_mode='none'", str(unique["none"])),
        ]
        button.disabled = False
        modes.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Partial JSON"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    modes := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=mode, label=ft.Text(mode.split("-")[0]))
                            for mode in MODES
                        ],
                        selected=["trailing-strings"],
                        show_selected_icon=False,
                        on_change=on_mode,
                    ),
                    received := ft.Text(size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Container(
                        height=96,
                        padding=8,
                        border_radius=6,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        content=(wire := ft.Text(size=10)),
                    ),
                    blocked := ft.Text(size=11),
                    fields := ft.Text(size=11),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Stream again",
                                icon=ft.Icons.REPLAY,
                                on_click=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=20,
                                height=20,
                                visible=False,
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
