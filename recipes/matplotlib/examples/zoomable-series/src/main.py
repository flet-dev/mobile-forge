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
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

DATES = np.arange("2021-01-01", "2026-01-01", dtype="datetime64[D]")
WINDOWS = [7, 30, 90]
DEFAULT_WINDOW = WINDOWS[1]


def readings():
    """Five years of daily readings: a warming trend, a season, and weather.

    Stands in for whatever series the app has actually logged. Seeded so the
    figure is the same on every launch and zooming into a feature twice shows
    the same feature.
    """
    day = np.arange(DATES.size)
    season = 11.0 * np.sin(2.0 * np.pi * (day - 110) / 365.25)
    trend = 0.0008 * day
    weather = np.random.default_rng(20260817).normal(scale=2.4, size=day.size)
    return 12.0 + season + trend + np.cumsum(weather) * 0.02 + weather


def rolling_mean(values, window):
    """Centred moving average, and the dates it is defined on.

    `mode="valid"` drops the partial windows at both ends instead of quietly
    averaging over fewer days, so the smoothed line never claims more than it
    knows; the returned dates are trimmed to match.
    """
    smoothed = np.convolve(values, np.ones(window) / window, mode="valid")
    edge = (window - 1) // 2
    return DATES[edge : edge + smoothed.size], smoothed


def main(page: ft.Page):
    """Plot the raw series with a smoothed overlay, in a chart you can zoom.

    The figure comes from pyplot on purpose. Importing flet_charts registers a
    matplotlib backend, and MatplotlibChart streams frames through the canvas
    and manager that backend attaches — which only pyplot's factory functions
    do. A bare `Figure()` has `canvas.manager is None` and never draws.

    The toolbar here is three of our own buttons driving the chart's navigation
    methods, rather than flet_charts' ready-made MatplotlibChartWithToolbar: that
    composite lays its eight controls out in one non-scrolling Row, which
    overflows a phone-width screen.
    """
    values = readings()

    figure, axes = plt.subplots(figsize=(7.0, 4.5), layout="constrained")
    axes.plot(DATES, values, linewidth=0.5, alpha=0.45, label="daily")
    (smooth_line,) = axes.plot(*rolling_mean(values, DEFAULT_WINDOW), linewidth=2.0)
    axes.set_ylabel("°C")
    axes.grid(alpha=0.3)

    # Zooming in makes the default date formatter spell out every tick in full, and on a
    # phone-width axis those labels collide into an unreadable smear. ConciseDateFormatter
    # drops whatever the neighbouring tick already implies, so they stay short at any zoom.
    locator = mdates.AutoDateLocator()
    axes.xaxis.set_major_locator(locator)
    axes.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

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
        """Label the overlay and redraw it at the selected window.

        `figure.canvas.draw()` is what pushes the new pixels: mutating the
        Line2D alone changes nothing the control can see. Also the only place
        the legend is built, so the overlay is never labelled with a window
        it is not showing.
        """
        chosen = int(window.selected[0])
        smooth_line.set_data(*rolling_mean(values, chosen))
        smooth_line.set_label(f"{chosen}-day")
        axes.legend(loc="upper left")
        figure.canvas.draw()
        caption.value = (
            f"{DATES.size} daily readings, smoothed over {chosen} days — "
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
