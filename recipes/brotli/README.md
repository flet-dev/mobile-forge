# brotli

[`brotli`](https://github.com/google/brotli) is Google's general-purpose compressor — the
`br` of `Content-Encoding: br`, specified in
[RFC 7932](https://datatracker.ietf.org/doc/html/rfc7932). What it has that `zlib` does not is
**a 122,784-byte dictionary of common web text compiled into the binary**, present in every
slice of this wheel, and it is what lets brotli compress payloads far too short for deflate to
find anything in: three URLs totalling 106 bytes come out at 43 bytes against `zlib`'s 61 and
`gzip`'s 73. On larger payloads the cheap part of its quality range wins on both axes at once,
producing smaller output than `zlib` level 9 in less time.

It is not a universal upgrade. `zlib` and `gzip` decompress two to two-and-a-half times
faster, `lzma` and `bz2` sometimes produce smaller output, and quality 11 costs hundreds of
milliseconds on a phone. The one that can hurt you quietly: **a brotli frame carries no
checksum**, so a damaged frame can decode to the wrong bytes and raise nothing — see
[Integrity](#integrity).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "brotli",
]
```

The import is always `brotli`. The distribution name is spelled two ways in the wild —
capitalised `Brotli` in older releases, lowercase since — and pip normalises both to the same
project, so write it however you like.

The entry belongs in top-level `[project] dependencies` and not in a `[tool.flet.android]` /
`[tool.flet.ios]` table: `flet build` resolves for the build host first, and PyPI has a
desktop wheel for every host you would build from.

**Adding this dependency also turns on `br` in Flet's own HTTP client.**
[httpx](https://www.python-httpx.org/) registers its brotli decoder only if the import
succeeds, so with brotli in the build `httpx.Client().headers["accept-encoding"]` becomes
`gzip, deflate, br` and an API that serves brotli returns smaller responses without a line of
code from you. [Things to know](#things-to-know) has the caveat about who does the decoding.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`bake-off`](examples/bake-off) — measures brotli at four quality levels against `zlib`,
  `gzip`, `lzma` and `bz2` on the same bytes.

## Usage in a Flet app

Two calls do the job, and the result is `bytes` you can put straight on screen:

```python
import brotli
import flet as ft

frame = brotli.compress(payload, quality=5)   # 5 is the level worth defaulting to
restored = brotli.decompress(frame)

saved = ft.Text(f"{len(payload):,} B → {len(frame):,} B")
```

Those two take and return whole `bytes` objects. The
[Python binding](https://github.com/google/brotli/tree/master/python) exposes two more names,
`Compressor` and `Decompressor`, for streaming a payload you would rather not hold twice.

### Storage

**There is no file API.** `gzip`, `bz2`, `lzma` and the sibling [`zstandard`](../zstandard)
recipe all give you an `open()` that returns a file object; brotli gives you the four
callables above and no file object anywhere, so writing a compressed file is yours to do:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "snapshot.br")
compressor = brotli.Compressor(quality=5)
with open(path, "wb") as handle:
    for chunk in chunks:
        handle.write(compressor.process(chunk))
    handle.write(compressor.finish())
```

Reading it back streams the same way: a `Decompressor` returns whatever each piece of input
yielded, so an oversized payload can be written out as it arrives instead of being held whole
— which one call to `brotli.decompress()` cannot do.

Where the file goes is the usual Flet split:
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for something the app owns and cannot rebuild,
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for something derived, and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch. Write a digest beside whatever you keep — see [Integrity](#integrity) for why
that is not optional here.

### Threading

**The extension releases the GIL, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys real
parallelism.** Measured on desktop against a pure-Python counting thread, which can only
advance while it holds the GIL: it kept 94% of its idle rate while another thread ran a
quality-11 compression, against 49% for that same control competing with pure-Python work.
Four concurrent quality-11 compressions took 492 ms where four serial ones took 1,460 ms.

**One `Compressor` object must not be used from two threads at once.** The binding sets a flag
around each call to `process`, `flush` and `finish`, so an overlapping caller is rejected with
`brotli.error: brotli: encoder concurrent access` rather than being let into the encoder. The
rejection is per thread and all-or-nothing: with eight threads pushing 200 blocks each through
one shared `Compressor`, three to six threads lost the race and then went on losing it for
every block they had. **Their data is simply gone** — the guard protects the process, not your
bytes. The same eight threads with a `threading.Lock` held around `process()` produced zero
exceptions and all 1,600 blocks. `Decompressor` carries the same guard and reports
`brotli: decoder concurrent access`.

Module-level `brotli.compress()` and `brotli.decompress()` are safe from any number of
threads, because each call builds its own state. Reach for a `Compressor` only when you need
streaming, and then give each thread its own or serialise it behind a lock.

`run_thread` submits to a shared thread pool, so two taps in quick succession really do
overlap — and it never retrieves the worker's future, so the `brotli.error` above would
surface nowhere at all. Wrap worker bodies in `try`/`except`, and end them with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads.

### Quality

Quality is not a linear dial, and the cliff is between 9 and 10. On 339,362 bytes of log
lines, best of three on an Apple M4 desktop under CPython 3.14.5:

| quality | bytes | ratio | ms |
| --- | --- | --- | --- |
| 0 | 71,849 | 4.72 | 0.7 |
| 1 | 45,756 | 7.42 | 0.5 |
| 2 | 40,301 | 8.42 | 0.7 |
| 3 | 44,666 | 7.60 | 1.0 |
| 4 | 42,879 | 7.91 | 1.4 |
| 5 | 29,899 | 11.35 | 2.5 |
| 9 | 28,356 | 11.97 | 5.4 |
| 10 | 20,950 | 16.20 | 146.2 |
| 11 | 18,468 | 18.38 | 339.6 |

Take three things from that. **Quality 3 is worse than quality 2** — bigger *and* slower — so
the ladder is not monotonic and a level picked by intuition can cost you on both axes at once.
**Quality 10 costs 27× what 9 costs** for 26% fewer bytes, and on a device the top of the
ladder runs to hundreds of milliseconds, so anything above 9 belongs in
[`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind a
spinner, never on a tap. And **quality 5 is the value worth defaulting to**: it is where
context modelling and the extensive reference search switch on, and against `zlib` level 9 it
produced 39% smaller output in 0.42× the time here, 41% smaller on an HTML payload.

Reading back is the axis where brotli loses to deflate and wins against everything else.
Decompression throughput on the same payload, best of five runs of fifty iterations: about
3,000 MB/s for `gzip` and `zlib`, 1,100–1,400 MB/s for brotli across qualities 5 to 11, 230
MB/s for `lzma` and 130 MB/s for `bz2`. At matched output size the gap is decisive — brotli
quality 11 produced 18,468 bytes and read back in 0.30 ms, `lzma` preset 6 produced 18,808
bytes and read back in 1.48 ms, **5× slower**. So brotli is the choice against `lzma`, and
`zlib` remains the choice when read latency is all that matters.

### Integrity

**A brotli frame has no checksum, no length field and no trailer.** The format does not carry
one and the binding exposes nothing that could check one. Measured with 400 single-bit flips
per run across three independent seeds: a quality-5 frame gave 255–273 exceptions against
**127–145 decompressions that returned the wrong bytes and raised nothing**, and a quality-11
frame 328–334 against 66–72. Roughly a third of the damage gets through at quality 5 and a
sixth at quality 11 — never none of it. The same sweeps against `gzip`, `zlib`, `lzma` and
`bz2` frames of that payload returned wrong bytes **zero** times.

The common cases *are* caught: `brotli.decompress()` raises
`brotli.error: brotli: decoder failed` on a truncated frame and on garbage. It is the flipped
bit in the middle that gets through, and a phone's filesystem is exactly where a half-written
file happens. Write a `hashlib.sha256` digest beside anything you persist and check it on
read; that is the equivalent of what the other four codecs give you for free.

### App size

Each slice is roughly 380–450 KB compressed and 740–990 KB unpacked, and about 99% of that is
the single extension — there is no test suite or data directory for
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) to remove. An
Android APK covering all three ABIs carries approximately 2.55 MB of brotli: about 730 KB for
armeabi-v7a, 870 KB for arm64-v8a and 950 KB for x86_64. Use an app bundle, split APKs, or
narrow [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
to the ABIs you actually ship, which takes roughly 1.7 MB back. iOS slices run 7–9% larger
than the Android arm64 one for the same source.

These figures describe the package payload, not the exact amount added to the final APK or
IPA; packaging and compression determine that. Re-measure with a tool reporting decimal bytes
— `du -h` uses binary units and shows that 2.55 MB payload as 2.4 M.

### Other considerations

A desktop `flet run` uses PyPI's own wheel, built from the same sdist, so the API is
identical. What differs is speed: nearly every absolute figure on this page was measured on a
laptop, a phone is several times slower, and quality 11 is where that gap turns a delay into a
stall. Treat the ratios as transferable, and re-measure the milliseconds on a device — the
[`bake-off`](examples/bake-off) example exists to do exactly that. `brotli.__version__` is
built from `BrotliDecoderVersion()` rather than from package metadata, so printing it on
device also tells you which libbrotli is compiled into the wheel you resolved — a check no
`importlib.metadata` lookup can make.

No module in the package reads a file next to itself, so Flet's default
[compile-to-`.pyc`](https://flet.dev/docs/publish/#compilation-and-cleanup) and Android's
zipped site-packages are both safe.

## Things to know

- **`MODE_TEXT` does nothing.** `params->mode` is read at exactly one place in the encoder,
  and that line tests only `BROTLI_MODE_FONT`. `MODE_TEXT` therefore falls into the same
  branch as `MODE_GENERIC` and produces byte-identical output; verified on three payloads at
  two qualities each, zero difference every time. `MODE_FONT` does change the output, and only
  at quality 4 and above, since below that the encoder ignores the distance parameters it
  sets. Use it for WOFF 2.0 and ignore the other two.

- **Compression memory peaks at quality 9, not at quality 11.** Peak resident-set growth while
  compressing the same 339,362-byte log payload at the default `lgwin=22`, each figure from a
  fresh process and cross-checked against the kernel's own accounting via `/usr/bin/time -l`:
  about 0.6 MB at quality 0, 2.5 at 5, 10 at 7, 18 at 8, **35 at 9**, 13 at 10 and 15 at 11.
  The maximum is quality 9 — more than twice what quality 11 costs — because 9 is the last
  rung using the quality-sized hash table and 10 switches to the window-sized binary-tree
  hasher. The rung that looks like the last cheap one on the clock is the most expensive one
  on memory, which is worth knowing before defaulting to it on a phone. `lgwin` is the lever
  and it bites hardest exactly there: quality 9 drops to about 2 MB at `lgwin=16`, at the cost
  of ratio on data with long-range repetition. Decompression is cheap whatever wrote the frame
  — around 1 MB above baseline. Two concurrent compressions ask the OS for twice the figure at
  once, and an Android low-memory kill is not something `try`/`except` can catch.

- **Short inputs are the whole reason to prefer it, and the margin is large.** Compressed at
  quality 11, against `zlib` level 9 and `gzip` level 9:

  | input | raw | brotli | zlib | gzip | lzma |
  | --- | --- | --- | --- | --- | --- |
  | three URLs | 106 | **43** | 61 | 73 | 116 |
  | HTML fragment | 86 | **75** | 91 | 103 | 144 |
  | HTTP response headers | 113 | **92** | 108 | 120 | 168 |
  | one log line | 88 | **83** | 96 | 108 | 144 |
  | one JSON record | 81 | **78** | 79 | 91 | 136 |

  brotli is the only one of the four that shrinks all five, and the empty string costs it
  1 byte against `zlib`'s 8 and `gzip`'s 20. The JSON record is the honest counter-example: 78
  against 79 is not a reason to change anything, because the dictionary holds web text and a
  record of opaque identifiers is not web text.

- **`brotli.error` derives straight from `Exception`, not from `OSError` or `ValueError`.**
  `except OSError:` around a decompression catches nothing, and an unhandled exception in a
  Flet event handler ends the session with a crash screen. The messages are fixed strings
  worth recognising: `brotli: decoder failed`, `brotli: encoder concurrent access`,
  `brotli: encoder is unhealthy`, `brotli: invalid quality; range is 0 to 11` and
  `brotli: invalid lgwin; range is 10 to 24`.

- **httpx advertises `br`, and then *your* process does the decoding.** Adding this dependency
  puts `br` into httpx's `Accept-Encoding` (see [Install](#install)), which is worth having —
  but the frame is decompressed in Python, not in a platform networking stack. Verified
  against a stub transport returning `Content-Encoding: br`: 32 bytes on the wire, 4,000 bytes
  out of `response.content`, identical to the source. At brotli's read speed that is
  microseconds on the payload sizes an API returns, but it is CPU you did not previously
  spend.

- **Python 3.14 does not make this redundant the way it does for zstd.** 3.14 added
  `compression.zstd` to the standard library and no brotli module, so the stdlib compression
  set stays `zlib`, `gzip`, `bz2`, `lzma` and now `zstd`. brotli has to come from a wheel on
  every Python version Flet ships.

## Build notes (maintainers)

### Recipe shape

The recipe is `meta.yaml` and nothing else: a name, a version, a build number, no patches, no
`build.sh`, no `requirements`, no `script_env`. That is the fact worth recording, because it
sets the expectation for a bump — upstream vendors the whole of libbrotli under `c/` in its
own sdist and builds it with plain setuptools, so a bump that suddenly needs a patch or a host
requirement means upstream restructured, not that the toolchain drifted.

Two observations from the published wheels that are recorded nowhere else:

- **The 3.12 Android slices name the extension `_brotli.cpython-312.so`, without the platform
  triplet, while 3.13 and 3.14 use the full `_brotli.cpython-31X-<triplet>.so`.** Both carry
  the `.cpython-*` tag serious_python's `jniLibs` relocation keys on, so both work, but forge's
  foreign-arch drop (the `\.cpython-\d+-<triplet>\.so$` filter in `src/forge/build.py`) cannot
  tell the four 3.12 Android slices apart by filename. Each was checked by `e_machine` and is
  the right architecture, so it is harmless today — but it is the first thing to look at if a
  3.12 Android wheel ever imports on one ABI and not another.
- **The iOS extensions are `MH_DYLIB` already**, on all nine slices, so this recipe is not
  exposed to the `Unsupported mach-o filetype` breakage that hit CMake-built recipes published
  before forge's `MH_BUNDLE → MH_DYLIB` converter landed. setuptools produces a dylib on iOS
  on its own; nothing in the recipe arranges it.

### Upgrade hazards

- **The concurrency guard is a property of the current binding, not of libbrotli.** It lives
  in `python/_brotli.c`. The release before this one contains the word "concurrent" zero
  times, and what it had instead was undefined behaviour: the same eight-thread script against
  it killed five of eight runs with `SIGSEGV` at quality 11, and at quality 5 five completed
  runs raised nothing at all while quietly mangling the stream. A regression here turns a
  documented, catchable error back into an uncatchable native abort on device.
- **`params->mode` gaining a second reader** would falsify the "`MODE_TEXT` does nothing"
  claim in [Things to know](#things-to-know), which is a one-line grep of `c/enc/` against the
  source. Upstream could re-enable text context modelling at any release.
- **The dictionary size**, 122,784, is `data_size` in `c/common/dictionary.c`. It is quoted on
  this page and printed by the example app, and it has not changed in years — which is exactly
  why nobody would think to check it.

### Re-verification checklist

- **That `METADATA` still carries zero `Requires-Dist` lines.** [Install](#install) offers a
  two-line snippet as the whole job; an upstream dependency would make that false without
  failing anything.
- **That upstream still publishes no mobile wheels of its own.** Check with
  `pip download --only-binary :all:`, **PyPI listed first** and this index only as
  `--extra-index-url`, once per platform tag across the three Pythons; every one must come back
  with this index's wheel. The day upstream tags an Android, iOS or `py3-none-any` wheel, this
  recipe may stop being needed.
- **The concurrency guard**, by re-running eight threads against one shared `Compressor`.
- **The quality ladder, the throughput figures and the memory curve**, which are measurements
  rather than estimates. Their shapes — a time cliff between 9 and 10, quality 3 worse than 2,
  peak memory maximised at quality 9 — follow from the encoder's strategy switches and are what
  a bump could genuinely move. Re-measure rather than rescaling by eye, starting with the
  memory curve, since it is the one naming a specific quality as a hazard.
- **The linkage and the extension filename**, per slice: `DT_NEEDED` still four bionic and
  interpreter entries with no `libc++_shared`, 16 KB `PT_LOAD` alignment on all four Android
  ABIs, `MH_DYLIB` on all three iOS ones, and an ABI-tagged extension name — an untagged `.so`
  would be a silent `ModuleNotFoundError` on Android.
- **The sizes** in [App size](#app-size), re-measured from the resulting wheels and from a
  built APK rather than scaled from the old figures.

### Coverage gaps

`tests/test_brotli.py` is a single function asserting that `compress` shrinks a short string
and that `decompress` returns it exactly. It is the only device evidence behind this page, so
its narrowness is the thing to fix. In rough order of value: a `Compressor`/`Decompressor`
streaming round trip in chunks, since [Storage](#storage) recommends that shape and nothing
exercises it; a quality sweep asserting 11 is not larger than 1, which would catch a build that
silently lost the high-quality encoder; `MODE_TEXT` output equalling `MODE_GENERIC` output,
which pins that claim to the shipped binary rather than to a source grep; and the dictionary's
effect, asserting a short web-shaped string beats `zlib` — the one property distinguishing this
wheel from the stdlib, and the one a stripped or mis-linked build would lose. The concurrency
guard is deliberately off that list: eight threads on a shared object is a poor fit for a CI
test that must never flake.
