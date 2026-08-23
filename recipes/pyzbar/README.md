# pyzbar

[`pyzbar`](https://github.com/NaturalHistoryMuseum/pyzbar) reads barcodes and QR codes out of
an image. It is a small ctypes wrapper — pure Python, no compiled extension of its own —
around [zbar](https://github.com/mchehab/zbar), which does the actual decoding, and the point
of this recipe is that the zbar shared library travels with it. On a phone that means barcode
reading that never leaves the device: hand it an 8-bit greyscale frame and it hands back the
values, their symbology, where they sit in the image and which way up they are — no network
call and no cloud API. Getting the frames is your problem, though: pyzbar decodes buffers, it
does not talk to a camera.

It is published for **both platforms** — every Android ABI and every iOS slice Flet targets.
What is worth knowing is where the library comes from at load time, which symbologies this
build can actually read, and a small set of API shapes that fail quietly rather than loudly.
Everything below about the Flet side was read off Flet 0.86.5, which pins serious_python
4.5.1.

The only Python file in the wheel that differs from upstream's own release is
`pyzbar/zbar_library.py`, the loader — every other module is byte-identical, and the Android
and iOS wheels carry an identical `pyzbar/` tree, differing only in the platform tag their
`WHEEL` and `RECORD` record — so
[upstream's documentation](https://github.com/NaturalHistoryMuseum/pyzbar) applies unchanged.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pyzbar",
]
```

Nothing else to configure. `flet-libzbar` — the zbar build the wrapper dlopens — is a
`Requires-Dist` of the wheel and comes along on its own; on Android a third wheel,
`flet-libiconv`, is pulled in behind it and contributes nothing at run time (see
[Android notes](#android-notes)).

A bare `pyzbar` resolves from this index on **every slice a `flet build` can produce**.
Measured one resolve per slice, the way `flet build` does it
(`pip download --only-binary :all: --extra-index-url https://pypi.flet.dev --platform <tag>
--python-version <ver>`): the three Android ABIs Flet 0.86.5 targets (`arm64-v8a`, `x86_64`,
`armeabi-v7a`) and all three iOS slices (device arm64, simulator arm64, simulator x86_64), on
Python 3.12, 3.13 and 3.14 — eighteen for eighteen, each pulling the forge wheel plus a
matching `flet_libzbar`.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Every one of the wheel's twenty entries is a `.py` or wheel metadata — no
binary, no fixture, nothing that has to exist as a real file on disk — and the only two uses
of `__file__` in an *importable* module are both in the loader: one in a
`platform.system() == 'Windows'` branch that is dead here, and one in the mobile fallback,
which tries a path, catches `OSError` and moves on. (`pyzbar/tests/` uses `__file__` six more
times to find its PNG fixtures, but those fixtures are not in these wheels and nothing imports
that package — see [Things to know](#things-to-know).) There is no
`importlib.resources`, no `pkg_resources` and no `getsource` anywhere, so Flet's default
compile-to-`.pyc` is safe.

One of the twenty is not a module: `pyzbar-0.1.9.data/scripts/read_zbar.py`, upstream's
console script, which lives under the wheel's `.data/` scheme root rather than in the package.
A plain `pip install --target` materialises it as `bin/read_zbar.py` plus a generated
`bin/read_zbar` launcher, so it is worth knowing it exists — but Flet's packaging drops both:
neither a built APK nor a built simulator bundle of the
[`barcode-roundtrip`](examples/barcode-roundtrip) example has a `bin/` directory at all, and
the only `read_zbar` left is `pyzbar/scripts/read_zbar.pyc`, the module inside the package
proper. Mentioned so a payload audit does not go looking for it.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`barcode-roundtrip`](examples/barcode-roundtrip) — three barcodes encoded, rendered,
  decoded back and checked, with a damage slider and a capability probe.

## Threading

A `decode()` call holds no state that another call could tread on: pyzbar creates the zbar
scanner and the zbar image inside the call and destroys both on the way out, so there is no
shared handle and no lock to take. It also releases the GIL for the duration, because the
bindings are built with `ctypes.CFUNCTYPE`, so decoding several frames really does run in
parallel.

Measured on a development machine against zbar 0.23.93: twelve threads × 200 decodes of
*twelve different* 640×480 frames — 2400 decodes, every one returning its own thread's payload,
zero exceptions. Four threads on that work ran 2.6× faster than one, against 0.9× for a
GIL-bound pure-Python loop of the same duration, which is what makes it a GIL result and not a
scheduling artefact. A single decode of one of those frames costs about 2.7 ms there. That last
number is a desktop number and says nothing about a phone; measure on the device before you
decide what fits in a frame.

That makes [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
safe for decoding, with the two standing Flet caveats: it never retrieves the worker's future,
so an exception raised inside one surfaces nowhere at all — wrap the body — and auto-update
does not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Android notes

The wrapper loads its library by bare soname. `flet-libzbar` ships a single unversioned
`opt/lib/libzbar.so` whose `SONAME` is `libzbar.so` and whose only `DT_NEEDED` entries are
`libm`, `libdl` and `libc`; serious_python's `copyOpt_<abi>` Gradle task copies
`opt/**/*.so` into `jniLibs/<abi>/` under the basename alone, which is exactly the name the
loader asks `dlopen` for. The `<site-packages>/opt/lib/libzbar.so` path the wheel nominally
unpacks to is *not* where it ends up — the site-packages split task skips `opt/` outright and
leaves it to `copyOpt` — so the bare-soname fallback is the one that resolves, and the
loader's candidate order matters here in the opposite direction from iOS. A built APK of the
[`barcode-roundtrip`](examples/barcode-roundtrip) example confirms both halves: a
`lib/<abi>/libzbar.so` under the bare basename for each of the three ABIs, and an
`assets/sitepackages.zip` carrying the thirteen `pyzbar/*.pyc` files with no `opt/` directory
in it at all.

**The extra `flet-libiconv` wheel is build-time only.** zbar's QR text extraction needs iconv,
which bionic does not provide at API 24, so the recipe supplies GNU libiconv as a static
archive: `flet_libiconv` ships `opt/lib/libiconv.a` and `libcharset.a` and no `.so` at all.
It is linked *into* `libzbar.so` — `readelf -d` shows no libiconv in `DT_NEEDED`, and the
Android binary carries 78 GNU-libiconv charset names that the iOS one does not — so the
archive contributes nothing at run time and cannot reach the app either: `copyOpt` copies only
`**/*.so`, and the site-packages split skips `opt/` entirely. It costs a 792 KB download at
build time and 913 bytes in the APK — a `flet_libiconv-1.17.dist-info/` and not one byte of
library, read out of a built APK of the example. Capability is unaffected: **QR text
conversion works the same on both platforms.**

Sizes, per ABI: `libzbar.so` is 1,114,544 bytes on arm64-v8a and 1,014,508 on armeabi-v7a,
stripped, with every `PT_LOAD` segment 16 KB (`0x4000`) aligned — what Android's 16 KB
page-size devices need. pyzbar's own wheel adds 42,487 bytes unpacked (16,532 compressed).

Flet 0.86.5 builds three Android ABIs on every supported Python version, and all three
resolve. The legacy 32-bit `x86` ABI is not one of them — `flet build` rejects it with
*Invalid Android architecture(s): x86* — which is just as well, since this index carries that
slice only for Python 3.12.

## iOS notes

`flet-libzbar` ships a real Mach-O `MH_DYLIB` (not an `MH_BUNDLE`, so forge's `fix_wheel`
conversion never has to touch it): arm64, `install_name @rpath/libzbar.so`,
`LC_BUILD_VERSION` platform 2 with `minos 13.0`. serious_python's darwin step walks
site-packages for `*.so`, repackages each one into a signed embedded framework and leaves a
`.fwork` text pointer where the file was — so `<site-packages>/opt/lib/libzbar.fwork` is what
exists on device, and iOS CPython's `.fwork`-aware `ctypes.CDLL` dereferences it. That is the
loader's *first* candidate, and site-packages stays a real directory on iOS, so this is the
one that hits. A built simulator bundle of the
[`barcode-roundtrip`](examples/barcode-roundtrip) example shows exactly that:
`Frameworks/opt.lib.libzbar.framework` with a one-line
`site-packages/opt/lib/libzbar.fwork` pointing at it.

iOS links the system `/usr/lib/libiconv.2.dylib` (`otool -L` shows it; `_iconv`,
`_iconv_open` and `_iconv_close` are resolved at load), so there is no `flet-libiconv` wheel
for iOS — the recipe is gated to Android — and the dylib is much smaller for it: 266,376 bytes
on device arm64 and 252,520 on the arm64 simulator, against Android's 1.1 MB. The 4.2× gap is
entirely the statically folded-in libiconv.

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
- **`flet run` on your desktop does not use this wheel.** These wheels are Android/iOS
  platform-tagged, so a desktop resolve takes PyPI's `py2.py3-none-any` build, which bundles
  no library and asks `ctypes.util.find_library('zbar')` for a system one. Install zbar
  (`brew install zbar`, `sudo apt install libzbar0`); on macOS `find_library` only sees
  Homebrew's copy under Homebrew's own Python, so a uv-managed or python.org interpreter also
  needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.
- **Upstream's own test suite ships inside the wheel.** `pyzbar/tests/` is 16,180 of the
  wheel's 42,487 unpacked bytes, and `test_pyzbar.py` imports numpy and PIL unguarded at module
  scope — cv2 and imageio too, but those two are wrapped in `try/except ImportError` — so it
  could never run in an app anyway. (Its five PNG fixtures are the one
  thing these wheels drop that PyPI's ships, which is most of why they are half the size.)
  Nothing to do about it — mentioned so a payload audit does not look wrong, and so nobody
  tries `import pyzbar.tests`.
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

- **`tests/test_pyzbar.py` asserts two things and neither is a symbology.**
  `test_libzbar_loads()` proves the patched loader found and `dlopen`ed something;
  `test_decode_scan_path()` proves a blank buffer scans cleanly. Nothing on device proves that
  QR, EAN-13 or Code 128 decode, that PDF417 is absent, or that the eighteen-symbology list
  above is still right — the `barcode-roundtrip` example is what exercises all of that, so
  rebuild and run it on a bump.
- **The symbology list is a property of zbar's configure defaults, not of this recipe.**
  `build.sh` passes nothing that enables or disables a decoder, so PDF417 is out because
  upstream leaves it out. Re-read the list off a device (or off a same-version desktop build)
  after a `flet-libzbar` bump rather than carrying it forward.
- **The delivery mechanism is the fragile part, and it lives outside this recipe.** Android
  depends on serious_python's `copyOpt_<abi>` continuing to flatten `opt/**/*.so` into
  `jniLibs/<abi>/` under the basename alone, and on the site-packages split continuing to skip
  `opt/`; iOS depends on the darwin sync continuing to framework-ize every `*.so` under
  site-packages and leave a `.fwork` pointer behind. The patch's candidate order is
  load-bearing in opposite directions on the two platforms. Re-check both after a
  serious_python bump — a wrong answer here is an `ImportError` on device from a wheel that
  built green.
- **`flet-libiconv` is declared as a runtime dependency but is a build-time one.**
  `recipes/flet-libzbar/meta.yaml` lists it under `requirements.host`, which `fix_wheel`
  promotes to a `Requires-Dist`; `requirements.host_build` exists for exactly this case — a
  dependency that is statically linked in — and does not promote. Moving it there (with a
  build-number bump) would drop a 792 KB download from every Android build with no runtime
  change. Until then the README says the download is expected.
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
  library*. It bites nothing today because `flet build` cannot target that ABI at all, but the
  same mechanism means a future upstream release newer than the recipe's pin would outrank the
  forge wheel on **every** slice: pip prefers the higher version over the more specific tag.
  Check the actual resolve (`pip download --only-binary :all: --extra-index-url
  https://pypi.flet.dev --platform … --python-version …`) rather than trusting a green build.
- **Sizes, symbol counts and the eighteen-symbology list are measured**, from the cp314
  arm64-v8a and iOS device wheels and from `flet_libzbar` 0.23.93. Re-measure rather than
  adjusting by eye.
