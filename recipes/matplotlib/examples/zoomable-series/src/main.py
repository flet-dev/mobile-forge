"""Show a live matplotlib figure you can pan and zoom, via flet-charts' MatplotlibChart."""

import os

# matplotlib resolves its config/cache directory once, at import — and importing
# flet_charts imports matplotlib. Point it at app storage before either, or it
# falls back to a fresh temp directory on every launch.
_MPL_DIR = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "matplotlib")
os.makedirs(_MPL_DIR, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", _MPL_DIR)

import flet as ft  # noqa: E402
import flet_charts as fch  # noqa: E402
from series import (  # noqa: E402
    DEFAULT_WINDOW,
    WINDOWS,
    build_figure,
    readings,
    set_window,
)


def main(page: ft.Page):
    """Put the series in a chart you can pan and zoom, with a smoothing selector.

    The toolbar is three of our own buttons driving the chart's navigation
    methods, rather than flet_charts' ready-made MatplotlibChartWithToolbar:
    that composite lays its eight controls out in one non-scrolling Row, which
    overflows a phone-width screen.
    """
    values = readings()
    figure, smooth_line = build_figure(values)
    chart = fch.MatplotlibChart(figure=figure, expand=True)

    def reset():
        """Drop every pan and zoom, and clear both mode buttons with them."""
        chart.home()
        pan.selected = zoom.selected = False

    def pan_click():
        """Toggle drag-to-pan, turning zoom off: the two modes are exclusive."""
        chart.pan()
        pan.selected = not pan.selected
        zoom.selected = False

    def zoom_click():
        """Toggle draw-a-box-to-zoom, turning pan off for the same reason."""
        chart.zoom()
        zoom.selected = not zoom.selected
        pan.selected = False

    def resmooth():
        """Redraw the overlay at the selected window and say what is on screen.

        `figure.canvas.draw()` is what pushes the new pixels: mutating the
        Line2D alone changes nothing the control can see.
        """
        chosen = int(window.selected[0])
        set_window(smooth_line, values, chosen)
        figure.canvas.draw()
        caption.value = (
            f"{len(values)} daily readings, smoothed over {chosen} days — "
            "turn on pan to drag, or zoom to box a season"
        )
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("matplotlib live chart"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    caption := ft.Text(size=12),
                    window := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=str(w), label=ft.Text(f"{w} d"))
                            for w in WINDOWS
                        ],
                        # A list, not a set: control properties are msgpack'd on their
                        # way to the client, and a set raises TypeError there.
                        selected=[str(DEFAULT_WINDOW)],
                        on_change=resmooth,
                    ),
                    ft.Row(
                        controls=[
                            ft.IconButton(ft.Icons.HOME, on_click=reset),
                            pan := ft.IconButton(
                                ft.Icons.OPEN_WITH,
                                selected_icon_color=ft.Colors.AMBER_800,
                                on_click=pan_click,
                            ),
                            zoom := ft.IconButton(
                                ft.Icons.ZOOM_IN,
                                selected_icon_color=ft.Colors.AMBER_800,
                                on_click=zoom_click,
                            ),
                        ]
                    ),
                    chart,
                ]
            ),
        )
    )

    resmooth()


if __name__ == "__main__":
    ft.run(main)
