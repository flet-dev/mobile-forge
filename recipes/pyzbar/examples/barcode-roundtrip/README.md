# pyzbar barcode round trip

One screen that closes the loop with no camera, no network and no image library. The app
**encodes** three barcodes straight from their specifications, paints them into 8-bit
greyscale byte buffers, hands those exact buffers to
[pyzbar](https://github.com/NaturalHistoryMuseum/pyzbar) and prints whether what came out
equals what went in. A PNG encoder built from `zlib` and `struct` in under twenty lines wraps
the same buffer for [`ft.Image(src=<bytes>)`](https://flet.dev/docs/controls/image/), so the
picture on screen and the bytes that were decoded are provably the same data.

What it demonstrates:

- **The input shape pyzbar takes when you have no PIL and no numpy** — a plain
  `(pixels, width, height)` tuple of 8-bit greyscale, one byte per pixel. Neither library is
  installed in this app, and neither is needed; the buffer comes out of a dozen lines of
  `bytes` arithmetic.
- **`Decoded.data` is `bytes`.** Each row prints it twice — `b'5901234123457'` and then
  `'5901234123457'` — because comparing the raw value to a `str` literal is always `False`
  and rendering it into a `Text` shows the reader the `b` and the quotes.
- **The rest of the `Decoded` tuple**: the symbology name, `quality`, `orientation`, the
  `rect` and every vertex of the `polygon`. `quality` is a per-symbology score and is not
  comparable across rows — on the undamaged set it reads 52 for the Code 128, 103 for the
  EAN-13 and 1 for the QR.
- **What this build can actually read, asked of the device's own library** rather than taken
  from documentation. For every member of `ZBarSymbol` the app calls
  `zbar_image_scanner_set_config(scanner, symbol, CFG_ENABLE, 1)`, which returns 0 when the
  decoder was compiled in and 1 when it was not: 18 symbologies in, **PDF417 out**. The line
  below it shows what that costs you — `decode(..., symbols=[ZBarSymbol.PDF417])` returns
  `[]` rather than raising, so a symbology this build lacks fails silently.
- **Detecting errors versus correcting them.** A
  [`Slider`](https://flet.dev/docs/controls/slider/) inverts 0–30 whole modules before
  rasterising, seeded from its own position so every stop is reproducible. Measured against
  zbar 0.23.93: **one** flipped module already kills both 1-D symbols — which have no error
  correction at all, so a 1-D symbol either reads or it does not — and they stay dead at every
  later stop, while the 25×25 QR (error correction level Q) still decodes
  at every count up to 18 and goes intermittent from 19 — in a 0-to-40 sweep it last decoded
  at 28. The app prints whatever the device's own library does.
- **Rotation is the library's problem, not yours.** The switch turns all three buffers 90°
  clockwise; the data is unchanged and `orientation` goes from `UP` to `RIGHT`.
- **Two independent cross-checks.** The app computes EAN-13's mod-10 check digit and Code
  128's mod-103 checksum itself and puts them in the bars; zbar recomputes both from what it
  read and refuses the symbol if they disagree, so a `MATCH` is two separate implementations
  of the same spec agreeing. Separately, every symbology that decoded has to appear as
  compiled-in in the capability probe — the last line says so, and would say `INCONSISTENT`
  otherwise.
- **Honest behaviour where libzbar is absent.** The import is guarded, so a desktop
  `flet run` without a system zbar shows `ImportError: Unable to find zbar shared library`
  and what to do about it, instead of failing to launch.

The QR's modules are carried in the file as 25 bit-packed rows — 100 bytes, 136 characters of
base64 — rather than generated: writing a QR encoder means Reed-Solomon and mask selection,
which teaches nothing about pyzbar. They encode `https://flet.dev`, and the decode is what
proves they are right. The two 1-D symbols are generated in full, pattern tables included.

What it deliberately does **not** show is the other half of a scanning app: getting a buffer
out of a camera frame or a photo the user picked. That needs an image library, and the recipe
[`README.md`](../../README.md#things-to-know) says which one and where it comes from.

Everything runs synchronously — a redraw is three rasters, three decodes and three PNG
compressions, about 3 ms on a development machine (twice that with the rotation switch on) —
so it needs no
[`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and two
gestures cannot overlap. It writes no files, makes no network requests and bundles no assets.

`pyzbar` is a plain `[project] dependencies` entry: the recipe publishes wheels for every
Android ABI and every iOS slice Flet targets, and `flet-libzbar` follows it in on its own.
`pyproject.toml` pins both `flet` and `pyzbar`, which is the combination that was verified.
`requires-python` stays at `>=3.10` — pyzbar's own wheel is `py2.py3-none-any` and declares no
floor, so every split uv resolves for is satisfiable — checked the way a consumer meets it, by
copying that `pyproject.toml` alone into an empty directory and running `uv lock` there.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device, emulator or
simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

`flet run` on the desktop is worth doing once too, for what it shows: it resolves pyzbar from
PyPI rather than from this index, so it needs a system zbar (`brew install zbar`,
`sudo apt install libzbar0`) and on macOS usually
`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run flet run` as well. That is also what the
`find_library('zbar')` value in the header line is there for. On a desktop it is the path the
system search found; the mobile wheels do not depend on that search succeeding, and a screen
that rendered at all is the proof the library was located some other way.
