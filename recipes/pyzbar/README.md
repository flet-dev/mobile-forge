# pyzbar

[`pyzbar`](https://github.com/NaturalHistoryMuseum/pyzbar) reads barcodes and QR codes out of an
image. It is a small ctypes wrapper — pure Python, no compiled extension of its own — around
[zbar](https://github.com/mchehab/zbar), which does the actual decoding, and the point of this
recipe is that the zbar shared library travels with it. On a phone that means barcode reading
that never leaves the device: hand it an 8-bit greyscale frame and it hands back the values,
their symbology, where they sit in the image and which way up they are — no network call and no
cloud API. Getting the frames is your problem, though: pyzbar decodes buffers, it does not talk
to a camera.

It is published for **both platforms** — every Android ABI and every iOS slice Flet targets.
The only Python file in the wheel that differs from upstream's own release is the loader, so
[upstream's documentation](https://github.com/NaturalHistoryMuseum/pyzbar) applies unchanged.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pyzbar",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`barcode-roundtrip`](examples/barcode-roundtrip) — three barcodes encoded, rendered,
  decoded back and checked, with a damage slider and a capability probe.

## Usage in a Flet app

One call does the whole job, and what comes back goes straight into a
[`ft.Text`](https://flet.dev/docs/controls/text/):

```python
from pyzbar.pyzbar import decode

found = decode((pixels, width, height))  # 8-bit greyscale, immutable bytes
label = ft.Text(
    "\n".join(f"{d.type}: {d.data.decode('utf-8', 'replace')}" for d in found)
    or "no symbol found",
    selectable=True,
)
```

`decode()` returns one result per symbol it read and an empty list when it read none — a frame
with nothing in it is not an error. Keeping `.data` as `bytes` and decoding it at the point of
display, as above, is deliberate; the rest of each result (`.type`, `.rect`, `.polygon`,
`.orientation`) is what you need to draw a box over the symbol in an
[`ft.Image`](https://flet.dev/docs/controls/image/).

### Storage

pyzbar reads a buffer that is already in memory and writes nothing of its own — no cache, no
model file, no path to configure. What touches storage is the picture on the way in.

Put a frame the user picked or your app downloaded in
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
when you are going to decode it and throw it away, and in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
when the user expects to still have it later:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_TEMP", "."), "scan.jpg")
```

pyzbar never sees that path. It takes pixels, not filenames, so a file only exists because your
app put it there and reading it back is your code's job.

### Threading

A `decode()` call holds no state that another call could tread on: pyzbar creates the zbar
scanner and the zbar image inside the call and destroys both on the way out, so there is no
shared handle and no lock to take. It also releases the GIL for the duration, because the
bindings are built with `ctypes.CFUNCTYPE`, so decoding several frames really does run in
parallel.

Measured on a development machine against zbar 0.23.93: twelve threads × 200 decodes of
*twelve different* 640×480 frames — 2400 decodes, every one returning its own thread's payload,
zero exceptions. Four threads on that work ran 2.6× faster there than one, against 0.9× for a
GIL-bound pure-Python loop of the same duration, which is what makes it a GIL result and not a
scheduling artefact. A single decode of one of those frames costs about 2.7 ms on that same
development machine. Those are all desktop numbers and say nothing about a phone; measure on
the device before you decide what fits in a frame.

That makes [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
safe for decoding, with the two standing Flet caveats: it never retrieves the worker's future,
so an exception raised inside one surfaces nowhere at all — wrap the body — and auto-update
does not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Image input

Two shapes go in, and only two. A plain `(pixels, width, height)` tuple of 8-bit greyscale —
one byte per pixel, `pixels` immutable `bytes` — or an object pyzbar recognises by its type
name and converts for you: a PIL `Image`, or a numpy array. That is the entire input surface.

Nothing in the package gets you a frame. The camera, the file picker and the JPEG decoder are
the app's problem, and on a phone that is most of the work — pyzbar's half is the last few
milliseconds. Build the buffer yourself when your app draws the picture, which the
[`barcode-roundtrip`](examples/barcode-roundtrip) example does in a dozen lines of `bytes`
arithmetic, and reach for an image library when the picture came from outside.

### App size

Budget about 1.1 MB per Android ABI and about 270 KB per iOS slice. Almost all of that is
`libzbar` itself; pyzbar's own wheel adds about 42 KB unpacked (17 KB compressed) and is
nothing but Python. The Android library is roughly four times the iOS one because it statically
folds in the charset conversion that iOS gets from the system.

[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
worth removing — the only removable thing in the wheel is upstream's own test package, about
16 KB. On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These figures describe the package payload, not the exact
amount added to the final APK or IPA; packaging and compression determine that result.

### Other considerations

**`flet run` on your desktop does not use this wheel.** These wheels are Android/iOS
platform-tagged, so a desktop resolve takes PyPI's `py2.py3-none-any` build, which bundles no
library and asks `ctypes.util.find_library('zbar')` for a system one. Install zbar
(`brew install zbar`, `sudo apt install libzbar0`); on macOS `find_library` only sees
Homebrew's copy under Homebrew's own Python, so a uv-managed or python.org interpreter also
needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`. That system zbar is a different build
from the one in these wheels, and which symbologies a build can read is a property of the
build — so confirm capability on a device or emulator/simulator rather than at your desk.

## Things to know

- **Never call `pyzbar.wrapper.zbar_version()`.** pyzbar declares it as taking two `unsigned*`
  pointers; zbar 0.23 takes **three** — major, minor, patch — and writes `*patch` for any
  third pointer that is not NULL, so it writes through whatever address the caller happened to
  leave in that register. What that does depends on the interpreter, which is the worst way for
  a bug to behave: against zbar 0.23.93, CPython 3.12.13 died with SIGSEGV on 30 runs out of
  30 and 3.13.14 with SIGBUS on 20 out of 20, while 3.14.5 and 3.14.6 completed all 60 runs
  and returned the right major and minor. A crash here is native: no Python traceback, no
  `except` that can catch it, and in a Flet app it takes the session with it — and a run that
  *doesn't* crash is a stray write, not a safe call. Nothing in `decode()` touches it. If you
  want the version on screen, declare it yourself against the handle pyzbar already loaded:
  `ctypes.CFUNCTYPE(c_int, p, p, p)(('zbar_version', pyzbar.wrapper.LIBZBAR))` with three
  `c_uint` `byref`s — which is what the example does, and it reports 0.23.93.
- **`Decoded.data` is `bytes`, not `str`.** Rendering it straight into a `Text` gives the user
  `b'5901234123457'`, quotes and all, and comparing it to a `str` literal is always `False`.
  Use `d.data.decode('utf-8', 'replace')`, and keep the raw bytes for anything binary — a QR
  can legitimately carry a non-UTF-8 payload. `d.type` is a plain `str` holding the
  `ZBarSymbol` member *name* (`'QRCODE'`, `'EAN13'`), not the enum member.
- **The image tuple must carry immutable `bytes`.** `decode((pixels, width, height))` casts
  `pixels` straight to a C pointer, so a `bytearray` or a `memoryview` — the natural thing to
  be holding if you built the raster incrementally — raises `ctypes.ArgumentError` from inside
  the wrapper. Its text is version-specific: CPython 3.12 says `argument 1: TypeError: wrong
  type`, 3.13 and 3.14 say `argument 1: TypeError: 'bytearray' object cannot be interpreted as
  ctypes.c_void_p`. Either way it is not a `PyZbarError`, so `except PyZbarError` will not
  catch it. Call `bytes(buf)` first and catch broad `Exception` around `decode()`.
- **Only 8-bit greyscale.** pyzbar hardcodes the `L800` fourcc and derives bits-per-pixel as
  `8 * len(pixels) // (width * height)`. Handing it RGB — the obvious thing to try — gives
  `PyZbarError: Unsupported bits-per-pixel [24]. Only [8] is supported.`, and a length that is
  not a multiple of `width * height` gives *Inconsistent dimensions*. Convert to greyscale
  before the call; PIL images are converted for you, raw tuples are not.
- **Neither PIL nor numpy is required, and neither is installed by this wheel.** `decode()`
  duck-types on `str(type(image))`: `'PIL.'` in the type name means convert to `L` and
  `tobytes()`, `numpy.ndarray`/`imageio.core.util` means take channel 0 as uint8, and anything
  else is unpacked as `(pixels, width, height)`. The only Pillow requirement in the metadata
  is under the optional `scripts` extra, for a console script.
- **To decode a real photo you want Pillow, and it is on this index.** Building the buffer by
  hand is only reasonable when your app draws the image itself; anything that came off a
  camera or a file picker arrives as JPEG or PNG, and turning that into 8-bit greyscale is the
  work Pillow already does. Add `"pillow"` alongside `"pyzbar"` in `dependencies` and hand
  `decode()` the `Image` object — it takes the PIL branch above and converts for you.
  `pypi.flet.dev` lists Pillow 12.2.0 for cp312, cp313 and cp314 on both platforms (plus
  10.4.0 and 11.1.0 for cp312). Measured on a desktop against this pyzbar and zbar 0.23.93: an
  `L`, an `RGB` and a JPEG-backed image all decode to the same value, while the same RGB
  pixels passed as a raw tuple raise *Unsupported bits-per-pixel [24]*.
- **PDF417 is not compiled into this libzbar, and pyzbar's `ZBarSymbol` enum still lists it.**
  So `symbols=[ZBarSymbol.PDF417]` looks valid and silently returns `[]`. Every other member
  is present: EAN2, EAN5, EAN8, UPCE, ISBN10, UPCA, EAN13, ISBN13, COMPOSITE, I25, DATABAR,
  DATABAR_EXP, CODABAR, CODE39, QRCODE, SQCODE, CODE93, CODE128 — eighteen. The library will
  tell you this itself:
  `zbar_image_scanner_set_config(scanner, symbol, ZBarConfig.CFG_ENABLE, 1)` returns 0 when
  the decoder exists and 1 when the build left it out, which is a better source than any
  document. (`NONE` and `PARTIAL` are scanner states, not symbologies — skip them.)
- **A UPC-A comes back typed `EAN13`.** zbar derives UPC-A from an EAN-13 decode, so a UPC-A
  arrives as a 13-digit `EAN13` with a leading zero, and narrowing to
  `symbols=[ZBarSymbol.UPCA]` returns nothing at all because it disables the source. Include
  `EAN13` in the filter and normalise in your own code.
- **`quality` is not a confidence score you can compare across symbologies.** On the same
  undamaged renderings the example produces, it reads 52 for a Code 128, 103 for an EAN-13
  and 1 for a QR.
- **Rotation is handled for you, and shows up in the result.** The same buffer turned 90°
  clockwise decodes to the same data with `orientation` changing from `'UP'` to `'RIGHT'`.
- **A 1-D symbol only *detects* damage; a QR *corrects* it.** Against zbar 0.23.93, inverting
  a single module loses an EAN-13 at all 95 of its module positions and a Code 128 at 151 of
  its 156 — the five survivors all sit in the stop pattern — while a 25×25 QR at
  error-correction level Q still decoded with 18 of its 625 modules inverted, and at that count
  survived 112 of 120 random damage patterns rather than one lucky one.
  Prefer QR for anything your app generates itself, and for 1-D scanning give the user a
  large, well-lit target and retry across frames.
- **`import pyzbar.pyzbar` is where a missing library surfaces, not the first `decode()`.**
  `pyzbar/wrapper.py` builds a `CFUNCTYPE` prototype for every zbar function at module scope
  and the first one calls `load_libzbar()`, so the `dlopen` happens while the `import`
  statement is still running. Guard the import and put the failure on screen; a `try/except`
  around your first decode is too late.
- **Upstream's own test suite ships inside the wheel.** `pyzbar/tests/` rides along, and
  `test_pyzbar.py` imports numpy and PIL unguarded at module scope — cv2 and imageio too, but
  those two are wrapped in `try/except ImportError` — so it could never run in an app anyway.
  Nothing to do about it; mentioned so nobody tries `import pyzbar.tests`.
- **Licensing:** pyzbar is MIT, but the payload is not. [`flet-libzbar`](../flet-libzbar), the
  library it actually decodes with, is
  **[LGPL-2.1-or-later](https://spdx.org/licenses/LGPL-2.1-or-later.html)**, and on Android the
  [`flet-libiconv`](../flet-libiconv) behind it is **LGPL-2.1-or-later** too. They arrive
  differently: zbar is a separate `.so` the wrapper `dlopen`s, while libiconv is folded statically
  into it. Neither is visible from pyzbar's own metadata, which is why it is stated here. Each
  wheel carries its licence text under `dist-info/licenses/`. For an open-source app there is
  nothing to do. For a closed-source one, LGPL section 6 asks that a user be able to relink your
  app against their own build of the library; a `.so` sealed inside a signed APK or IPA does not
  offer that on its own, and section 6a (shipping your object files) is the usual answer where it
  matters. Flagging it, not advising you — we are not lawyers.

## Build notes (maintainers)

`patches/mobile.patch` carries a full preamble on the loader fallback and `meta.yaml` explains
its own requirements, so what is left here is what a bump can silently invalidate. Note that
most of the consumer-facing claims above are about *libzbar* and about *Flet*, not about
pyzbar, so bumping `flet-libzbar` or Flet invalidates as much as bumping this recipe.

### Recipe shape

One Python file in the wheel differs from upstream's own release: `pyzbar/zbar_library.py`, the
loader. Every other module is byte-identical, and the Android and iOS wheels carry an identical
`pyzbar/` tree differing only in the platform tag their `WHEEL` and `RECORD` record — which is
why the page can point at upstream's docs unchanged. The one thing these wheels drop that PyPI's
ships is the five PNG fixtures under `pyzbar/tests/`, which is most of why they are half the size.

The wheel needs no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry, and that is
worth re-checking rather than assuming: all twenty entries are `.py` or wheel metadata — no
binary, no fixture, nothing that has to exist as a real file on disk — and the only two uses of
`__file__` in an *importable* module are both in the loader, one in a
`platform.system() == 'Windows'` branch that is dead here and one in the mobile fallback, which
tries a path, catches `OSError` and moves on. There is no `importlib.resources`, no
`pkg_resources` and no `getsource` anywhere, so Flet's default compile-to-`.pyc` is safe.

One of the twenty is not a module but upstream's console script,
`pyzbar-<version>.data/scripts/read_zbar.py`, under the wheel's `.data/` scheme root. A plain
`pip install --target` materialises it as `bin/read_zbar.py` plus a generated launcher; Flet's
packaging drops both, and neither a built APK nor a built simulator bundle of the example has a
`bin/` directory at all. Noted so a payload audit does not go looking for it.

**Delivery is the fragile part and it lives outside this recipe.** The loader asks `dlopen` for
a bare soname on Android: `flet-libzbar` ships a single unversioned `opt/lib/libzbar.so` whose
`SONAME` is `libzbar.so` and whose only `DT_NEEDED` entries are `libm`, `libdl` and `libc`, and
serious_python's `copyOpt_<abi>` Gradle task flattens `opt/**/*.so` into `jniLibs/<abi>/` under
the basename alone. The `<site-packages>/opt/lib/libzbar.so` path the wheel nominally unpacks to
is *not* where it ends up, because the site-packages split task skips `opt/` outright. iOS is the
opposite direction: `flet-libzbar` ships a real Mach-O `MH_DYLIB` (not an `MH_BUNDLE`, so forge's
`fix_wheel` conversion never has to touch it) with `install_name @rpath/libzbar.so` and
`LC_BUILD_VERSION` platform 2, `minos 13.0`; serious_python's darwin sync repackages every `*.so`
under site-packages into a signed embedded framework and leaves a `.fwork` text pointer behind,
which iOS CPython's `.fwork`-aware `ctypes.CDLL` dereferences — and that is the loader's *first*
candidate. **The patch's candidate order is load-bearing in opposite directions on the two
platforms.** Built artifacts of the example confirm both halves: an APK with `lib/<abi>/libzbar.so`
under the bare basename for each of the three ABIs and an `assets/sitepackages.zip` carrying the
thirteen `pyzbar/*.pyc` files with no `opt/` directory in it at all, and a simulator bundle with
`Frameworks/opt.lib.libzbar.framework` and a one-line `site-packages/opt/lib/libzbar.fwork`
pointing at it.

**The extra `flet-libiconv` wheel on Android is build-time only.** zbar's QR text extraction needs
iconv, which bionic does not provide at API 24, so the recipe supplies GNU libiconv as a static
archive — `flet_libiconv` ships `opt/lib/libiconv.a` and `libcharset.a` and no `.so` at all. It is
linked *into* `libzbar.so`: `readelf -d` shows no libiconv in `DT_NEEDED`, and the Android binary
carries 78 GNU-libiconv charset names that the iOS one does not. It cannot reach the app either —
`copyOpt` copies only `**/*.so` and the site-packages split skips `opt/` — so it costs a 792 KB
download at build time and 913 bytes in the APK, a `flet_libiconv` `dist-info/` and not one byte
of library, read out of a built APK of the example. iOS links the system
`/usr/lib/libiconv.2.dylib` instead (`otool -L` shows it; `_iconv`, `_iconv_open` and
`_iconv_close` resolve at load), so the recipe is gated to Android. **QR text conversion works the
same on both platforms.**

Sizes, stripped: `libzbar.so` is 1,114,544 bytes on arm64-v8a and 1,014,508 on armeabi-v7a, with
every `PT_LOAD` segment 16 KB (`0x4000`) aligned — what Android's 16 KB page-size devices need.
The iOS dylib is 266,376 bytes on device arm64 and 252,520 on the arm64 simulator; the 4.2× gap
against Android is entirely the statically folded-in libiconv. pyzbar's own wheel is 42,487 bytes
unpacked, 16,532 compressed, of which `pyzbar/tests/` is 16,180.

### Upgrade hazards

- **A serious_python bump can break delivery from a wheel that built green.** Every mechanism in
  the delivery paragraph above is read out of serious_python 4.5.1, and a wrong answer there is
  an `ImportError` on device, not a build failure. Re-check both platforms after a bump.
- **The symbology list is a property of zbar's configure defaults, not of this recipe.**
  `build.sh` passes nothing that enables or disables a decoder, so PDF417 is out because
  upstream leaves it out — which means a `flet-libzbar` bump can change what the consumer
  sections promise without anything in this directory moving.
- **`flet-libiconv` is declared as a runtime dependency but is a build-time one.**
  `recipes/flet-libzbar/meta.yaml` lists it under `requirements.host`, which `fix_wheel`
  promotes to a `Requires-Dist`; `requirements.host_build` exists for exactly this case — a
  dependency that is statically linked in — and does not promote. Moving it there (with a
  build-number bump) would drop a 792 KB download from every Android build with no runtime
  change and nothing above to rewrite: no consumer-facing claim depends on the extra wheel
  arriving.
- **The Android comment in `recipes/flet-libzbar/build.sh` is stale and contradicted by the
  binary it produces.** It says iconv is absent at API 24 so "zbar builds without charset
  conversion"; in fact `flet-libiconv` is on the include and library paths, `AM_ICONV`
  succeeds and GNU libiconv is folded in statically — 78 charset/alias names appear in the
  Android `libzbar.so` and one in the iOS dylib, along with an 848 KB size difference. Do not
  repeat the comment's claim in consumer docs; the platforms have the same QR charset
  capability. Worth fixing in the recipe separately.
- **`android_24_x86` exists only for cp312, and a gap in this index degrades silently rather
  than failing.** PyPI publishes pyzbar as a `py2.py3-none-any` wheel, which any platform tag
  can select, so a slice this index lacks resolves to upstream's unpatched loader with no
  libzbar behind it — a green build that dies on device with *Unable to find zbar shared
  library*. It bites nothing today because `flet build` cannot target that ABI at all (flet-cli
  0.86.5 rejects it with *Invalid Android architecture(s): x86*), but the same mechanism means a
  future upstream release newer than the recipe's pin would outrank the forge wheel on **every**
  slice: pip prefers the higher version over the more specific tag.

### Re-verification checklist

- **Everything the consumer sections claim about the Flet side was read off Flet 0.86.5, which
  pins serious_python 4.5.1.** Re-read it on a serious_python bump.
- **Resolve, one per slice, the way `flet build` does it:** `pip download --only-binary :all:
  --extra-index-url https://pypi.flet.dev --platform <tag> --python-version <ver>` across the
  three Android ABIs Flet targets (`arm64-v8a`, `x86_64`, `armeabi-v7a`), the three iOS slices
  (device arm64, simulator arm64, simulator x86_64) and Python 3.12/3.13/3.14. Last measured
  eighteen for eighteen, each pulling this wheel plus a matching `flet_libzbar`. Check the actual
  resolve rather than trusting a green build.
- **Re-read the eighteen-symbology list off a device** after a `flet-libzbar` bump, using
  `zbar_image_scanner_set_config(..., CFG_ENABLE, 1)` rather than any document. The example
  prints the list it finds.
- **Check `PT_LOAD` alignment** — every segment 16 KB (`0x4000`) aligned on all three Android
  ABIs, which is what Android's 16 KB page-size devices need.
- **Re-measure the sizes and symbol counts rather than adjusting them by eye.** The figures above
  come from the cp314 arm64-v8a and iOS device wheels and from `flet_libzbar` 0.23.93, and were
  taken against build-1 `flet-libzbar` and `flet-libiconv` wheels. Build 2 of each adds a licence
  file to its `dist-info/` and leaves the libraries themselves alone, so the `.so` and `.dylib`
  figures carry over and the 913-byte Android `flet_libiconv` footprint does not.

### Coverage gaps

`tests/test_pyzbar.py` asserts two things and neither is a symbology. `test_libzbar_loads()`
proves the patched loader found and `dlopen`ed something; `test_decode_scan_path()` proves a blank
buffer scans cleanly. Nothing on device proves that QR, EAN-13 or Code 128 decode, that PDF417 is
absent, or that the eighteen-symbology list above is still right — the
[`barcode-roundtrip`](examples/barcode-roundtrip) example is what exercises all of that, so
rebuild and run it on a bump.

Nothing exercises the real intake path either: no test decodes a photo, and neither Pillow nor
numpy is present in any test or in the example, so the two duck-typed input branches are covered
only by the desktop measurement quoted above. The threading figures are development-machine
numbers, not device ones.
