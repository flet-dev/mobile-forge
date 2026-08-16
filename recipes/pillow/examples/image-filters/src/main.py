"""Draw an image with Pillow, filter it, and hand the encoded bytes straight to ft.Image."""

import io

import flet as ft
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
        draw.ellipse(
            (inset, inset, SIZE - inset, SIZE - inset), outline=colour, width=6
        )
    draw.line((0, SIZE // 2, SIZE, SIZE // 2), fill="black", width=3)
    # load_default(size=...) scales a TrueType face embedded in ImageFont.py, so
    # text renders without shipping a font file.
    draw.text((16, 14), "PILLOW", fill="white", font=ImageFont.load_default(size=34))
    return img


def encode(img):
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return buffer.getvalue()


SOURCE = source_image()


def main(page: ft.Page):
    def render():
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        name = effect.value
        amount = strength.value
        data = encode(EFFECTS[name](SOURCE, amount))
        preview.src = data
        caption.value = f"{name} at {amount:.0f} — PNG, {len(data) / 1024:.1f} kB"
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Pillow image filters"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"Pillow {__version__} — codecs: "
                        f"{', '.join(features.get_supported_codecs())}",
                        size=12,
                    ),
                    preview := ft.Image(
                        src=encode(SOURCE),
                        width=SIZE,
                        height=SIZE,
                        border_radius=8,
                    ),
                    ft.Row(
                        controls=[
                            effect := ft.Dropdown(
                                expand=True,
                                label="Effect",
                                value=next(iter(EFFECTS)),
                                options=[ft.DropdownOption(name) for name in EFFECTS],
                                on_select=render,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    # on_change_end, not on_change: one render per gesture, so two
                    # workers can never land out of order and swap the preview back.
                    strength := ft.Slider(
                        min=0,
                        max=7,
                        value=4,
                        divisions=7,
                        round=0,
                        label="{value}",
                        on_change_end=render,
                    ),
                    caption := ft.Text(size=12),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                scroll=ft.ScrollMode.AUTO,
            ),
        )
    )

    render()


if __name__ == "__main__":
    ft.run(main)
