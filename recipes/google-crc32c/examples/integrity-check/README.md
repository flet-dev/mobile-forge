# CRC32C integrity check

Store writes an 8 MB blob into the app's durable storage and records one CRC32C per megabyte
beside it. Damage flips a single bit somewhere in those eight million bytes. Verify streams the
file back and names the chunk that stopped matching. The table underneath checksums the same
blob four ways, so you can see what CRC32C costs against the alternatives on the device you are
holding.

What it demonstrates:

- **The job a checksum actually does** — one flipped bit changes nothing an app would notice.
  Verify re-reads the file, compares each chunk against the manifest and reports the byte range
  that moved. The per-chunk manifest is the reason the answer is a range rather than "the file
  is bad".
- **Streaming with
  [`Checksum.consume`](https://github.com/googleapis/google-cloud-python/blob/main/packages/google-crc32c/src/google_crc32c/_checksum.py)** —
  it reads a chunk, folds it into the whole-file checksum and yields it, so one pass produces
  both the value the file is stored under and the per-chunk list that locates damage, without
  ever holding more than one chunk.
- **Two 32-bit CRCs that never agree** — the table shows `google_crc32c.value` next to
  [`zlib.crc32`](https://docs.python.org/3/library/zlib.html#zlib.crc32) on identical bytes.
  Different polynomials: Castagnoli's `0x1EDC6F41` against IEEE 802.3's `0x04C11DB7`. MD5 is
  there because Cloud Storage carries it alongside CRC32C, and SHA-256 because it is what you
  would reach for if the threat were a person rather than a bad cable.
- **Files in the right place** —
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  holds the blob and its manifest, so they are still there when the app restarts.
- **Compute off the UI thread** — every job runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  buttons disabled and a spinner up, and each one ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. The extension holds the GIL while it runs, so the megabyte chunks are what keep the
  spinner turning.

Each rate is the best of five passes after a warm-up one, because eight megabytes goes through
the fastest of these in well under a millisecond and a single cold reading is mostly noise —
timing one call apiece made the zlib row swing threefold over identical bytes.

The header line prints `google_crc32c.implementation` and the machine name. It will read `'c'`,
which says the C extension loaded — not which code path inside it ran. That one only shows up in
the MB/s column, and only on a real device: an emulator's numbers describe the host.

Do not read the table under a desktop `flet run` on macOS, where CRC32C comes out far behind
`zlib.crc32` — about 6.8 GB/s against 42 GB/s on an Apple Silicon laptop. That is PyPI's macOS
wheel carrying only the portable table while `zlib` uses the hardware instruction, not anything
about CRC32C. The mobile wheels compile the instruction path in on every slice but
`armeabi-v7a`.

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
