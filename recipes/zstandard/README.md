# zstandard

[`zstandard`](https://python-zstandard.readthedocs.io/en/latest/) is the Python binding to
Facebook's [Zstandard](https://facebook.github.io/zstd/) compressor, with libzstd compiled
straight into the extension. What earns it a place on a phone is the shape of its cost curve
rather than its ratio: **a frame reads back at the same speed no matter how hard the
compressor worked to write it**, so you pay once, on a background thread, for a cache the app
then reads for free. The other mobile-shaped feature is its dictionary API, which is the
difference between zstd being pointless and being 4× on collections of small records.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "zstandard",
]
```

**On Python 3.14, check whether you need this wheel at all.** 3.14 added zstd to the standard
library and Flet's 3.14 mobile runtime ships it, so `from compression import zstd` may already
cover a compress-and-store app; Flet's 3.13 and 3.12 runtimes carry no zstd at all, and an app
supporting those still needs the wheel. What the wheel adds on 3.14 is the streaming and batch
surface — `stream_writer`, `stream_reader`, `chunker`, `read_to_iter`, `copy_stream`,
[`multi_compress_to_buffer`](https://python-zstandard.readthedocs.io/en/latest/compressor.html#zstandard.ZstdCompressor.multi_compress_to_buffer)
and the buffer types — plus
[`ZstdCompressionParameters`](https://python-zstandard.readthedocs.io/en/latest/compression_parameters.html#zstandard.ZstdCompressionParameters),
the frame-header helpers
[`frame_content_size`](https://python-zstandard.readthedocs.io/en/latest/misc_apis.html#zstandard.frame_content_size)
and
[`get_frame_parameters`](https://python-zstandard.readthedocs.io/en/latest/misc_apis.html#zstandard.get_frame_parameters),
and multi-threaded compression, which the stdlib module in that runtime does not have.

zstandard's own floor is Python 3.9, so the `requires-python` an app ends up with is set by
Flet rather than by this package.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`level-lab`](examples/level-lab) — sweeps the zstd level range on device against `zlib`,
  `bz2` and `lzma`, and shows what a trained dictionary is worth on many small records.

## Usage in a Flet app

```python
import zstandard

frame = zstandard.ZstdCompressor(level=3, write_checksum=True).compress(payload)
restored = zstandard.ZstdDecompressor().decompress(frame)
saved = ft.Text(f"{len(payload) / len(frame):.1f}× smaller")
```

Three things in those lines are not obvious. `level=3` is a starting point and not a floor: a
higher level is not reliably a smaller file, and the reversals are deterministic rather than
noise. `write_checksum=True` is *not* the default, and without it a corrupted frame
decompresses to plausible-looking wrong bytes with no exception at all. And neither object may
be shared across threads — one
[`ZstdCompressor`](https://python-zstandard.readthedocs.io/en/latest/compressor.html#zstandard.ZstdCompressor)
used from two threads at once kills the process, and one
[`ZstdDecompressor`](https://python-zstandard.readthedocs.io/en/latest/decompressor.html#zstandard.ZstdDecompressor)
quietly returns the wrong bytes.

### Storage

A compressed file the app owns belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which is app-private, never auto-deleted and included in backups; a derived one that can be
rebuilt belongs in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache),
and scratch in
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp).
The file API is
[`zstandard.open()`](https://python-zstandard.readthedocs.io/en/latest/one_shot_api.html#zstandard.open),
which mirrors `builtins.open` and closes what it opened:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "snapshot.zst")
with zstandard.open(path, "wb") as handle:
    handle.write(payload)
with zstandard.open(path, "rb") as handle:
    payload = handle.read()
```

Three habits for a phone's filesystem specifically:

- **Ask for a checksum.** Four bytes per frame is nothing against a half-written file after
  the OS killed the app, and without one a corrupt frame can decompress to the wrong bytes in
  silence: `zstandard.open(path, "wb", cctx=zstandard.ZstdCompressor(write_checksum=True))`.
