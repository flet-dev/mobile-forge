# msgpack pack-compare

One screen that encodes the *same* Python objects with msgpack and with `json`, and reports
three things the choice between them actually turns on: how many bytes each costs and how long
each takes, which values survive a round trip unchanged, and what a single flipped bit does to
each frame.

Every payload is generated in the app rather than bundled, so the same build produces the same
bytes on every device and two phones can be compared with each other and with the desktop
figures below.

What it demonstrates:

- **Where the format wins, per payload.** Measured on an Apple M4 desktop under CPython 3.14.6
  with msgpack 1.1.2, the three pickers give: *api records* 259,089 bytes against json's 338,487
  (23% smaller); *sensor grid* — 10,000 floats and nothing else — 91,203 against 182,388, exactly
  half; *photo blobs* — 200 × 8 KiB of opaque bytes — 1,639,034 against 2,185,439. That last one
  is the interesting one, because json has no binary type at all: the app base64-encodes the
  blobs for the json column, which is what a real app would have to do, and pays 33% for it.
  msgpack's total is 634 bytes more than the raw payload.
- **That encoding cost is not symmetric.** On those blobs msgpack packs in 0.09–0.11 ms where
  the json column needs 3.97–4.22 ms across three runs — the msgpack path is close to a memcpy
  while the json path has to base64 1.6 MB and then escape it. On the float grid, 0.10–0.12 ms
  against 2.32–2.35 ms. Only on the api records, where most of the bytes are short strings
  either way, do the two come close: 0.72–0.74 ms against 1.88–1.98 ms.
- **What survives a round trip, and what quietly does not.** The middle table runs twelve values
  through both formats and prints `exact`, or the exception, or *the type and value that came
  back instead*. Desktop results: json turns the integer key in `{1: "a"}` into `'1'` without a
  word, and refuses `bytes` and `datetime` outright; msgpack keeps the key but raises
  `ValueError` rather than decode it, until you pass `strict_map_key=False`. `2**64` overflows
  msgpack and is fine in json. A tz-aware `datetime` packed with `datetime=True` comes back a
  `msgpack.Timestamp`, not a `datetime`, unless you *also* pass `timestamp=3` — the last two rows
  are the same value with and without that second flag.
- **The two switches that change a type silently.** Under *same bytes, different type*:
  `packb(b"id", use_bin_type=False)` round-trips to the **str** `'id'`, and
  `unpackb(packb("id"), raw=True)` round-trips to the **bytes** `b'id'`. Neither raises. Both are
  one keyword away from code that looks symmetric.
- **That a msgpack frame has no checksum — and neither does JSON.** The bottom line flips one
  bit at a time into a msgpack frame and into the json encoding of the same 200 records. On
  desktop, 120 flips gave msgpack 34 raised / 86 silently wrong / 0 unaffected and json 68
  raised / 52 silently wrong / 0 unaffected. Binary loses this comparison, because more of its
  bits mean something and more of json's corruption lands somewhere that is a syntax error — but
  neither format detects damage, and the honest conclusion is to store a hash beside anything you
  persist.
- **Which msgpack is actually running.** The header line reports
  `msgpack.Packer.__module__`: `_cmsgpack` is the C extension, `fallback` is the pure-Python
  implementation that `msgpack/__init__.py` substitutes without a word if the extension fails to
  load. On the same desktop the fallback packs the api-records payload in 11.60 ms rather than
  0.71 — slower than `json` — so this is worth looking at once on a real device.
- **That Flet is already using the same module.** The header also compares the app's `msgpack`
  object with the one in `flet.messaging.protocol`, which is what Flet encodes every control
  message with. It should read *same module Flet encodes controls with*: the wheel is in the app
  because `flet` depends on it, not because this example does.
- **Verified numbers, not printed ones.** Every encoding is decoded and compared against the
  original before its row is shown, and the summary line says how many of the formats came back
  equal.
- **Degrading instead of crashing.** The import of `msgpack` is guarded. Without the wheel the
  header turns red and names what the import raised, the json column still runs end to end, and
  the msgpack cells read `-`.

All the figures above are **desktop** measurements (Apple M4, macOS 26.6, CPython 3.14.6,
msgpack 1.1.2 from PyPI). The point of running the app is to replace them with the device's own.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

It also runs on the desktop with `uv run flet run`, which is the fastest way to see the tables
before committing to a build.
