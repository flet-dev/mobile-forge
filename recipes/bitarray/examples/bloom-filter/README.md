# bitarray Bloom filter

A 65,536-bit Bloom filter, drawn at one pixel per bit and priced against the two things
you would otherwise reach for. A slider chooses how many members go in — 2,000, 5,000,
10,000, 20,000 or 40,000 — and each release rebuilds the filter, probes it with 50,000
keys that are not in it, and reports what came back.

What it demonstrates:

- **A picture that is not a rendering of the data — it *is* the data.** PNG's
  bit-depth-1 greyscale format packs eight pixels per byte, leftmost pixel in the most
  significant bit, which is precisely how a big-endian
  [bitarray](https://github.com/ilanschnell/bitarray) packs its bits. So each scanline of
  the image is a slice of `filter.tobytes()` behind a zero filter byte, and `bitmap()`
  contains no per-pixel loop at all. Checked on a desktop with two decoders that share no
  code with this app — macOS `sips` converting the 256×256 PNG to a 24-bit BMP, and Tk's
  own PNG reader — and checked **per pixel**, not by counting: both report 30,045 white
  pixels against `filter.count()` of 30,045, and both disagree with the bitarray on 0 of
  the 65,536 pixels. The count alone would not settle it, since reversing the bit order
  within each byte or flipping the row order leaves it unchanged; a filter with only bits
  0, 1, 2, 8, 256, 300 and 65,535 set decodes to exactly those coordinates.
- **A false-positive rate measured, not asserted.** Each pass counts how many of 50,000
  non-member keys the filter wrongly accepts and prints that beside `fill^k` — the rate
  the filter's own measured density predicts — with the 95% band for that many samples.
  Every stop should land inside the band; a row that says `OUTSIDE` is worth
  investigating.
- **What a bit costs against the alternatives.** The filter's buffer is always 8,192
  bytes. The same membership question as a Python `set` of the member keys is measured
  live with `sys.getsizeof` on the table plus every key object, and at 40,000 members that
  came to 3,897,368 bytes on a desktop — 476× the filter. `[False] * 65_536`, the same
  65,536 booleans as a list of pointers, is 524,344 bytes.
- **Determinism you can check.** Keys are `b"user-%07d"` and `b"probe-%07d"`, hashed with
  SHA-256 rather than the builtin `hash()`, which is salted per process. So every device
  running this app should produce the same bit counts and the same false-positive counts
  as the table below — a difference is a real difference, not noise. Nor does the
  interpreter move them: every figure in that table came out identical on CPython 3.12.13
  and 3.14.6, including the `set(keys)` byte totals.
- **The two `page.run_thread` rules, honoured explicitly.** The worker body is wrapped in
  `try/except` because
  [`run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) never
  retrieves the future and would swallow the exception entirely, and it ends with an
  explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
  because auto-update does not reach a background thread. The slider disables itself for
  the duration, which is what stops two releases from running concurrently and writing the
  same controls — `run_thread` submits to a shared pool, so they genuinely would.
- **The first pass goes through the worker too, and that is not a stylistic choice.** A
  synchronous `main` runs on Flet's event loop thread and the socket writer is a task on
  that same loop, so a first pass computed inline in `main` leaves the layout `page.add`
  queued in memory until `main` returns. Measured with the real desktop client, patching
  `asyncio.StreamWriter.write` to timestamp every frame: with the pass inline, `main` was
  entered at t=2.672 s and the 807-byte layout frame was written at t=3.652 s — 980 ms in
  which the client had nothing to draw. Handing the first pass to `page.run_thread`
  instead put the layout on the wire 1 ms after `main` returned, with the bitmap
  following ~1 s later. Same total work, but you watch it happen instead of watching
  nothing.
- **Honest behaviour where the package is absent.** The import is guarded, so a run
  without bitarray shows the exception and what to add to `pyproject.toml` instead of
  failing to start.

## What it should print

Measured on a desktop — macOS arm64, CPython 3.12.13, bitarray 3.8.1. These are the
numbers to compare a device against; only the timings should move.

| members | hashes | bits set | fill | false positives / 50,000 | `fill^k` predicts |
| --- | --- | --- | --- | --- | --- |
| 2,000 | 8 | 14,244 | 21.7% | 0 | 0.2 ± 1.0 |
| 5,000 | 8 | 29,947 | 45.7% | 98 | 95.1 ± 19.1 |
| 10,000 | 5 | 34,932 | 53.3% | 2,168 | 2,151.2 ± 88.9 |
| 20,000 | 2 | 29,984 | 45.8% | 10,454 | 10,466.2 ± 178.3 |
| 40,000 | 1 | 30,045 | 45.8% | 22,913 | 22,922.5 ± 218.4 |

With that machine otherwise idle a pass cost 64 to 75 ms: 2 to 27 ms to insert, 40 to 64
ms for the 50,000 probes, 0.2 to 0.3 ms for the bitmap and 0.3 to 8 ms to build the
comparison `set`. Repeating the measurements while the machine was loaded gave two to
three times those figures, so read them as a floor rather than a specification — and note
that they are desktop numbers. No device timing is claimed here.

## Try it

Runs on the desktop as well as on a phone, because bitarray publishes desktop wheels for
every host you would build from:

```bash
uv run flet run
```

[Build](https://flet.dev/docs/publish/) it for a device with:

```bash
uv run flet build apk
uv run flet build ios-simulator
```

It bundles no assets, writes no files and makes no network requests.