- **Pass `size=` when you stream.** `zstandard.open(path, "wb")` and
  [`stream_writer(handle)`](https://python-zstandard.readthedocs.io/en/latest/compressor.html#zstandard.ZstdCompressor.stream_writer)
  write a frame that declares no content size, which both blocks a later `decompress()` and
  makes a high level reserve an enormous compression context. Calling `stream_writer` directly
  with `size=len(payload)` fixes the two together.
- **Read big frames in chunks.**
  [`stream_reader(handle)`](https://python-zstandard.readthedocs.io/en/latest/decompressor.html#zstandard.ZstdDecompressor.stream_reader)`.read(65536)`
  in a loop never holds more than a chunk, where `decompress()` allocates the whole output up
  front — even when you asked it not to (see [Things to know](#things-to-know)).

There is no atomic-write machinery in the library, so if a truncated file would hurt, write
beside the target and `os.replace` it yourself.

### Threading

**The C extension releases the GIL, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys real
parallelism** — compression, decompression and dictionary training all yield. Measured on
desktop against controls: a pure-Python counting thread, which can only advance while it holds
the GIL, kept 99.4–100.4% of its idle rate while the main thread worked, against **50.2%** for
a pure-Python control that does not release it; and four threads compressing a 3.6 MB payload
at level 10 gave a **2.84–3.02×** speedup over one thread, where the same harness gave
`hashlib.sha256` **3.40–3.79×**. ([`orjson`](../orjson), by contrast, holds the GIL for its
whole call and gains nothing from threads.)

**But one `ZstdCompressor` or `ZstdDecompressor` used from two threads at once breaks, and the
two break differently — the compressor loudly, the decompressor silently.** Measured on
desktop, ten fresh processes per cell, each worker compressing *its own distinct payload* and
checking the round trip against its own bytes:

| what the threads share | 2 threads | 4 threads | 8 threads |
|---|---|---|---|
| one `ZstdCompressor` | process killed 10/10 | killed 8/10, `ZstdError` in the rest | killed 8/10, `ZstdError` in the rest |
| one `ZstdDecompressor` | **wrong bytes, no exception, exit 0** in 2/10 | wrong bytes in 8/10 | wrong bytes in 9/10, killed 1/10 |
| a `threading.Lock` around the whole call | 0 errors, 0 wrong | 0 errors, 0 wrong | 0 errors, 0 wrong |
| a fresh `ZstdCompressor` per thread | 0 errors, 0 wrong | 0 errors, 0 wrong | 0 errors, 0 wrong |
| `zstandard.compress()` / `.decompress()` | 0 errors, 0 wrong | 0 errors, 0 wrong | 0 errors, 0 wrong |

The compressor's failure is an uncatchable native signal — SIGSEGV or SIGBUS, no traceback,
nothing in the log. **The decompressor's is worse: it usually returns plausible-looking wrong
bytes**, and only a minority of runs raise a *catchable* `ZstdError` (`Data corruption
detected`, `Unknown frame descriptor`, `Src size is incorrect`). Do not read "no crash" as
"safe", and do not let a `try/except ZstdError` convince you it is handled.

That is exactly the shape of `page.run_thread`, whose workers share a pool and genuinely
overlap when the user taps twice, so **build the compressor and the decompressor inside the
worker**, or guard a shared one with a `threading.Lock` taken around the entire call. The
module-level
[`zstandard.compress(data, level)`](https://python-zstandard.readthedocs.io/en/latest/one_shot_api.html#zstandard.compress)
and `zstandard.decompress(data)` are safe because they build a context per call, and pay for
it — prefer a per-thread compressor in a loop.

The wheel is built **with** libzstd's own worker pool, so `threads=` works rather than
raising. Where it pays is `multi_compress_to_buffer`, which compresses independent records in
parallel with byte-identical output:

| 20,000 records, 2.45 MB | `threads=1` | `threads=-1` |
| --- | --- | --- |
| level 10 | 62.7 ms | **12.6 ms** |
| level 19 | 168.1 ms | 30.6 ms |

On a *single* large input it bought almost nothing on the payloads tried — 341 ms against
316 ms at level 15 on 20 MB, and level 19 was slower with four threads than with none — so
measure before reaching for it there.

The usual Flet rules still apply: a `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), and its body must be
wrapped in `try/except`, because `run_thread` discards whatever it raises — a `ZstdError` in a
worker looks like a screen that stopped updating, not like an error.

### Choosing a level

**The read side is flat, so choose a level for what it costs to write.** On the
[`level-lab`](examples/level-lab) example's 879,176-byte payload, reading a frame back took
0.20–0.34 ms at *every* level from -5 to 19 — 45 timings, nine levels × five sweeps — where
`bz2` at 9 took 6.4–7.1 ms and `lzma` at preset 1 took 3.1–3.2 ms for output of comparable
size. Compression is the side the dial moves, in time and in memory both. These are desktop
numbers; the shape is what transfers, not the milliseconds.

- **1–3 for anything written during a user interaction.** Cheap, and frequently *smaller* than
  level 6 on the same bytes.
- **Around 10 for a cache written on a background thread**, where a few tens of milliseconds
  do not show.
- **15 and up only after measuring both the time and the memory** — level 19 costs roughly a
  quarter of a second per call on that payload — and never through `stream_writer` without
  `size=`, the one combination that can get the app killed.
- **A trained dictionary before a higher level, when the records are small.** On 2,000 JSON
  records averaging 214 bytes, a dictionary at level 1 beats every dictionary-less level on
  the dial.

Output is deterministic for a given input, so measuring three candidate levels on your own
payload settles the question once. That is what the example does from a slider.

### App size

Roughly 0.6–0.8 MB compressed and 1.4–2.1 MB unpacked per slice, measured on the Python 3.14
wheels (3.12 is within 600 bytes of 3.14 on Android arm64). The two compiled extensions are
87–91% of that, and iOS carries about 11% more native code than Android arm64 for the same
version. Rather more than half the payload is the CFFI backend, which ships in every slice and
can never load (see [Things to know](#things-to-know)) — dead weight that cannot be dropped
from the wheel. [`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup)
has nothing meaningful to take out either: it drops `__init__.pyi` and `py.typed`, about
14 KB, which is harmless because nothing reads either at runtime.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI. These figures describe the package payload, not the exact
amount added to the final APK or IPA; packaging and compression determine that.

### Other considerations

A desktop `flet run` uses PyPI's wheel — the same upstream source at the same version, but
built by upstream rather than here, so confirm anything depending on the compiled libzstd
version or the selected backend against a device. The example prints both in its header for
exactly that reason.

**Every absolute number on this page was measured on desktop**; the ratios are the
transferable part. Re-measure on a device before designing around one — a phone will not
reproduce a laptop's milliseconds, and the memory ceiling that matters is the one the OS
enforces on your app.

Nothing in the package reads its own source or a data file — the only `builtins.open` in the
Python layer is inside `zstandard.open()`, opening the path you passed it — so Flet's default
compile-to-`.pyc` and Android's zipped site-packages are both safe. What is not safe is
reading a native module's location: Flet relocates tagged extensions out of site-packages on
**both** platforms, so `zstandard.backend_c.__file__` is not a path inside your app. Code of
your own that locates anything relative to a native module's `__file__` breaks here.

## Things to know

- **A higher level is not a smaller file. Ratio is not monotonic, and it is deterministic
  about it.** On the [`level-lab`](examples/level-lab) payload (879,176 bytes, half API JSON
  and half log lines): level 2 → 83,949 bytes beats level 3 → 87,141 *and* level 6 → 93,557;
  level 10 → 66,512 beats level 15 → 68,612. On a second dataset of 3.85 MB of log lines the
  reversals land elsewhere — level 2 → 331,223 against level 3 → 368,026, an 11% swing the
  wrong way — and three runs of each level gave byte-identical output, so this is the
  algorithm, not noise: `ZstdCompressionParameters.from_level()` shows levels 1 and 2 using
  `strategy 1` with `min_match` 7 and 6, where level 3 switches to `strategy 2` and 5.
  **Measure on your own payload.**
- **`max_output_size` is silently ignored when the frame declares its content size** — which
  is the default for `compress()`. `ZstdDecompressor().decompress(bomb, max_output_size=1 << 20)`
  returned 67,108,864 bytes from a 2,067-byte frame: a 32,467× expansion, with the limit set.
  The C source consults `maxOutputSize` only in the `ZSTD_CONTENTSIZE_UNKNOWN` branch and
  otherwise allocates the declared size outright. For untrusted input read the header first
  with `zstandard.frame_content_size(frame)`, which allocates nothing and returns `-1` when no
  size is declared, or read through `stream_reader` in bounded chunks and stop — verified to
  halt after 1,114,112 bytes of that 67 MB bomb read 65,536 bytes at a time. On a frame with
  no declared size the limit does work, raising `ZstdError: decompression error: did not
  decompress full frame`.
- **A streamed frame cannot be read back with `decompress()`.** `stream_writer` and
  `zstandard.open(path, "wb")` write no content size, so `frame_content_size` on the result is
  `-1` and `ZstdDecompressor().decompress(frame)` raises `ZstdError: could not determine
  content size in frame header` — a mismatch that shows up only at runtime, on device. Three
  fixes, all verified: pass `size=len(data)` to `stream_writer`; pass a `max_output_size=` at
  least as large as the real output (too small gives `did not decompress full frame` instead);
  or read it back with `stream_reader`, which never needs the header size.
- **Forgetting to close a `stream_writer` loses the file, and how it loses it depends on the
  size.** `w = cctx.stream_writer(sink, closefd=False); w.write(payload)` with no `close()`
  buffers roughly 130 KB of *compressed* output, and only what overflows that buffer reaches
  the sink. At level 3:

  | payload written | bytes that reached the sink |
  | --- | --- |
  | 100,000 B | 0 — the file is **empty** |
  | 1,000,000 B | 136 |
  | 3,853,317 B | 400 |

  That last is a genuinely truncated frame, not an inert one. `decompress()` refuses either
  way (`error determining content size from frame header` for empty or garbage, `could not
  determine content size in frame header` for a truncated frame, neither pointing near the
  cause) but `stream_reader` happily decodes a *prefix* out of the remnant — 3,670,016 of
  those 3,853,317 bytes — so a cache file written this way reads back short and silent. Always
  use `with cctx.stream_writer(handle) as w:`, and pass `closefd=False` when the sink is a
  `BytesIO` you still want to read.
- **Frame corruption is silent unless you asked for a checksum, and you did not.**
  `get_frame_parameters(cctx.compress(data)).has_checksum` is `False` by default. Flipping a
  single bit at each of 400 positions through a 342,082-byte frame: **141 of them decompressed
  to the wrong bytes with no exception at all**, and 259 raised. With
  `ZstdCompressor(write_checksum=True)` — four bytes longer — all 400 raised, and those same
  141 came back as `ZstdError: decompression error: Restored data doesn't match checksum`.
- **`ZstdError` inherits straight from `Exception`**, not `OSError`, not `zlib.error`, not
  anything the stdlib codecs raise, so an existing `except (zlib.error, lzma.LZMAError)` block
  will not catch it. It is also not what argument mistakes raise: `ZstdCompressor(level=23)`
  gives `ValueError: level must be less than 23` and `compress("a str")` gives `TypeError: a
  bytes-like object is required, not 'str'`. In a Flet event handler catch broad `Exception`
  around whatever parses user input, because an unhandled raise there makes Flet send
  `SESSION_CRASHED`.
- **A trained dictionary is what makes zstd worth using on many small records — and it needs a
  real corpus.** 2,000 JSON records averaging 214 bytes, 428,694 bytes in total, dictionary
  trained on a disjoint 2,000, all at level 1:

  | how the records are compressed | bytes | ratio |
  | --- | --- | --- |
  | a frame per record, no dictionary | 342,030 | 1.25 |
  | a frame per record, 16,384-byte dictionary | 101,620 | 4.22 |
  | all 2,000 in a single frame | 41,680 | 10.29 |

  That order holds at every level on the dial, so reach for
  [`train_dictionary`](https://python-zstandard.readthedocs.io/en/latest/dictionaries.html#zstandard.train_dictionary)
  when records must stay independently addressable and batch into one frame when they need
  not. Training that corpus costs about 11 ms on desktop, but `train_dictionary(16384,
  samples[:3])` and `train_dictionary(16384, [])` both raise `ZstdError: cannot train dict:
  Src size is incorrect`, a message that does not say what is wrong — train on hundreds to
  thousands of representative records and catch `ZstdError` around the call. The size you pass
  is a ceiling, not a promise: on that corpus asking for 16,384 and 112,640 bytes returned
  exactly those, while asking for 1,048,576 returned 218,891, so read the real size back with
  `len(d.as_bytes())`.
- **Dictionaries are safe to get wrong, and they persist.** The dictionary id travels in the
  frame header, so decompressing with a differently-trained dictionary — or with none — raises
  `ZstdError: decompression error: Dictionary mismatch` rather than returning garbage.
  [`ZstdCompressionDict(d.as_bytes())`](https://python-zstandard.readthedocs.io/en/latest/dictionaries.html#zstandard.ZstdCompressionDict)
  reproduces byte-identical output to the original object and decompresses frames made with
  it, so the blob can be stored beside the data and reloaded.
- **High levels are a memory decision, not just a speed one, and streaming without `size=` is
  the worst case.** Peak RSS in a fresh desktop process, 3.85 MB input, 30.3 MB baseline:
  one-shot level 3 → no measurable extra, level 10 → 46.4 MB, level 15 → 90.2 MB, level 19 →
  75.1 MB, level 22 → 91.0 MB; `stream_writer` **without** `size=` at level 19 → 111.3 MB and
  at level 22 → **565.6 MB**, which `size=len(data)` cuts back to 92.2 MB. The library will
  tell you before you try: `ZstdCompressionParameters.from_level(22)
  .estimated_compression_context_size()` is 672,399,510 bytes with an unknown source size
  against 1,303,576 at level 3. Decompression is cheap regardless —
  `estimate_decompression_context_size()` is 95,968 bytes at every level, and a level-22 frame
  decodes with a default decompressor.
- **On Python 3.14, some of this is already in the standard library.** Flet's 3.14 mobile
  runtime ships `compression.zstd` with the same libzstd 1.5.7 as this wheel on both platforms
  and frames interoperate in both directions; its 3.13 and 3.12 runtimes ship no zstd at all.
  The stdlib module has no worker pool, so multi-threaded compression is one of the things
  only this wheel provides. Which runtime an app ships is chosen by Flet, not by this repo, so
  treat that as a fact to re-check rather than a constant — the
  [`level-lab`](examples/level-lab) example prints `compression.zstd`'s version or `absent` in
  its header so you can read the answer for your own build.
- **More than half the wheel is a backend that can never load.** Both backends ship in every
  slice: the C extension *and* a compiled CFFI one, plus a 152,627-byte `backend_cffi.py`.
  `zstandard/__init__.py` selects `backend_c` unconditionally on CPython, so
  `zstandard.backend` is `"cext"`, and the CFFI half is unreachable rather than merely unused:
  `_cffi.so` imports `_cffi_backend`, the top-level extension the `cffi` distribution ships,
  so `PYTHON_ZSTANDARD_IMPORT_POLICY=cffi` gives `ModuleNotFoundError: No module named
  '_cffi_backend'`. Asking for the extra is not a general fix either — `zstandard[cffi]`
  resolves from this index on cp312 alone, and on 3.13 the install dies with `Could not find a
  version that satisfies the requirement cffi~=1.17`. There is no reason to want it. Leave the
  policy alone.
- **`import zstandard` costs about 85× `import zlib`.** Best of seven fresh desktop
  interpreters: 2.64 ms against `zlib`'s 0.031 ms, `lzma`'s 0.281 ms and `bz2`'s 0.272 ms.
  Most of that is loading the extension; the Python layer is one flat module pulling in 13
  others, none of them heavy.
- **`zstandard.backend_features` is a `set`, not a list.** Flet 0.86 cannot serialise a `set`
  in a control property: it raises `TypeError: can not serialize 'set' object` from msgpack,
  and only once a real client attaches, so it looks fine headlessly and fails on device.
  `sorted(...)` or `", ".join(sorted(...))` it before it reaches a control.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` names a version and a build number, and that is the whole recipe — no `patches`
directory, no `build.sh`, no `requirements`, no `script_env`. That is the fact worth
recording: zstandard vendors the entire libzstd amalgamation in its sdist and drives it from a
plain `setuptools` build, with no configure step, no system library to find and no platform
branching that a mobile triple falls off, so it cross-compiles to every slice on forge's stock
support alone. The day this recipe needs a patch, suspect the toolchain or an upstream
restructuring before reaching for one.

Both backends are built because upstream's `setup.py` builds both; only `backend_c` is ever
selected on CPython. Dropping the CFFI half would mean carrying a patch against a package that
otherwise needs none, to save about half a megabyte per slice.

The native module is `zstandard.backend_c`, an ordinary submodule — the package `__init__` is
plain Python. A package whose `__init__` *is* the extension is the shape that needs a loader
fix under Android's site-packages relocation; [`apsw`](../apsw) is the recipe carrying one.

### Upgrade hazards

- **The vendored libzstd version moves every ratio and every timing on this page.** A bump
  that changes it invalidates the level figures, the dictionary table and the
  `compression.zstd` interop claim together.
- **An externally linked libzstd would be a redesign, not a bump.** It would need a
  `flet-lib*` recipe and would put a runtime dependency into [Install](#install), which today
  is a two-line snippet.
- **The index still carries an older cp312-only line of this package at several build
  numbers.** pip takes the highest version, so the current one wins — but a cp312 slice that
  fails to build or gets yanked resolves back to that old line rather than failing loudly.
- **Wheel dates are not evidence of a mixed build.** Two armeabi-v7a slices are dated three
  weeks after the others; all of them report the same `Generator` and a byte-identical
  `METADATA`, so that is a rebuild, not toolchain skew.

### Re-verification checklist

- **libzstd is still vendored and still statically linked.** `strings -a` on `backend_c`
  should find the version, and `DT_NEEDED` / `otool -L` must still name no `libzstd`.
- **The link surface has not grown.** Android: `DT_NEEDED` is `libm.so`,
  `libpython3.<minor>.so`, `libdl.so` and `libc.so`, with no `libc++_shared`, and every
  `PT_LOAD` segment carries the 16 KB alignment Android 15 requires; armeabi-v7a and the
  legacy `x86` slice must stay genuine `ELF32` builds rather than stubs. iOS: both extensions
  `MH_DYLIB` marked `NOUNDEFS` (`otool -hv`), so no `MH_BUNDLE` conversion is needed, and
  `otool -L` naming only `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`.
- **`pthread_create` is still present in `backend_c`, and `PyEval_SaveThread` too.** The first
  is libzstd's worker pool, the second is the whole [Threading](#threading) section. Both are
  compile-time decisions and both are invisible in a green build.
- **`Requires-Dist` is still gated behind `extra == "cffi"`, and the payload is still eleven
  files with no data file.** An ungated `cffi` requirement would silently add a dependency to
  every consumer app, and a data file would raise the `extract_packages` question that today
  does not arise.
- **The extension filenames.** 3.13 and 3.14 ship
  `zstandard/backend_c.cpython-3<minor>-aarch64-linux-android.so` where the 3.12 wheels from
  the same build ship a bare `zstandard/backend_c.cpython-312.so` with no platform triple.
  Both spellings carry the `cpython-<minor>` tag, which is what the packaging keys on; a
  spelling that lost it would break Android relocation.
- **The thread-sharing failures.** Re-run two threads against one shared `ZstdCompressor` and,
  separately, one shared `ZstdDecompressor`. Give each thread a **different** payload and
  compare the round trip against that thread's own bytes: with a shared payload the
  decompressor's actual failure — wrong bytes, exit 0, no exception — is indistinguishable
  from success, which is how it gets written up as a clean crash. If a release ever makes
  either safe, the strongest warning on this page comes down; until then both must stay.
- **The `max_output_size` behaviour and the silent-corruption count.** Both are the kind of
  claim a patch release can change quietly, and both are why the [Storage](#storage) advice is
  shaped the way it is.
- **Whether Flet's mobile runtime still matches what this page says about `compression.zstd`.**
  Checked here against python-build release 20260730 — Android and iOS 3.14 bundles carry
  `_zstd` and `compression/zstd/`, 3.13 and 3.12 carry neither — but the runtime that ships in
  an app is chosen by Flet and serious_python, not by this repo's `PYTHON_BUILD_RELEASE` pin,
  so re-check against the Flet version in use.
- **Whether a bare `zstandard` still resolves from this index.** Today it must, because
  upstream publishes no Android, iOS or `py3-none-any` wheel — which also means the day it
  does, this recipe may stop being needed. Re-run `pip download --only-binary :all: --platform
  …` once per target tag, with PyPI listed first and this index only as `--extra-index-url`,
  and read the filename that comes back rather than comparing version numbers.
- **The sizes, in decimal units.** Re-measure compressed and unpacked from the wheels rather
  than scaling old figures, and divide by 10⁶: `du -h` reports binary units, so a 1.7 MB
  payload re-measured that way reads as 1.6 M and looks like a regression.
- **The measurements**, all of them: the level figures, the thread speedups with their
  `hashlib` control, the `multi_compress_to_buffer` table, the RSS peaks and the import
  timings. Re-measure rather than scaling — the shapes are the transferable part, and every
  absolute number above is a desktop number a phone will not reproduce.

### Coverage gaps

**No on-device run backs any consumer claim on this page.** Every one came off the wheels or
off a desktop install of the same version. The bridge licensing the second kind is narrow but
real: `__init__.py`, `__init__.pyi`, `backend_cffi.py`, `py.typed` and `METADATA` are
byte-identical between the Android arm64 3.14 wheel, the iOS device 3.14 wheel, the Android
x86 3.12 wheel and a PyPI desktop install, and every diagnostic string quoted above is present
in the Android arm64, Android armeabi-v7a **and** iOS device binaries, as are the three
`backend_features` strings. The one exception is `cannot train dict: Src size is incorrect`,
assembled at runtime from a `cannot train dict: %s` format string and libzstd's `Src size is
incorrect` — grep for the halves, not the message. What none of that establishes is that
`import zstandard` succeeds on a phone at all; the [`level-lab`](examples/level-lab) example is
the missing evidence, and its header lines are built to be the thing you read off the screen.

`tests/test_zstandard.py` covers a one-shot round trip and a `stream_writer`/`stream_reader`
pair. It exercises nothing this page warns app authors about, and three additions would be
worth more than any timing: `zstandard.backend == "cext"` (the [App size](#app-size) and
backend story assumes the C extension is what loads, and a wheel that silently fell back to
CFFI would still pass today's tests), a dictionary round trip plus the mismatch raise, and
`write_checksum=True` catching a flipped byte.
