import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

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


def build_figure(values):
    """Plot the raw series with a smoothed overlay; return the figure and that overlay.

    The figure comes from pyplot on purpose. Importing flet_charts registers a
    matplotlib backend, and MatplotlibChart streams frames through the canvas
    and manager that backend attaches — which only pyplot's factory functions
    do. A bare `Figure()` has `canvas.manager is None` and never draws.
    """
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
    return figure, smooth_line


def set_window(line, values, window):
    """Point the overlay at a `window`-day average and rebuild the legend with it.

    The legend is built here so the line is never labelled with a window it is
    not showing. Changing an artist is all this does: the caller still has to
    call `figure.canvas.draw()` for the chart to show anything different.
    """
    line.set_data(*rolling_mean(values, window))
    line.set_label(f"{window}-day")
    line.axes.legend(loc="upper left")
