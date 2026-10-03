import asyncio
import ctypes
import os
import struct
import sys
import tempfile

import pytest

# v8x resolves its QuickJS bytecode cache once, on the first conversion.
CACHE_DIR = tempfile.mkdtemp(prefix="vlc-bytecode-")
os.environ["V82JSC_BC_CACHE_DIR"] = CACHE_DIR

import vl_convert as vlc  # noqa: E402

SPEC = {
    "data": {
        "values": [
            {"fruit": "apple", "count": 28},
            {"fruit": "banana", "count": 55},
            {"fruit": "cherry", "count": 43},
        ]
    },
    "mark": "bar",
    "encoding": {
        "x": {"field": "fruit", "type": "nominal"},
        "y": {"field": "count", "type": "quantitative"},
    },
}


def png_size(png):
    """Width and height from a PNG's IHDR chunk."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


def test_vegalite_to_svg():
    """Vega-Lite compiles and Vega renders an SVG on the embedded QuickJS runtime."""
    svg = vlc.vegalite_to_svg(SPEC)
    assert svg.lstrip().startswith("<svg")
    assert "banana" in svg


def test_vegalite_to_png_honours_scale():
    """PNG output exists and `scale` doubles both dimensions."""
    width, height = png_size(vlc.vegalite_to_png(SPEC))
    assert width > 0 and height > 0
    assert png_size(vlc.vegalite_to_png(SPEC, scale=2)) == (2 * width, 2 * height)


def test_asyncio_variant():
    """The vl_convert.asyncio functions await from an event loop, as in an async Flet handler."""

    async def convert():
        return await vlc.asyncio.vegalite_to_svg(SPEC)

    assert "banana" in asyncio.run(convert())


def test_text_renders_without_system_fonts():
    """Text rasterises from the font bundled in the wheel; with no font it would be dropped."""
    frame = '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40">{}</svg>'
    blank = frame.format('<rect width="120" height="40" fill="white"/>')
    text = frame.format(
        '<rect width="120" height="40" fill="white"/>'
        '<text x="4" y="30" font-family="sans-serif" font-size="28">Flet</text>'
    )
    assert vlc.svg_to_png(text) != vlc.svg_to_png(blank)


def test_bytecode_cache_lands_in_configured_dir():
    """Compiled JavaScript is cached under V82JSC_BC_CACHE_DIR, so apps can point it at app storage."""
    vlc.vegalite_to_svg(SPEC)
    assert any(name.endswith(".qbc") for name in os.listdir(CACHE_DIR))


@pytest.mark.skipif(sys.platform != "android", reason="bionic's key limit is Android-only")
def test_leaves_tls_keys_for_other_modules():
    """A running worker leaves pthread keys free; unshimmed, it left about 4 of bionic's 128."""
    vlc.vegalite_to_png(SPEC)
    libc = ctypes.CDLL("libc.so")
    keys, key = [], ctypes.c_uint()
    while libc.pthread_key_create(ctypes.byref(key), None) == 0:
        keys.append(key.value)
    for k in keys:
        libc.pthread_key_delete(k)
    assert len(keys) >= 32, f"only {len(keys)} pthread keys left"


def test_altair_save_png():
    """Altair finds vl-convert on the device and `chart.save()` writes a PNG through it."""
    import altair as alt

    chart = alt.Chart(alt.Data(values=SPEC["data"]["values"])).mark_bar()
    chart = chart.encode(x="fruit:N", y="count:Q")
    path = os.path.join(CACHE_DIR, "altair.png")
    chart.save(path)
    with open(path, "rb") as f:
        assert png_size(f.read())[0] > 0
