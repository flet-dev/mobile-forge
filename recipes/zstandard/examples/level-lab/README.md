# zstd level lab

One screen that answers the two questions a consumer actually has — *which level?* and *is
zstd even the right codec for this payload?* — by measuring both on the phone in front of you
instead of quoting somebody's benchmark. A slider walks the level range at the positions that
matter (-5, -1, 1, 2, 3, 6, 10, 15, 19); let it go and a generated 879,176-byte payload is
compressed at that level and, on the same bytes, with `zlib` 9, `bz2` 9 and `lzma` preset 1.
A second card trains a dictionary and compresses 2,000 small records three ways.

What it demonstrates:

- **That ratio is not monotonic in level, and that the read side is flat.** Walk the slider
  and the `bytes` column goes back up in places — level 2 beats level 3 and level 6 on this
  payload — while the `read ms` column barely moves from -5 to 19, where `bz2` and `lzma` read
  back an order of magnitude slower for output of comparable size. You choose a level for what
  it costs to *write*.
- **Three independent correctness checks, so a wrong answer is visible rather than merely
  slower.** Every codec's output must decompress back to the exact source bytes, and the count
  that says so is flagged `← FAILURE` the moment one does not;
  [`frame_content_size`](https://python-zstandard.readthedocs.io/en/latest/misc_apis.html#zstandard.frame_content_size)
  must equal `len(payload)`, read out of the frame header without decompressing anything, so
  it cannot agree by accident; and a `hashlib.sha256` of the source is compared against one of
  the round trip. On the error path both tables are cleared, because timings left beside a
  failure read as though they described it.
- **The memory cost, read off the library rather than quoted.**
  `estimated_compression_context_size()` is printed under the table for the level in play —
  about 1.3 MB at level 3 against about 18 MB at level 19 on this payload — beside
  `estimate_decompression_context_size()`, which is 96 KB whatever the level. That asymmetry
  is the whole reason a phone can read a level-19 frame it should not have written. A warning
  band appears from level 15 up.
- **What a dictionary is worth, and when to use a single frame instead.** The second card
  compresses 2,000 JSON records averaging 214 bytes three ways: a frame per record, a frame
  per record with a trained 16,384-byte dictionary, and all of them in one frame. Ratios run
  from barely-above-1 to roughly 4× and 10× respectively, in that order at every level on the
  dial. It also prints the trained `dict_id()` and shows that decompressing with a *different*
  dictionary raises `ZstdError: decompression error: Dictionary mismatch` rather than
  returning garbage.
- **The two habits that keep a phone out of trouble, performed rather than described.** One
  frame is written to
  [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
  through `stream_writer(handle, size=len(payload))` and read back through `stream_reader` in
  65,536-byte chunks, then deleted. The `size=` is what puts a content size in the frame header
  — printed, so you can see it is there — and the chunked read stops an oversized frame from
  materialising in one allocation. `write_checksum=True` is on, because a file in the cache
  directory can be half-written when the app is killed.
- **Which zstd this build actually has.** The header carries `zstandard.__version__`, the
  compiled-in `ZSTD_VERSION`, `zstandard.backend` (`cext` is the C extension, which is the
  evidence it loaded), the Python version, `page.platform.value`, and `compression.zstd`'s
  version or `absent` — the field to read on a 3.14 device, where the standard library has a
  zstd of its own.
- **Compute off the UI thread, safely.** The run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), started
  from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture is one run, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. Every compressor and decompressor is built *inside* the worker and never shared: two
  threads on one of either corrupts the run, loudly or silently — see
  [Threading](../../README.md#threading).

The payload and the records are generated in code with no randomness, so the same slider
position produces the same bytes on every install and two devices can be compared directly.
Level 22 is deliberately off the dial: streaming without `size=` at that level peaked at
565.6 MB of resident memory in a fresh desktop process, and it is the one setting that can get
an app killed rather than merely make it slow.

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

`pyproject.toml` pins both `flet` and `zstandard`, which is the combination that was verified.
`requires-python` stays at `>=3.10`, checked the way a consumer meets it: by copying that
`pyproject.toml` alone into an empty directory and running `uv lock` there.
