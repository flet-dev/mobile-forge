from collections import namedtuple

import flet as ft
from barcodes import (
    MAX_FLIPS,
    blocked_reason,
    build_symbols,
    capability_report,
    library_line,
    round_trip,
    to_png,
)

Card = namedtuple("Card", "image report")


def symbol_card():
    """The picture and the report line for one symbol, made once so the image swaps in place.

    `ft.Image` needs a `src` at construction and nothing has been rasterised yet,
    so it starts on a one-pixel PNG that the first redraw replaces — which is
    what `gapless_playback` is for.
    """
    return Card(
        image=ft.Image(
            src=to_png(b"\xff", 1, 1),
            gapless_playback=True,
            filter_quality=ft.FilterQuality.NONE,
            fit=ft.BoxFit.CONTAIN,
        ),
        report=ft.Text(size=12, selectable=True),
    )


def main(page: ft.Page):
    """Encode three barcodes, decode them back, and report whether each round trip held.

    Everything is computed on the device: no camera, no network, no assets and no
    image library. The slider damages whole modules before rasterising, which is
    what separates a symbology that only detects errors from one that corrects
    them.
    """
    symbols = build_symbols()
    cards = [symbol_card() for _ in symbols]

    def render():
        """Run all three round trips at the current slider and switch settings."""
        decoded_types = set()
        for symbol, card in zip(symbols, cards):
            report = round_trip(symbol, int(damage.value), bool(turn.value))
            decoded_types.add(report.type)
            card.image.src = report.png
            card.image.height = report.display_height
            card.report.value = "\n".join(report.lines)
        decoded_types.discard(None)
        capability.value = capability_report(decoded_types)

    def preview():
        """Caption the damage level under the thumb while the slider is still moving."""
        flips = int(damage.value)
        caption.value = (
            f"{flips} module{'' if flips == 1 else 's'} inverted before rasterising"
        )

    def redraw():
        """Re-run the round trips after the slider is released or the switch is flipped."""
        preview()
        render()

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
                        library_line(page.platform.value), size=11, selectable=True
                    ),
                    caption := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    damage := ft.Slider(
                        value=0,
                        min=0,
                        max=MAX_FLIPS,
                        divisions=MAX_FLIPS,
                        label="{value}",
                        # on_change would re-rasterise and re-decode three symbols for
                        # every pixel the thumb travels; on_change_end runs it once.
                        on_change=preview,
                        on_change_end=redraw,
                    ),
                    turn := ft.Switch(label="rotate 90° clockwise", on_change=redraw),
                    *[
                        ft.Column(spacing=4, controls=[card.image, card.report])
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
