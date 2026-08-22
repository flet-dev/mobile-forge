"""Render a matplotlib heat map to PNG bytes and show it in a Flet Image."""

import os

# matplotlib resolves its config/cache directory once, at import. Point it at app
# storage before anything imports matplotlib, or it falls back to a fresh temp
# directory on every launch and rebuilds its font cache each time.
_MPL_DIR = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "matplotlib")
os.makedirs(_MPL_DIR, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", _MPL_DIR)

import flet as ft  # noqa: E402
from radio import VERSION, render  # noqa: E402


def main(page: ft.Page):
    """Show a path-loss slider over a heat map that is re-rendered on release."""

    def show_exponent():
        """Report the exponent the next render will use, while the slider moves."""
        caption.value = f"Path-loss exponent: {exponent.value:.1f}"

    def redraw():
        """Start a render on a background thread, with the slider locked.

        Bound to `on_change_end`, not `on_change`: a render takes long enough
        that firing one per slider tick would queue up work nobody asked for.
        """
        show_exponent()
        exponent.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(draw)

    def draw():
        """Render at the slider's exponent and put the PNG on screen.

        The body of the thread redraw() starts. Raising the exponent shrinks
        each transmitter's reach, so the contours pull in towards the markers
        and the corners of the room go dark.
        """
        png, seconds = render(exponent.value)
        plot.src = png
        plot.visible = True
        stats.value = f"{len(png) / 1000:.0f} KB PNG rendered in {seconds:.2f} s"
        exponent.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("matplotlib heat map"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(VERSION, size=12),
                    caption := ft.Text(),
                    ft.Row(
                        controls=[
                            exponent := ft.Slider(
                                min=1.5,
                                max=4.0,
                                value=2.0,
                                divisions=25,
                                round=1,
                                label="{value}",
                                expand=True,
                                on_change=show_exponent,
                                on_change_end=redraw,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    plot := ft.Image(
                        src=b"",
                        visible=False,
                        fit=ft.BoxFit.CONTAIN,
                        gapless_playback=True,
                    ),
                    stats := ft.Text(size=12),
                ]
            ),
        )
    )

    redraw()


if __name__ == "__main__":
    ft.run(main)
