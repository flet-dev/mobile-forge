# zstd level lab

One screen that answers the two questions a consumer actually has — *which level?* and
*is zstd even the right codec for this payload?* — by measuring both on the phone in front
of you instead of quoting somebody's benchmark. A slider walks the level range at the
positions that matter (-5, -1, 1, 2, 3, 6, 10, 15, 19); let it go and the app compresses a
generated 879,176-byte payload at that level and, on the same bytes, with `zlib` 9, `bz2` 9
and `lzma` preset 1, then fills a table with bytes, ratio, compress ms and read-back ms for
each. A second card does the small-records story: it trains a 16 KB dictionary and
compresses 2,000 records three ways.

What it demonstrates:

- **Ratio is not monotonic in level, and the app proves it on its own data.** Reading the
  `bytes` column across the slider on a desktop run: level 2 → 83,949 beats level 3 →
  87,141 *and* level 6 → 93,557, and level 10 → 66,512 beats level 15 → 68,612. A higher
  number is not a smaller file, so the only way to choose is to measure — which is what the
  slider is for.
- **The read side is flat, and that is the reason to pick zstd on a phone.** Decompression
  measured 0.20–0.34 ms at every level from -5 to 19, against `bz2` 9's 6.4–7.1 ms and
  `lzma` preset 1's 3.1–3.2 ms for files of comparable size. You choose a level for what it
  costs to *write*; reading back costs the same either way.
- **Three independent correctness checks, so a wrong answer is visible rather than merely
  slower.** Every codec's output must decompress back to the exact source bytes (`4/4
  codecs round-tripped exactly`); `zstandard.frame_content_size(frame)` must equal
  `len(payload)`, read out of the frame header without decompressing anything, so it cannot
  agree with the round trip by accident; and a `hashlib.sha256` of the source is compared
  against one of the zstd round trip, both prefixes printed beside the verdict. On the
  error path both tables are cleared, because timings left beside a failure read as though
  they described it.
- **The memory cost, read off the library rather than quoted.**
  `ZstdCompressionParameters.from_level(level, source_size=…).estimated_compression_context_size()`
  is printed under the table for the level in play — 1.2 MB at level 3 against 17.3 MB at
  level 19 on this payload — beside
  `zstandard.estimate_decompression_context_size()`, which is 94 KB whatever the level. That
  asymmetry is the whole reason a phone can read a level-19 frame it should not have
  written. A warning band appears from level 15 up.
- **What a dictionary is worth, and when to use a single frame instead.** 2,000 JSON records
  averaging 214 bytes, 428,694 bytes in total, at level 1: a frame per record with no
  dictionary compresses to 342,030 (ratio 1.25 — nearly nothing), the same records with a
  16 KB trained dictionary to 101,620 (ratio 4.22), and all of them in one frame to 41,680
  (ratio 10.29). This card follows the slider like the codec table does, so the screen opens
  on level 3, where the same three rows read 347,797 / 98,257 / 43,467 — move the dial to
  level 1 to reproduce the figures above. Those three stay in that order at every level on
  the dial. So use a
  dictionary when records must stay independently addressable, and batch when they need not.
  The card also prints the trained `dict_id()` and shows once that decompressing with a
  *different* dictionary raises `ZstdError: decompression error: Dictionary mismatch` rather
  than returning garbage.
- **The two habits that keep a phone out of trouble, performed rather than described.** The
  streaming line writes one frame to
  [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
  through `stream_writer(handle, size=len(payload))` and reads it back through
  `stream_reader` in 64 KB chunks, then deletes it. The `size=` is what puts a content size
  in the frame header — printed, so you can see it is there — and the chunked read is what
  stops an oversized frame from materialising in one allocation. `write_checksum=True` is on,
  because a file in the cache directory can be half-written when the app is killed.
- **Which zstd this build actually has.** The header lines carry `zstandard.__version__`,
  the compiled-in `zstandard.ZSTD_VERSION`, `zstandard.backend` (`cext`, the C extension —
  the CFFI backend also ships in the wheel but is never selected on CPython), the Python
  version, `page.platform.value`, and `compression.zstd`'s `zstd_version` or `absent`. That
  last field is the one to read on a 3.14 device: the standard library grew its own zstd in
  3.14, and whether this app's runtime has it is a fact about the runtime, not something to
  predict.
- **Compute off the UI thread, safely.** The run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture is one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. Every `ZstdCompressor` and `ZstdDecompressor` is built *inside* the worker
  and never shared, because two threads on one compressor kill the process with a native
  signal and two threads on one decompressor quietly return the wrong bytes — see
  [Threading](../../README.md#threading) in the recipe README. The slider's
  `disabled` flag is set in the handler rather than in the worker, where it would not have
  taken effect before Flet pushed the control states, and it matters more here than usual
  because two overlapping runs would write the same cache file.

The payload and the records are generated in code with no randomness, so the same slider
position produces the same bytes on every install and two devices can be compared directly.
Nothing is downloaded and no asset is bundled. Timings are best-of-three while a call stays
under 20 ms and single-shot above it, so level 19 — a quarter of a second per call on
desktop — does not turn one slider release into a stall.

Level 22 is deliberately not on the dial. Streaming a 3.85 MB input at level 22 *without*
`size=` peaked at 565.6 MB of RSS in a fresh desktop process against a 30.3 MB baseline,
and it is the one setting that can get an app killed rather than merely make it slow; the
recipe README's [Things to know](../../README.md#things-to-know) carries the numbers.

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

`pyproject.toml` pins both `flet` and `zstandard`, which is the combination that was
verified. `requires-python` stays at `>=3.10` — zstandard's own floor is `>=3.9`, so it adds
none of its own — checked the way a consumer meets it, by copying that `pyproject.toml`
alone into an empty directory and running `uv lock` there.
