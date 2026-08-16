# Pillow image filters

A picture drawn entirely by [Pillow](https://python-pillow.github.io/) — three merged
gradients, a few circles and a text label — with a filter applied to it. Pick an effect and
drag the strength slider; the image on screen is re-rendered and re-encoded on the device
every time.

What it demonstrates:

- **PIL bytes straight into a Flet control** — the filtered image is encoded into an
  `io.BytesIO` and the raw PNG bytes are assigned to
  [`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src), which accepts
  `bytes` as well as a path. No temporary file, no base64, no assets entry. The caption
  reports how many kilobytes the encoder produced, which changes a lot between effects —
  posterizing a gradient makes it six times smaller, blurring it makes it twice as big.
- **Which codecs this build actually has** — the header line prints
  [`features.get_supported_codecs()`](https://pillow.readthedocs.io/en/stable/reference/features.html#PIL.features.get_supported_codecs).
  On a phone it reads `jpg, zlib`; run the same code on your laptop and it also lists
  `jpg_2000` and `libtiff`. That difference is the one thing worth knowing before porting
  image code to mobile.
- **Text with no bundled font** —
  [`ImageFont.load_default(size=...)`](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html#PIL.ImageFont.load_default)
  scales a TrueType face embedded in Pillow itself, which is why this app ships no assets at
  all. It is ASCII-only, hence the all-caps Latin label.
- **Rendering off the UI thread** — each render runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind
  a spinner and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. The slider fires on `on_change_end` rather than `on_change`, so a drag
  starts one render instead of eight racing ones.

Every effect is the identity at strength 0, so sliding from 0 upwards always shows you the
same picture being pushed further — `GaussianBlur(radius=0)`, `posterize(bits=8)` and
`solarize(threshold=255)` all return the source unchanged.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
