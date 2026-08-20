# brotli

[`brotli`](https://github.com/google/brotli) is Google's general-purpose compressor — the
`br` of `Content-Encoding: br`, specified in
[RFC 7932](https://datatracker.ietf.org/doc/html/rfc7932). The reason to add it to a phone
app rather than use `zlib`, which is already there, is that **it carries a 122,784-byte
dictionary of common web text compiled into the binary**. That dictionary is present in
every slice of this wheel, and it is what lets brotli compress payloads far too short for
deflate to find anything in: three URLs totalling 106 bytes come out at 43 bytes against
`zlib`'s 61 and `gzip`'s 73. Across the cheap part of its quality range it also wins on
larger payloads on *both* axes at once — 41% smaller than `zlib` level 9 and faster to
produce, on the HTML payload measured below.

It is not a universal upgrade, and this page says where it loses: `zlib` and `gzip`
decompress two to two-and-a-half times faster, `lzma` and `bz2` sometimes produce smaller
output, quality 11 costs hundreds of milliseconds, and — the one that can hurt you quietly —
**a brotli frame carries no checksum**, so a damaged frame can decode to the wrong bytes and
raise nothing. All of that is measured in [Things to know](#things-to-know).

**The name is spelled two ways and you will meet both.** The import is always `brotli`. The
distribution was `Brotli` up to and including 1.1.0 — whose sdist is `Brotli-1.1.0.tar.gz`
and whose metadata says `Name: Brotli` — and is lowercase `brotli` from 1.2.0, whose sdist
is `brotli-1.2.0.tar.gz` and whose metadata says `Name: brotli`. `pypi.org/project/Brotli/`
still resolves, pip normalises both spellings to the same project, and this index carries
the history: `Brotli-1.1.0-1-*.whl` alongside `brotli-1.1.0-4-*.whl` and the current
`brotli-1.2.0-1-*.whl`. Write it however you like; nothing downstream cares.

**Measured on device, 2026-08-20.** The [`bake-off`](examples/bake-off) example ran on an
arm64-v8a Android 14 emulator and an iPhone 16 simulator, both CPython 3.14.6, over the same
338,073-byte HTML payload. Every byte count is identical on the two platforms because they are
deterministic: `bz2` level 9 produces the smallest output at 9,761 bytes, brotli q11 next at
11,068, and brotli q5 is 41% smaller than `zlib` 9 (14,397 against 24,579). All eight codecs
round-tripped to the same SHA-256. What differs is time, and it is the reason to care about
quality: **q11 cost 1,783.8 ms on Android and 462.1 ms on iOS**, against 1.1 ms and 0.3 ms for
q1 — hundreds of frames, on whichever thread you run it.

**The corruption result is the one to read twice.** Flipping a single bit in the compressed
bytes, 120 times: brotli q5 raised an exception 71 times and **returned wrong data silently 49
times**, identically on both platforms. `gzip` raised all 120, because it carries a CRC32 and
brotli carries no integrity check at all. If you store brotli output anywhere it can rot, store
a checksum beside it.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "brotli",
]
```

Nothing else to configure, and nothing comes along with it: the `METADATA` in all nineteen
published wheels contains **zero** `Requires-Dist` lines and no `Requires-Python` either, so
no `flet-lib*` wheel and no transitive dependency follows it in, and the Python floor you
hit is Flet's.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Every wheel is seven files — one extension, `brotli.py`, and five
`dist-info` entries — with no data file of any kind, so the Flet 0.86 Android
`sitepackages.zip` class of failure has nothing to bite on. The Python layer is 57 lines
that import `_brotli` and wrap it; it never touches `__file__`, `importlib.resources`,
`pkgutil` or `open`, so running out of a zip is irrelevant to it. The extension carries a
CPython ABI tag on every slice, which is what serious_python's Android packaging keys on
when it relocates a module into `jniLibs`. Confirmed against a built APK of the
[example](examples/bake-off): brotli's entries in that APK's `sitepackages.zip` are a
2,012-byte `brotli.pyc`, a 13-byte `_brotli.soref` holding the single line
`lib_brotli.so`, and the `dist-info` — seven files there rather than the wheel's five,
because pip adds `INSTALLER` and `REQUESTED` on install. No data file of any kind, and no
`.so`: that has moved to `lib/<abi>/`.

**Adding this dependency also turns on `br` in Flet's own HTTP client.** Flet 0.86.5
requires `httpx>=0.28.1`, and httpx registers its brotli decoder only if the import
succeeds. Measured on httpx 0.28.1: with brotli installed,
`httpx.Client().headers["accept-encoding"]` is `gzip, deflate, br` and the decoder table is
`['br', 'deflate', 'gzip', 'identity']`; in an otherwise identical environment without it,
`gzip, deflate` and `['deflate', 'gzip', 'identity']`. So an app that talks to a
brotli-serving API gets smaller responses without a line of code — see
[Things to know](#things-to-know) for the caveat about who actually decompresses them.

Nineteen wheels at the same build number: Android arm64-v8a, armeabi-v7a and x86_64 plus
iOS device, arm64-simulator and x86_64-simulator on each of Python 3.12, 3.13 and 3.14, and
a legacy 32-bit `android_24_x86` slice on 3.12 only. That is the standard forge matrix, so
no [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed.

**A bare `brotli` really does resolve from this index for a mobile target.** Upstream
publishes 100 files for 1.2.0 on PyPI and not one is an Android wheel, an iOS wheel or a
`py3-none-any` wheel — only an sdist and CPython 2.7-through-3.14 binaries for macOS, Linux,
musl and Windows. Checked with `pip download --only-binary :all:` with **PyPI listed first**
and this index only as `--extra-index-url`, once per platform tag across the three Pythons:
all seven came back with this index's wheel.

Because those desktop wheels do exist for every CPython from 3.10 to 3.14, `brotli` belongs
in `[project] dependencies` and not in a `[tool.flet.<platform>]` table — the host resolve
`flet build` performs will find one, and `flet run` on your laptop gets the same API you
will ship.

## Storage

**There is no file API.** `gzip`, `bz2`, `lzma` and the sibling [`zstandard`](../zstandard)
recipe all give you an `open()` that returns a file object; `brotli` gives you four
callables — `compress`, `decompress`, `Compressor`, `Decompressor` — and no file object
anywhere. Writing a compressed file is yours to do:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "snapshot.br")
compressor = brotli.Compressor(quality=5)
with open(path, "wb") as handle:
    for chunk in chunks:
        handle.write(compressor.process(chunk))
    handle.write(compressor.finish())
```

Reading it back streams the same way: a `Decompressor` returns whatever each piece of
input yielded, so an oversized payload can be written out as it arrives instead of being
held whole, which is what `brotli.decompress()` — one call, one `bytes` — cannot do.

Where the file goes is the usual Flet split:
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for something the app owns and cannot rebuild,
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for something derived, and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch.

**Store a hash beside the file.** A brotli frame has no checksum, no length field and no
trailer — the format simply does not carry one, and the Python binding exposes nothing that
could check one. Measured on the log payload, 400 single-bit flips per run across three
independent seeds: a quality-5 frame gave 255–273 exceptions against **127–145
decompressions that returned the wrong bytes and raised nothing**, and a quality-11 frame
328–334 against 66–72. Roughly a third of the damage gets through at quality 5 and a sixth
at quality 11 — never none of it. The same sweeps against `gzip`, `zlib`, `lzma` and `bz2`
frames of that payload returned wrong bytes **zero** times. Those four are not all-seeing:
52 of the 80 bits in `gzip`'s 10-byte header sit in fields it ignores, so a flip there is
accepted without complaint. But what comes back is still the original bytes, and that is the
distinction that matters. A phone's filesystem is exactly where a half-written file happens,
so a `hashlib.sha256` digest written alongside is not defensiveness, it is the equivalent of
what the other four codecs give you for free.

brotli itself reads and writes nothing, opens no path and creates no cache or config
directory, so there is no environment variable to point anywhere before importing it. The
extension's undefined-symbol list is the evidence: eleven bionic entries, not one of them a
file or directory call.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`bake-off`](examples/bake-off) — brotli at four quality levels against `zlib`, `gzip`, `lzma`
  and `bz2` on the same bytes, plus the short-input case and a bit-flip sweep.

## Threading

**The extension releases the GIL, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys
real parallelism.** `PyEval_SaveThread` and `PyEval_RestoreThread` are undefined symbols on
all nineteen slices — two of the thirty-five that every Android slice imports — which is the
tell that the C code hands the interpreter back while it works. Measured on desktop against
controls that make a false answer visible: a pure-Python
counting thread, which can only advance while it holds the GIL, kept **94.1%** of its idle
rate while another thread ran a quality-11 compression and **90.8%** while it decompressed,
against **48.8%** for a pure-Python control competing with pure-Python work. Wall clock
agrees: four concurrent quality-11 compressions took 492 ms where four serial ones took
1,460 ms, a 2.97× speedup on a 10-core machine.

**One `Compressor` object must not be used from two threads at once — but 1.2.0 tells you so
instead of crashing.** The binding sets a `processing` flag around each call to `process`,
`flush` and `finish`, and tests it while holding the GIL, so an overlapping caller is
rejected with `brotli.error: brotli: encoder concurrent access` rather than being allowed
into the encoder. Measured with eight threads pushing 200 blocks each — 1,600 pushes —
through one shared `Compressor`, eight runs: every run completed, and 600 to 1,200 of the
pushes raised that error. The rejection is all-or-nothing per thread, always a whole
multiple of 200: three to six of the eight threads lost the race and then went on losing it
for every block they had, while the rest got all of theirs through. Decompressing the result
and counting the blocks confirms the arithmetic exactly — the survivors are precisely the
pushes that did not raise — so **the rejected threads' data is simply gone**; the guard
protects the process, not your bytes. The same eight threads with a `threading.Lock` held
around `process()` produced zero exceptions and all 1,600 blocks, five runs out of five.
`Decompressor` carries the same guard and reports it as
`brotli: decoder concurrent access`.

That guard is new in this version — 1.1.0's `python/_brotli.c` contains the word
"concurrent" zero times — and what it replaced is undefined behaviour, not a friendlier
error. The same script against 1.1.0 on a desktop: at quality 11, five of eight runs died
with `SIGSEGV` and three completed; at quality 5 all eight completed, and five of those
raised **nothing at all** while quietly mangling the stream. Other runs raised
`BrotliEncoderCompressStream failed while processing the stream`, produced output that
`brotli.decompress` then refused outright, or hung past a two-minute wall. Which of those
you get is timing. If you have code that was quietly getting away with a shared compressor
on 1.1.0, it was not getting away with it.

The module-level `brotli.compress()` and `brotli.decompress()` are safe from any number of
threads, because each call builds its own state. Reach for a `Compressor` object only when
you need streaming, and then give each thread its own or serialise it.

This matters in Flet specifically because `run_thread` submits to a shared thread pool, so
two taps in quick succession really do overlap — and it never retrieves the worker's future,
so the `brotli.error` above would surface nowhere at all. Wrap worker bodies in
`try`/`except`, and end them with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach background threads.

## Android notes

- **Three ABIs mean three copies of a 733–949 KB extension.** The `.so` is 98.7–99.0% of
  the unpacked wheel on every slice, so an APK covering all three carries 2,551,488 bytes of
  brotli unless you split by ABI. That is not arithmetic on wheel sizes — an APK built from
  the [example](examples/bake-off) contains exactly `lib/arm64-v8a/lib_brotli.so` at
  868,496 B, `lib/armeabi-v7a/lib_brotli.so` at 733,552 B and `lib/x86_64/lib_brotli.so` at
  949,440 B. The `lib_brotli.so` name is serious_python's, derived from the `_brotli` module
  name, and collides with nothing else Flet ships.
- **The extension links nothing but the interpreter and bionic.** `DT_NEEDED` is exactly
  `libm.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` on all ten Android slices,
  with no `SONAME`, no `RPATH`, no `RUNPATH` and no `libc++_shared`, so none of the usual
  Android C++ staging applies. Each imports exactly thirty-five undefined symbols:
  twenty-four from CPython's API and eleven from bionic — `malloc`, `free`, `memcpy`,
  `memmove`, `memset`, `snprintf`, `exit`, `__cxa_atexit`, `__cxa_finalize`,
  `__register_atfork`, and `log2` from `libm.so`. The count is the same on all ten, but the
  set is not quite: 3.12 links the private `_PyArg_ParseTuple_SizeT` and
  `_PyArg_ParseTupleAndKeywords_SizeT` where 3.13 and 3.14 link the public
  `PyArg_ParseTuple` and `PyArg_ParseTupleAndKeywords` — a CPython-side change, not a recipe
  one. All `PT_LOAD`
  segments carry 16 KB alignment, which Android 15 requires. arm64-v8a and x86_64 are
  `ELF64`; armeabi-v7a and the legacy `x86` slice are genuine `ELF32`/`ARM` and
  `ELF32`/`i386` builds rather than stubs.
- **`bz2` and `lzma` are there to compare against.** Flet's Android runtime ships
  `lib_bz2.so`, `lib_lzma.so` and `libzlib.so` in serious_python_android 4.5.1's `jniLibs`,
  so a like-for-like comparison on device does not need any extra dependency.

## iOS notes

- **The same source weighs 7–9% more here, and that is all that differs.** 946,128 bytes of
  Mach-O on the 3.14 device slice against 868,496 of ELF on Android arm64 — 8.9% on 3.14 and
  7.3% on 3.12 and 3.13. Each extension is `MH_DYLIB`, checked on all nine iOS slices, which
  matters because Flet 0.86 turns every site-packages `.so` into a framework binary that
  SwiftPM *links*, and `ld` refuses an `MH_BUNDLE`. `otool -L` names exactly two libraries on every slice:
  `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`.
- **`_bz2` and `_lzma` ship as xcframeworks** in serious_python_darwin 4.5.1's iOS
  distribution, so the stdlib comparison works on iOS as well.
- **Shipping a compressor is not shipping a cipher.** brotli contains no cryptography, so it
  does not by itself put your app into App Store Connect's "uses non-exempt encryption"
  category — a package that ships ciphers does, and [`pycryptodome`](../pycryptodome) is the
  one on this index most likely to be sitting beside it. Whatever else is in your app still
  decides that question, and `ITSAppUsesNonExemptEncryption` in `Info.plist` is where the
  answer is recorded.

## Things to know

- **Quality is not a linear dial, and the cliff is between 9 and 10.** On 339,362 bytes of
  log lines, measured on an Apple M4 desktop under CPython 3.14.5 (best of three):

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

  Two things to take from that. **Quality 3 is worse than quality 2** — 44,666 bytes against
  40,301, and slower with it, 1.0 ms against 0.7 — so the ladder is not monotonic and a level
  picked by intuition can cost you on both axes at once. And **10 costs 27× what 9 costs**
  for 26% fewer bytes, which is the line between "a user can wait for this" and "this belongs
  in a background job that runs once"; `c/enc/quality.h` names the reason —
  `ZOPFLIFICATION_QUALITY` and `MIN_QUALITY_FOR_HQ_BLOCK_SPLITTING` are both 10. Quality 5 is
  the value worth defaulting to, and the same header says why:
  `MIN_QUALITY_FOR_CONTEXT_MODELING` and `MIN_QUALITY_FOR_EXTENSIVE_REFERENCE_SEARCH` are
  both 5. Against `zlib` level 9 on the same bytes it produced 38.7% smaller output in 0.42×
  the time here, and 41.4% smaller in 0.49× the time on the HTML payload.
- **`MODE_TEXT` does nothing.** `params->mode` is read at exactly one place in libbrotli
  1.2.0's encoder — `c/enc/encode.c:604` — and that line tests only `BROTLI_MODE_FONT`.
  `MODE_TEXT` therefore falls into the same branch as `MODE_GENERIC` and produces
  byte-identical output; verified on three payloads at two qualities each, zero difference
  every time. `MODE_FONT` does change the output (+40 bytes at quality 5, −66 at quality 11
  on the log payload), and only at quality 4 and above, since it sets distance parameters
  the encoder ignores below `MIN_QUALITY_FOR_NONZERO_DISTANCE_PARAMS` (`c/enc/quality.h`,
  value 4). Use it for WOFF 2.0 and ignore the other two.
- **Deflate still decompresses faster; `lzma` and `bz2` do not.** Decompression throughput
  on that same 339,362-byte payload, best of five runs of fifty iterations:
  `gzip` 3,002 MB/s, `zlib` 2,875, brotli quality 9 1,365, quality 5 1,333, quality 11
  1,136, quality 1 760, `lzma` preset 6 229, `bz2` level 9 131. The comparison that matters
  is at matched output size: brotli quality 11 produced 18,468 bytes and read back in
  0.299 ms, while `lzma` preset 6 produced 18,808 bytes — essentially the same size — and
  read back in 1.483 ms, **5.0× slower**. So brotli is the choice against `lzma`, and
  `zlib` remains the choice when read latency is all that matters.
- **Compression memory peaks at quality 9, not at quality 11.** Peak RSS above baseline
  while compressing that payload at the default `lgwin=22`, each figure from a fresh process
  and cross-checked against the kernel's own accounting via `/usr/bin/time -l`: 0.6 MiB at
  quality 0, 2.4 at 5, 3.7 at 6, 9.3 at 7, 17.2 at 8, **33.4 at 9**, 12.4 at 10 and 14.3 at
  11. The curve is not monotonic and its maximum is quality 9 — more than twice what quality
  11 costs, and fourteen times what quality 5 costs — because 9 is the last rung using the
  quality-sized hash table, and 10 switches to the window-sized binary-tree hasher. The rung
  that looks like the last cheap one on the clock is the most expensive one on memory, which
  is worth knowing before defaulting to it on a phone. `lgwin` moves the figure too, and
  moves it hardest exactly where quality hurts: quality 9 drops from 33.4 MiB to 2.1 at
  `lgwin=16` and 2.0 at `lgwin=10`. Narrowing the window costs ratio on data with long-range
  repetition (25,364 bytes at `lgwin=10` against 18,468 at 22 on the log payload) and buys
  nothing beyond 22 on a payload this size, since 24 gave the identical 18,468.
  Decompression is cheap whatever wrote the frame: measured in a fresh process, 1.0 MiB
  above baseline from an `lgwin=22` frame and 0.7 MiB from an `lgwin=10` one. Two concurrent
  compressions ask the OS for twice the figure at once, and an Android low-memory kill is
  not something `try`/`except` can catch.
- **A damaged frame sometimes lies instead of raising.** Covered under
  [Storage](#storage) with the numbers; repeated here because it is the single most
  surprising thing about the format for anyone arriving from `gzip`. `brotli.decompress()`
  raises `brotli.error: brotli: decoder failed` on a truncated frame and on garbage, so the
  common cases are caught — it is the flipped bit in the middle that gets through.
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
  1 byte against `zlib`'s 8, `gzip`'s 20 and `lzma`'s 32. The JSON record is the honest
  counter-example: 78 against 79 is not a reason to change anything, because the dictionary
  holds web text and a record of opaque identifiers is not web text.
- **`brotli.__version__` is the C library's version, read at import.** The binding builds it
  from `BrotliDecoderVersion()` rather than from package metadata, so printing it on device
  tells you which libbrotli is actually compiled into the wheel you resolved — a check no
  `importlib.metadata` lookup can make.
- **`brotli.error` derives straight from `Exception`, not from `OSError` or `ValueError`.**
  `except OSError:` around a decompression catches nothing. The messages are fixed strings
  worth recognising: `brotli: decoder failed`, `brotli: encoder concurrent access`,
  `brotli: encoder is unhealthy`, `brotli: invalid quality; range is 0 to 11`,
  `brotli: invalid lgwin; range is 10 to 24`. And catch it — an unhandled exception in a
  Flet event handler ends the session with a crash screen.
- **httpx advertises `br` but does not always do the decoding.** Adding this dependency puts
  `br` into httpx's `Accept-Encoding` (measured in [Install](#install)), which is worth
  having — and the decoding then happens in *your* Python process, not in a platform
  networking stack. Verified against httpx 0.28.1 with a stub transport returning
  `Content-Encoding: br`: 32 bytes on the wire, 4,000 bytes out of `response.content`,
  identical to the source. At 1,333 MB/s that is microseconds on the payload sizes an API
  returns, but it is CPU you did not previously spend.
- **Size: 377–446 KB to download per slice, 743–993 KB unpacked, and 98.7–99.0% of that is
  the extension.** The Python half is one 1,970-byte module, byte-identical across all nineteen
  wheels and byte-identical to the sdist's own `python/brotli.py`. Roughly a third of the
  binary is data rather than code: on the Android arm64 3.14 slice `.rodata` is 454,936
  bytes against 386,752 of `.text`, and the built-in dictionary accounts for 122,784 of
  that. Every slice is stripped — no `.symtab`, no `.debug_*`.
- **Python 3.14 does not make this redundant the way it does for zstd.** 3.14 added
  `compression.zstd` to the standard library and no brotli module: the stdlib compression
  set is `zlib`, `gzip`, `bz2`, `lzma` and, from 3.14, `zstd`. brotli has to come from a
  wheel on every Python version Flet ships.

## Build notes (maintainers)

The recipe is `meta.yaml` and nothing else: a name, a version, a build number, no patches,
no `build.sh`, no `requirements`, no `script_env`. That is the fact worth recording, because
it sets the expectation for a bump — upstream vendors the whole of libbrotli under `c/` in
its own sdist and builds it with plain setuptools, so a bump that suddenly needs a patch or
a host requirement means upstream restructured, not that the toolchain drifted.

Two observations from the published wheels that are not recorded anywhere else:

- **The 3.12 Android slices name the extension `_brotli.cpython-312.so`, without the
  platform triplet, while 3.13 and 3.14 use the full
  `_brotli.cpython-31X-<triplet>.so`.** Both spellings carry the `.cpython-*` tag
  serious_python's `jniLibs` relocation keys on, so both work, but the untriplet-ed form
  means forge's foreign-arch drop (the `\.cpython-\d+-<triplet>\.so$` filter in
  `src/forge/build.py`) cannot distinguish the four 3.12 Android slices from each other by
  filename. That is currently harmless — the `e_machine` of each was checked and every slice
  is the right architecture — but it is the failure mode to look for first if a 3.12 Android
  wheel ever imports on one ABI and not another.
- **The iOS extensions are `MH_DYLIB` already**, on all nine slices, so this recipe is not
  exposed to the `Unsupported mach-o filetype` breakage that affects CMake-built recipes
  published before forge's `MH_BUNDLE → MH_DYLIB` converter landed. setuptools produces a
  dylib on iOS on its own; nothing in the recipe arranges it.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **That `METADATA` still has zero `Requires-Dist` lines.** [Install](#install) tells people
  nothing comes along with this package; upstream declaring a dependency would make that
  false without failing anything.
- **The concurrency guard.** The `brotli: encoder concurrent access` behaviour in
  [Threading](#threading) is a 1.2.0 property — 1.1.0 died with `SIGSEGV`, mangled the
  stream silently or hung instead, per the runs recorded there — and it lives in
  `python/_brotli.c`, not in libbrotli. Re-run eight threads against one
  shared `Compressor` after a bump; a regression here turns a documented, catchable error
  back into an uncatchable native abort on device.
- **Whether `params->mode` gained a second reader.** The "`MODE_TEXT` does nothing" claim in
  [Things to know](#things-to-know) is a one-line grep of `c/enc/` against the *new* source,
  and upstream could re-enable text context modelling at any release.
- **The quality ladder, the throughput table and the memory curve**, which are measurements
  on a specific desktop, not estimates. Their shapes (a time cliff between 9 and 10, quality
  3 worse than 2, peak RSS maximised at quality 9) follow from the encoder's strategy
  switches and are what a bump could genuinely move; re-measure rather than rescaling by
  eye. The memory curve matters most, since it is the one that names a specific quality as a
  hazard.
- **The dictionary size.** 122,784 is `data_size` in `c/common/dictionary.c`, and it is
  quoted on this page and printed by the example app. 1.1.0 declares the same value, which
  is exactly why nobody would think to check it again.
- **The linkage and the extension filename**, per slice: `DT_NEEDED` still four bionic and
  interpreter entries with no `libc++_shared`, 16 KB `PT_LOAD` alignment on all four Android
  ABIs, `MH_DYLIB` on all three iOS ones, and an ABI-tagged extension name — an untagged
  `.so` would be a silent `ModuleNotFoundError` on Android, since serious_python keys its
  relocation on that suffix.
- **That upstream still publishes no mobile wheels of its own.** 1.2.0 ships 100 files on
  PyPI with no Android, iOS or `py3-none-any` tag among them, which is what makes a bare
  `brotli` resolve from this index; the day that changes, this recipe may stop being needed.

`tests/test_brotli.py` is a single function asserting that `compress` shrinks a 51-byte
string and that `decompress` returns it exactly. It is the only device evidence behind this
page, which makes its narrowness the thing to fix. In rough order of value, the additions
that would protect what is claimed above: a `Compressor`/`Decompressor` streaming round trip
in chunks, since [Storage](#storage) recommends that shape and nothing exercises it; a
quality sweep asserting that 11 is not larger than 1, which would catch a build that
silently lost the high-quality encoder; `MODE_TEXT` output equalling `MODE_GENERIC` output,
which pins the claim above to the shipped binary rather than to a source grep; and the
dictionary's effect, asserting that a short web-shaped string compresses to fewer bytes than
`zlib` manages — the one property that distinguishes this wheel from the stdlib and the one
a stripped or mis-linked build would lose. The concurrency guard is deliberately not on that
list: eight threads on a shared object is a poor fit for a CI test that must never flake.
