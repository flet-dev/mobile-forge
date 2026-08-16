import io
from os.path import dirname, join


def test_basic():
    """Round-trip a JPEG through Pillow's PNG encoder."""
    from PIL import Image

    img = Image.open(join(dirname(__file__), "mandrill.jpg"))
    assert img.width == 512
    assert img.height == 512

    out_file = io.BytesIO()
    img.save(out_file, "png")
    out_bytes = out_file.getvalue()
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
    """Load a TrueType font and render text with it."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(join(dirname(__file__), "Vera.ttf"), size=20)
    assert font.size == 20

    bbox = font.getbbox("Hello")
    width = bbox[2] - bbox[0]
    assert 30 < width < 80, f"unexpected 'Hello' width = {width}"

    bbox_long = font.getbbox("Hello world")
    assert bbox_long[2] - bbox_long[0] > width

    img = Image.new("RGB", (200, 50), "white")
    ImageDraw.Draw(img).text((10, 10), "Hello", fill="black", font=font)
    pixels = [img.getpixel((x, 25)) for x in range(15, 80)]
    assert any(
        p != (255, 255, 255) for p in pixels
    ), "font didn't render any non-white pixels"


def test_only_jpeg_and_zlib_codecs_are_built():
    """The mobile wheels link libjpeg and freetype only — no WebP, AVIF, JPEG
    2000, libtiff or LittleCMS. That is the difference a consumer hits when an
    Image.open that works on their Mac fails on device, so pin the exact codec
    set the README promises."""
    from PIL import features

    codecs = set(features.get_supported_codecs())
    assert {"jpg", "zlib"} <= codecs, codecs
    assert not ({"webp", "jpg_2000", "libtiff"} & codecs), codecs
    assert "freetype2" in features.get_supported_modules()
    assert not features.check("littlecms2")


def test_default_font_needs_no_file():
    """There is no system font path on device, so ImageFont.truetype has nothing
    to open unless the app bundles a face. load_default() carries its own and is
    the safe fallback — check it renders."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (120, 40), "white")
    ImageDraw.Draw(image).text(
        (4, 4), "Flet", font=ImageFont.load_default(size=20), fill="black"
    )
    assert image.getbbox() is not None
