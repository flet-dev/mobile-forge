import math
import os
import time
from pathlib import Path

# The JavaScript bytecode cache and the Google Fonts cache each resolve their
# directory once, on first use, so point them at app storage before importing.
CACHE = Path(os.getenv("FLET_APP_STORAGE_CACHE", ".")) / "vl-convert"
os.environ.setdefault("V82JSC_BC_CACHE_DIR", str(CACHE / "bytecode"))
os.environ.setdefault("VLC_GOOGLE_FONTS_CACHE_DIR", str(CACHE / "google-fonts"))

import vl_convert as vlc  # noqa: E402

VERSIONS = (
    f"Vega {vlc.get_vega_version()} · Vega-Lite {vlc.get_vegalite_versions()[-1]}"
)

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
RAIN = (78, 61, 52, 47, 59, 41, 33, 38, 55, 81, 96, 89)
HIGHS = {
    "Lisbon": (15, 16, 19, 20, 23, 27, 29, 29, 27, 23, 18, 15),
    "Oslo": (-1, 0, 4, 10, 16, 20, 22, 21, 16, 9, 4, 0),
    "Lagos": (32, 33, 33, 32, 31, 29, 28, 28, 29, 30, 31, 32),
}


def scatter_points():
    """A noisy but fixed curve, so the fitted line has something to find."""
    return [
        {"x": x, "y": round(3 + 0.8 * x + 2.5 * math.sin(x * 1.7), 2)}
        for x in (i * 0.5 for i in range(40))
    ]


SPECS = {
    "Bars": {
        "title": "Rainfall (mm)",
        "data": {"values": [{"month": m, "mm": r} for m, r in zip(MONTHS, RAIN)]},
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": {"field": "month", "type": "ordinal", "sort": None, "title": None},
            "y": {"field": "mm", "type": "quantitative", "title": None},
            "color": {
                "condition": {"test": "datum.mm > 80", "value": "#e4572e"},
                "value": "#4c78a8",
            },
        },
    },
    "Lines": {
        "title": "Average high (°C)",
        "data": {
            "values": [
                {"city": city, "month": m, "high": h}
                for city, highs in HIGHS.items()
                for m, h in zip(MONTHS, highs)
            ]
        },
        "mark": {"type": "line", "point": True},
        "encoding": {
            "x": {"field": "month", "type": "ordinal", "sort": None, "title": None},
            "y": {"field": "high", "type": "quantitative", "title": None},
            "color": {"field": "city", "type": "nominal", "legend": {"orient": "bottom"}},
        },
    },
    "Fit": {
        "title": "Points and a LOESS fit computed by Vega",
        "data": {"values": scatter_points()},
        "layer": [
            {"mark": {"type": "point", "filled": True, "opacity": 0.6}},
            {
                "mark": {"type": "line", "color": "#e4572e", "strokeWidth": 3},
                "transform": [{"loess": "y", "on": "x", "bandwidth": 0.3}],
            },
        ],
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    },
}


def render(name, width):
    """Convert one spec to PNG bytes sized to `width` logical pixels.

    Returns the PNG, its pixel size and the seconds the conversion took. The
    first call in a process also boots the JavaScript runtime, so it is the slow one.
    """
    spec = {**SPECS[name], "width": width, "height": round(width * 0.6)}
    started = time.perf_counter()
    png = vlc.vegalite_to_png(spec, scale=2)
    elapsed = time.perf_counter() - started
    size = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    return png, size, elapsed
