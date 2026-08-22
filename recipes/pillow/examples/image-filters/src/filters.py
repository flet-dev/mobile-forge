import io
import time

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
    __version__,
    features,
)

SIZE = 384

# get_supported_codecs() is the one line worth printing on a phone: it reads
# "jpg, zlib" here and lists jpg_2000 and libtiff as well on a laptop.
VERSION = f"Pillow {__version__} — codecs: {', '.join(features.get_supported_codecs())}"

# Every effect is the identity at strength 0, so the slider always runs from the
# untouched source picture to the strongest version of the same transform.
EFFECTS = {
    "Gaussian blur": lambda img, k: img.filter(ImageFilter.GaussianBlur(radius=k)),
    "Posterize": lambda img, k: ImageOps.posterize(img, 8 - int(k)),
    "Solarize": lambda img, k: ImageOps.solarize(img, threshold=255 - int(k) * 36),
    "Contrast": lambda img, k: ImageEnhance.Contrast(img).enhance(1 + k / 2),
    "Desaturate": lambda img, k: ImageEnhance.Color(img).enhance(1 - k / 7),
}


def source_image():
    """Compose a test picture out of Pillow's own generators, with no bundled asset."""
    # linear_gradient/radial_gradient are native 256x256 builders, so the colour
    # field costs three C calls rather than a per-pixel Python loop.
    horizontal = Image.linear_gradient("L")
    vertical = horizontal.transpose(Image.Transpose.ROTATE_90)
    radial = Image.radial_gradient("L")
    img = Image.merge("RGB", (horizontal, vertical, ImageOps.invert(radial)))
    img = img.resize((SIZE, SIZE), Image.Resampling.BICUBIC)

    draw = ImageDraw.Draw(img)
    for i, colour in enumerate(("white", "black", "white")):
        inset = 40 + i * 46
        draw.ellipse((inset, inset, SIZE - inset, SIZE - inset), outline=colour, width=6)
    draw.line((0, SIZE // 2, SIZE, SIZE // 2), fill="black", width=3)
    # load_default(size=...) scales a TrueType face embedded in ImageFont.py, so
    # text renders without shipping a font file. It is ASCII-only, hence the label.
    draw.text((16, 14), "PILLOW", fill="white", font=ImageFont.load_default(size=34))
    return img


def encode(img):
    """Encode to PNG bytes, which ft.Image.src takes directly — no temp file, no base64."""
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return buffer.getvalue()


SOURCE = source_image()


def apply_effect(name, amount):
    """Filter the source picture at `amount` and return PNG bytes plus milliseconds.

    Filtering and PNG encoding are the compiled loops the app keeps off the UI
    thread. Every effect returns a *new* image and leaves SOURCE untouched, which
    is what makes this safe to call from a thread pool: nothing in Pillow
    serialises access to an Image, so two workers mutating one in place would
    corrupt each other's pixels without raising anything.
    """
    started = time.perf_counter()
    data = encode(EFFECTS[name](SOURCE, amount))
    return data, (time.perf_counter() - started) * 1000
