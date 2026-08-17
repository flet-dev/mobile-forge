"""Render a matplotlib heat map to PNG bytes and show it in a Flet Image."""

import io
import os
import time

# matplotlib resolves its config/cache directory once, at import. Point it at app
# storage before anything imports matplotlib, or it falls back to a fresh temp
# directory on every launch and rebuilds its font cache each time.
_MPL_DIR = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "matplotlib")
os.makedirs(_MPL_DIR, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", _MPL_DIR)

import flet as ft  # noqa: E402
import matplotlib  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ft2font import __freetype_version__  # noqa: E402

SIDE = 40.0
GRID = 240
DPI = 160
FIGSIZE = (4.4, 4.0)

# (x, y, watts) of the transmitters the survey is measuring.
SOURCES = [(8.0, 30.0, 1.0), (30.0, 27.0, 0.6), (21.0, 9.0, 0.35)]

_axis = np.linspace(0.0, SIDE, GRID)
_x, _y = np.meshgrid(_axis, _axis)


def survey(exponent):
    """Received power over the whole grid, in dBm, for one path-loss exponent.

    Free space loses power with the square of distance; walls and floors push
    the exponent up, which is what the slider varies. The 0.5 m floor keeps the
    field finite at a transmitter's own position.
    """
    watts = sum(
        p / np.maximum(np.hypot(_x - sx, _y - sy), 0.5) ** exponent
        for sx, sy, p in SOURCES
    )
    return 10.0 * np.log10(watts) + 30.0


def render(exponent):
    """Draw the survey as a PNG and return the bytes, with how long it took.

    Builds the figure through `Figure` and `FigureCanvasAgg` instead of pyplot.
    pyplot keeps a global registry of open figures, which makes it both unsafe
    to drive from a background thread and a steady leak — every figure it
    creates stays alive until something closes it. Constructing the canvas is
    what attaches Agg to the figure; the return value is deliberately unused.
    """
    started = time.monotonic()
    figure = Figure(figsize=FIGSIZE, dpi=DPI, layout="constrained")
    FigureCanvasAgg(figure)

    axes = figure.add_subplot()
    field = survey(exponent)
    image = axes.imshow(
        field, origin="lower", extent=(0, SIDE, 0, SIDE), cmap="viridis"
    )
    axes.contour(_x, _y, field, levels=8, colors="white", linewidths=0.4, alpha=0.6)
    axes.plot(
        [s[0] for s in SOURCES],
        [s[1] for s in SOURCES],
        "o",
        color="white",
        markeredgecolor="black",
        markersize=7,
    )
    axes.set_title(f"path-loss exponent {exponent:.1f}")
    axes.set_xlabel("metres")
    axes.set_ylabel("metres")
    figure.colorbar(image, ax=axes, label="received power (dBm)")

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    return buffer.getvalue(), time.monotonic() - started


def main(page: ft.Page):
    """Show a path-loss slider over a heat map that is re-rendered on release.

    The header reports the FreeType version ft2font was built with. It is
    matplotlib's own bundled copy, statically linked, the same on device as on
    a desktop — which is why every label in the figure lays out identically.
    """

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
        stats.value = f"{len(png) / 1024:.0f} KB PNG rendered in {seconds:.2f} s"
        exponent.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("matplotlib heat map"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"matplotlib {matplotlib.__version__} — FreeType "
                        f"{__freetype_version__} — {GRID}×{GRID} grid, Agg",
                        size=12,
                    ),
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
