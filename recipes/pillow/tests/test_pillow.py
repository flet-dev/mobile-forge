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
    assert any(p != (255, 255, 255) for p in pixels), (
        "font didn't render any non-white pixels"
    )


def test_webp_available():
    """WebP support is compiled in (PIL._webp imports)."""
    from PIL import Image, features

    assert features.check("webp") is True
    # Non-empty version string; not pinned, so a libwebp bump doesn't break this.
    assert features.version("webp")
    assert ".webp" in Image.registered_extensions()


def test_webp_no_unsupported_warning():
    """Opening a WebP emits no 'WEBP support not installed' warning."""
    import warnings

    from PIL import Image

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        img = Image.open(join(dirname(__file__), "webp_quadrants_lossy.webp"))
        img.load()

    assert not [w for w in caught if "WEBP support not installed" in str(w.message)]


def test_webp_decode_lossless_file():
    """Decode a committed lossless WebP; quadrant colours are exact."""
    from PIL import Image

    img = Image.open(join(dirname(__file__), "webp_quadrants_lossless.webp"))
    assert img.size == (8, 8)
    assert img.format == "WEBP"

    rgb = img.convert("RGB")
    assert rgb.getpixel((1, 1)) == (255, 0, 0)
    assert rgb.getpixel((6, 1)) == (0, 255, 0)
    assert rgb.getpixel((1, 6)) == (0, 0, 255)
    assert rgb.getpixel((6, 6)) == (255, 255, 0)


def test_webp_decode_lossy_file():
    """Decode a committed lossy WebP (VP8, what CDNs serve) within tolerance."""
    from PIL import Image

    img = Image.open(join(dirname(__file__), "webp_quadrants_lossy.webp"))
    assert img.size == (8, 8)

    rgb = img.convert("RGB")
    expected = {
        (1, 1): (255, 0, 0),
        (6, 1): (0, 255, 0),
        (1, 6): (0, 0, 255),
        (6, 6): (255, 255, 0),
    }
    for xy, want in expected.items():
        got = rgb.getpixel(xy)
        assert all(abs(g - w) <= 24 for g, w in zip(got, want)), f"{xy}: {got} != {want}"


def test_webp_lossless_roundtrip():
    """Encode and re-decode a lossless WebP without loss."""
    from PIL import Image

    src = Image.new("RGB", (16, 16))
    src.putdata([(x * 16, y * 16, 0) for y in range(16) for x in range(16)])

    out = io.BytesIO()
    src.save(out, "WEBP", lossless=True)
    data = out.getvalue()
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WEBP"
    assert data[12:16] == b"VP8L"

    rt = Image.open(io.BytesIO(data))
    assert rt.convert("RGB").tobytes() == src.tobytes()


def test_webp_lossy_roundtrip_alpha():
    """Round-trip RGBA through the lossy encoder, preserving alpha."""
    from PIL import Image

    src = Image.new("RGBA", (16, 16), (0, 128, 255, 255))
    for y in range(8):
        for x in range(8):
            src.putpixel((x, y), (0, 0, 0, 0))

    out = io.BytesIO()
    src.save(out, "WEBP", quality=80)
    data = out.getvalue()
    assert data[12:16] == b"VP8X"

    rt = Image.open(io.BytesIO(data))
    assert rt.mode == "RGBA"
    assert rt.getpixel((2, 2))[3] == 0
    assert rt.getpixel((12, 12))[3] == 255


def test_webp_metadata_roundtrip():
    """Save a still WebP with EXIF, proving libwebpmux is linked."""
    from PIL import Image

    payload = b"MM\x00*\x00\x00\x00\x08\x00\x00"
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(
        out, "WEBP", lossless=True, exif=b"Exif\x00\x00" + payload
    )

    # Pillow strips the "Exif\0\0" prefix before writing the chunk; tolerate
    # either convention so the assert pins the round-trip, not the framing.
    got = Image.open(io.BytesIO(out.getvalue())).info.get("exif")
    assert got is not None, "no exif chunk survived the round-trip"
    assert got.removeprefix(b"Exif\x00\x00") == payload, got


def test_webp_animation_decode():
    """Read a committed animated WebP frame by frame (libwebpdemux)."""
    from PIL import Image

    img = Image.open(join(dirname(__file__), "webp_anim_rgb.webp"))
    assert img.n_frames == 3
    assert img.is_animated is True

    for i, want in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        img.seek(i)
        assert img.convert("RGB").getpixel((4, 4)) == want
        assert img.info["duration"] == 100


def test_webp_animation_encode():
    """Write a 3-frame animated WebP and read it back (libwebpmux)."""
    from PIL import Image

    frames = [Image.new("RGB", (8, 8), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]

    out = io.BytesIO()
    frames[0].save(
        out, "WEBP", save_all=True, append_images=frames[1:],
        duration=80, loop=0, lossless=True,
    )

    rt = Image.open(io.BytesIO(out.getvalue()))
    assert rt.n_frames == 3
    for i, want in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        rt.seek(i)
        assert rt.convert("RGB").getpixel((4, 4)) == want
