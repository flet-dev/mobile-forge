# brotli bake-off

One screen that puts brotli next to the four codecs Python already has — `zlib`, `gzip`,
`lzma` and `bz2` — on the *same* bytes, at four brotli quality levels, and reports size,
compression time and decompression time for each. Under it, the same comparison on inputs
too short to compress at all, and a bit-flip sweep that shows what a damaged frame does.

Every payload is generated in the app rather than bundled, so the same build produces the
same bytes on every device and two phones can be compared with each other and with the
desktop figures below.

What it demonstrates:

- **Where brotli wins, in one row.** On a 338,073-byte HTML payload measured on an
  Apple M4 desktop under CPython 3.14.5, brotli quality 5 produced 14,397 bytes in about
  1.0 ms where `zlib` at level 9 produced 24,579 bytes in about 2.0 ms — 41% smaller *and*
  faster. The same pairing on 339,362 bytes of log lines: 29,899 bytes against 48,742.
- **Where it loses, in the row underneath.** On that HTML payload the smallest frame in the
  table is `bz2` at level 9 (9,761 bytes), not brotli quality 11 (11,068). On the JSON
  payload `lzma` wins too (21,320 against 21,593). And deflate reads back faster than
  brotli: on the log payload, `gzip` decompressed at 3,002 MB/s against brotli quality 5's
  1,333 MB/s. The table shows all of that rather than only the flattering half.
- **What quality 11 costs.** 394–425 ms for that HTML payload across runs, against about
  1.0 ms at quality 5 — roughly 390× the time for 23% fewer bytes, on a desktop. A phone
  will be slower still, so the picker is disabled while a run is in flight and the work
  happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread),
  because at that cost it is not a tap.
- **The 122,784-byte dictionary brotli carries.** The *short inputs* table is where it
  shows: three URLs, 106 bytes, become 43 with brotli, 61 with `zlib` and 73 with `gzip`;
  an HTML fragment of 86 bytes becomes 75, 91 and 103. Nothing was trained and no
  dictionary was supplied — those words are already compiled into the wheel. The last row
  of that table is 4,096 random bytes, the control: brotli returns 4,100, `zlib` 4,107 and
  `gzip` 4,119, because nothing helps there and every codec has to add framing.
- **That a brotli frame has no checksum.** The bottom line flips one bit at a time into a
  brotli frame and into a `gzip` frame of the same payload. On desktop, 120 flips into the
  brotli frame produced 71 exceptions and **49 decompressions that returned the wrong bytes
  and raised nothing**; the same 120 flips into the `gzip` frame produced 120 exceptions and
  no silent failures. gzip is not all-seeing either — 52 of the 80 bits in its 10-byte header
  are fields it ignores, so a flip there is accepted and hands back the original bytes, and a
  device may show a small `unaffected` count for gzip. What it never does is return the
  wrong bytes, and brotli's format carries nothing that could stop it. If you store brotli
  frames on a device, store a hash beside them.
- **Verified numbers, not printed ones.** Every frame is decompressed and compared against
  the source before its row is shown, and the header line reports how many of the eight
  round-tripped exactly plus a SHA-256 of the source against a SHA-256 of the round trip.
- **Degrading instead of crashing.** The import of `brotli` is guarded. Without the wheel
  the header turns red and names what the import raised, the four stdlib codecs still run,
  and the brotli column of the short-inputs table reads `-`.

All the figures above are **desktop** measurements (Apple M4, macOS 26.6, CPython 3.14.5,
Brotli 1.2.0 from PyPI). The point of running the app is to replace them with the device's
own.

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

It also runs on the desktop with `uv run flet run`, which is the fastest way to see the
table before committing to a build.
