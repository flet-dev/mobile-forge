import io
from os.path import dirname, join


def test_basic():
    """Round-trip a JPEG through Pillow's PNG encoder.

    Validates Image.open, image dimensions, PNG encoding, and that the
    encoded bytes decode back to the same dimensions. Avoids asserting an
    exact byte count — the encoder's output size varies with libpng/zlib
    versions and Pillow's compression defaults, which would make the test
    flap on every dep bump.
    """
    from PIL import Image

    img = Image.open(join(dirname(__file__), "mandrill.jpg"))
    assert img.width == 512
    assert img.height == 512

    out_file = io.BytesIO()
    img.save(out_file, "png")
    out_bytes = out_file.getvalue()

    # Sanity range, not a magic exact count.
    assert 1024 < len(out_bytes) < 10_000_000

    # PNG signature + IHDR chunk start + width 512 + height 512.
    assert out_bytes[:24] == (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + b"\x00\x00\x02\x00"
        + b"\x00\x00\x02\x00"
    )

    # Round-trip: re-decode the produced PNG and confirm the dimensions
    # survive (proves the encoder didn't truncate/corrupt the stream).
    rt = Image.open(io.BytesIO(out_bytes))
    rt.load()
    assert rt.width == 512
    assert rt.height == 512


def test_font():
    """Load a TrueType font and render text with it.

    Uses font.getbbox() (the API introduced in Pillow 9.2 to replace
    getsize, which was removed in Pillow 10.0). The original test called
    getsize() AND forgot the `assert` keyword on the comparisons, so it
    was a silent no-op even on contemporary Pillow at the time.
    """
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(join(dirname(__file__), "Vera.ttf"), size=20)
    assert font.size == 20

    # getbbox returns (left, top, right, bottom); width = right - left.
    # Use a generous range because glyph metrics vary by freetype version
    # and Pillow's hinting mode — exact pixel counts would be brittle.
    bbox = font.getbbox("Hello")
    width = bbox[2] - bbox[0]
    assert 30 < width < 80, f"unexpected 'Hello' width = {width}"

    bbox_long = font.getbbox("Hello world")
    assert bbox_long[2] - bbox_long[0] > width

    # End-to-end render — proves the font lib is actually drawable, not
    # just queryable.
    img = Image.new("RGB", (200, 50), "white")
    ImageDraw.Draw(img).text((10, 10), "Hello", fill="black", font=font)
    # If anything was drawn, at least one pixel on the text baseline is non-white.
    pixels = [img.getpixel((x, 25)) for x in range(15, 80)]
    assert any(p != (255, 255, 255) for p in pixels), "font didn't render any non-white pixels"
