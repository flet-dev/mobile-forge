import io
import time

import matplotlib
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ft2font import __freetype_version__

SIDE = 40.0
GRID = 240
DPI = 160
FIGSIZE = (4.4, 4.0)

# (x, y, watts) of the transmitters the survey is measuring.
SOURCES = [(8.0, 30.0, 1.0), (30.0, 27.0, 0.6), (21.0, 9.0, 0.35)]

# FreeType is matplotlib's own bundled copy, statically linked into ft2font: the same
# version on device as on a desktop, which is why every label lays out identically.
VERSION = (
    f"matplotlib {matplotlib.__version__} — FreeType {__freetype_version__} — "
    f"{GRID}×{GRID} grid, Agg"
)

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
