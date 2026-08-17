# zstandard

[`zstandard`](https://python-zstandard.readthedocs.io/en/latest/) is the Python binding to
Facebook's [Zstandard](https://facebook.github.io/zstd/) compression library, with libzstd
1.5.7 compiled straight into the extension — nothing to install alongside it. It builds for
**both** platforms here: nineteen wheels, every Android ABI and every iOS slice Flet targets,
on Python 3.12, 3.13 and 3.14.

The reason it earns its place on a phone is **the shape of its cost curve, not its ratio**.
On ratio alone it does not always win: given enough CPU, `lzma` at its default preset squeezed
3.85 MB of log lines to 100,292 bytes where zstd's very best (level 22) managed 163,193. What
zstd does that neither `bz2` nor `lzma` can is **decompress at the same speed no matter how
hard it worked to compress**. On the [`level-lab`](examples/level-lab) example's 879,176-byte
payload, reading a frame back took 0.20–0.34 ms at *every* level from -5 to 19 (45
measurements, nine levels × five sweeps), where `bz2` 9 took 6.4–7.1 ms and `lzma` preset 1
took 3.1–3.2 ms for output of comparable size. A phone reads its caches far more often than it
writes them, so you choose a level for the write cost and get the read for free. The second
reason is the [dictionary API](#things-to-know), which is the difference between zstd being
useless and being 4× on collections of small records.

One thing to check before adding it: **Python 3.14 has zstd in the standard library**, and
Flet's 3.14 mobile runtime ships it. See [Things to know](#things-to-know) for what this
wheel still adds there, and note that 3.12 and 3.13 runtimes carry no zstd at all.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "zstandard",
]
```

Nothing else to configure, and nothing comes along with it. The wheel's `METADATA` carries
two `Requires-Dist` lines, but both are gated on `extra == "cffi"` — an extra you have to ask
for by name — so a bare `zstandard` installs no `cffi`, no `flet-lib*` wheel and no
transitive dependency whatsoever.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed either. The payload is eleven files: two extensions, `__init__.py`,
`__init__.pyi`, `backend_cffi.py`, an empty `py.typed`, and the `dist-info`. There is no data
file, and `__file__`, `importlib.resources`, `pkgutil`, `pkg_resources` and `getsource` do
not appear anywhere in the Python layer — the only `builtins.open` is the one inside
`zstandard.open()`, opening the path you passed it. Both extensions carry a `cpython-3XX` ABI
tag on every slice, which is what Android's site-packages relocation keys on.

**A bare `zstandard` really does resolve from this index.** Upstream publishes 99 files for
0.25.0 on PyPI and not one of them is an Android wheel, an iOS wheel or a `py3-none-any`
wheel, so there is nothing pip can select for a mobile target anywhere else. Checked with
`pip download --only-binary :all:` with **PyPI listed first** and this index only as
`--extra-index-url`, one check per platform tag spread across the three Pythons — Android
arm64-v8a on 3.14, armeabi-v7a on 3.12, x86_64 on 3.13 and the legacy x86 on 3.12, iOS device
on 3.13, the arm64 simulator on 3.12 and the x86_64 simulator on 3.14 — all seven came back
with this index's wheel.

Nineteen wheels at the same build number: Android arm64-v8a, armeabi-v7a and x86_64 and iOS
device, arm64-simulator and x86_64-simulator on each of 3.12, 3.13 and 3.14, plus a legacy
32-bit `android_24_x86` slice on 3.12 only. No
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. `Requires-Python` in the wheel is the upstream `>=3.9`, so the floor you
will actually hit is Flet's, not zstandard's.

## Storage

A compressed file the app owns belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which is app-private, never auto-deleted and included in backups; a derived one that can be
rebuilt belongs in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache),
and scratch in
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp).
The file API is `zstandard.open()`, which mirrors `builtins.open` and closes what it opened:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "snapshot.zst")
with zstandard.open(path, "wb") as handle:
    handle.write(payload)
with zstandard.open(path, "rb") as handle:
    payload = handle.read()
```

Three things about writing to a phone's filesystem specifically:

- **Ask for a checksum.** `write_checksum` defaults to `False`, and a frame without one can
  decompress to the wrong bytes with no exception at all — measured below. Four bytes per
  frame is nothing against a half-written file after the OS killed the app:
  `zstandard.open(path, "wb", cctx=zstandard.ZstdCompressor(write_checksum=True))`.
- **Pass `size=` when you stream.** `zstandard.open(path, "wb")` and
  `ZstdCompressor().stream_writer(handle)` both write a frame whose header declares *no*
  content size — `zstandard.frame_content_size()` on one returns `-1` — which means a plain
  `ZstdDecompressor().decompress()` refuses to read it back later, and which is also what
  makes a high level reserve an enormous compression context. Using `stream_writer` directly
  and passing `size=len(payload)` fixes both at once.
- **Read big frames in chunks.** `stream_reader(handle).read(65536)` in a loop never holds
  more than a chunk, where `decompress()` allocates the whole output up front — and will
  do so even when you asked it not to (see [Things to know](#things-to-know)).

There is no atomic-write machinery in the library, so if a truncated file would hurt, write
beside the target and `os.replace` it yourself.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`level-lab`](examples/level-lab) — sweeps the zstd level range on device against `zlib`,
  `bz2` and `lzma`, and shows what a trained dictionary is worth on many small records.

## Threading

**The C extension releases the GIL, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys real
parallelism** — unlike [`orjson`](../orjson), whose recipe README measures none at all.
`PyEval_SaveThread` and `PyEval_RestoreThread` are undefined symbols on all nineteen slices,
and the source releases it in all the places that matter (8 `Py_BEGIN_ALLOW_THREADS` in
`decompressor.c`, 4 in
`compressor.c`, 2 in `compressiondict.c`, so even `train_dictionary` yields). Measured on
desktop two ways, each against controls that make a false answer visible. A pure-Python
counting thread — which can only advance while it holds the GIL — kept **100.3%** of its idle
rate while the main thread compressed, **100.4%** while it decompressed and **99.4%** while it
trained a dictionary, against **101.7%** for a `hashlib.sha256` control that does release the
GIL and **50.2%** for a pure-Python control that does not. And in throughput: four threads
compressing a 3.6 MB payload at level 10 gave a **2.84–3.02×** speedup over one thread across
three runs, where the same harness gave `hashlib.sha256` **3.40–3.79×**.

**But one `ZstdCompressor` or `ZstdDecompressor` used from two threads at once breaks, and
the two break differently — the compressor loudly, the decompressor silently.** Measured on
desktop, ten fresh processes per cell, each worker compressing *its own distinct payload* and
checking the round trip against its own bytes (a shared payload would make a swapped result
indistinguishable from a correct one, which is how this reads as a clean crash):

| what the threads share | 2 threads | 4 threads | 8 threads |
|---|---|---|---|
| one `ZstdCompressor` | process killed 10/10 | killed 8/10, `ZstdError` in the rest | killed 8/10, `ZstdError` in the rest |
| one `ZstdDecompressor` | **wrong bytes, no exception, exit 0** in 2/10 | wrong bytes in 8/10 | wrong bytes in 9/10, killed 1/10 |
| a `threading.Lock` around the whole call | 0 errors, 0 wrong | 0 errors, 0 wrong | 0 errors, 0 wrong |
| a fresh `ZstdCompressor` per thread | 0 errors, 0 wrong | 0 errors, 0 wrong | 0 errors, 0 wrong |
| `zstandard.compress()` / `.decompress()` | 0 errors, 0 wrong | 0 errors, 0 wrong | 0 errors, 0 wrong |

The compressor's failure is an uncatchable native signal — SIGSEGV or SIGBUS, no traceback,
nothing in the log — so you cannot miss it. **The decompressor's is worse: it usually returns
plausible-looking wrong bytes.** Two threads and 40 iterations each was enough to corrupt a
round trip in 2 of 10 runs with no exception raised anywhere; at eight threads every run
corrupted something, and a minority of runs raise a *catchable* `ZstdError`
(`Data corruption detected`, `Unknown frame descriptor`, `Src size is incorrect`) instead.
So do not read "no crash" as "safe", and do not let a `try/except ZstdError` convince you it
is handled.

This is exactly the shape of `page.run_thread`, whose workers run on a shared pool and
genuinely overlap when the user taps twice — so **build the compressor and the decompressor
inside the worker**, or guard a shared one with a `threading.Lock` taken around the entire
call. The module-level `zstandard.compress(data, level)` and `zstandard.decompress(data)` are
safe because they build a context per call, and pay for it: prefer a per-thread compressor in
a loop. Upstream warns that "errors will likely occur" and that you need one instance per
overlapping operation, which undersells it — an error is the good case here.

The wheel is also built **with** libzstd's own multi-threading (`ZSTD_MULTITHREAD` is set in
the vendored amalgamation, and eleven `pthread_*` entries — `pthread_create`, `pthread_join`
and the `pthread_cond_*`/`pthread_mutex_*` families — are undefined symbols on all nineteen
slices), so the `threads=` argument works rather than raising. Where it actually pays is
[`multi_compress_to_buffer`](https://python-zstandard.readthedocs.io/en/latest/compressor.html#zstandard.ZstdCompressor.multi_compress_to_buffer),
which compresses independent records in parallel: 20,000 records totalling 2.45 MB took 62.7
ms at `threads=1` against **12.6 ms** at `threads=-1` (level 10), and 168.1 ms against 30.6 ms
at level 19, with byte-identical output. On a *single* large input `threads=` bought almost
nothing on the payloads tried — 341 ms against 316 ms at level 15 on 20 MB, and level 19 was
slower with four threads than with none — so measure before reaching for it there.

The usual Flet rules still apply: a `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), and its body must be
wrapped in `try/except`, because `run_thread` discards whatever it raises — a `ZstdError` in a
worker looks like a screen that stopped updating, not like an error.

## Android notes

Both extensions link nothing beyond the interpreter and libc. `DT_NEEDED` is `libm.so`,
`libpython3.<minor>.so`, `libdl.so` and `libc.so` on all ten Android slices — **no
`libzstd`**, because the amalgamation is compiled into the extension, and no `libc++_shared`,
so none of the usual Android C++ staging applies. Of the 106–107 undefined symbols on
`backend_c`, the 30 outside CPython's own API are all bionic libc: the malloc family,
`memcpy`/`memmove`/`memset`, `qsort`, `clock`, `sysconf`, the stdio handles, and the eleven
`pthread_*` entries libzstd's worker pool uses. All `PT_LOAD` segments of both extensions on
all ten slices carry 16 KB alignment, which Android 15 requires. arm64-v8a and x86_64 are
`ELF64`; armeabi-v7a and the legacy `x86` slice are genuine `ELF32`/`ARM` and `ELF32`/`i386`
builds rather than stubs.

**The extension filenames are not spelled the same on every Python**, which matters only if
you go looking for them in an app payload: 3.13 and 3.14 ship
`zstandard/backend_c.cpython-3<minor>-aarch64-linux-android.so` (and
`…-arm-linux-androideabi.so`, `…-x86_64-linux-android.so`) where the 3.12 wheels from the same
build ship a bare `zstandard/backend_c.cpython-312.so` with no platform triple. Both spellings
carry the `cpython-<minor>` tag, which is what the packaging keys on.

The native module is `zstandard.backend_c`, an ordinary submodule — not the package
`__init__` — so this wheel does not touch the class of Android failures that
[`apsw`](../apsw) exists to document. Flet relocates tagged extensions out of site-packages,
which normally makes a native module's `__file__` unreliable; here it does not matter,
because nothing in the package ever reads it.

## iOS notes

**The extensions need no fixing up.** Both of them, on all nine iOS slices, are already
`MH_DYLIB` marked `NOUNDEFS` (`otool -hv`), which is the filetype Flet 0.86's iOS packaging
needs — so the `MH_BUNDLE` link failure that has bitten other recipes on this index does not
apply here.

Besides its own install name, `otool -L` names exactly two libraries on every one of the
eighteen iOS binaries: `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`. That
is the whole external surface — no third-party dylib to ship beside it and nothing to preload.
Of the 107–110 undefined symbols, the 31–33 outside CPython's API are all libSystem: the malloc
and mem families, `qsort_r`, `clock`, `sysctlbyname`, the stack-protector symbols,
`dyld_stub_binder` and the same eleven `pthread_*` entries as on Android.

iOS carries about 11% more native code than Android arm64 for the same version — `backend_c`
is 770,904 bytes on the 3.14 device slice against 694,472 on Android arm64-v8a, and `_cffi`
894,408 against 813,368. Those two gaps are 157,472 bytes together, which is the entire
157,449-byte difference in unpacked size between the two platforms give or take the 23 bytes
their `dist-info` files differ by.

## Things to know

- **A higher level is not a smaller file. Ratio is not monotonic, and it is deterministic
  about it.** Measured on the [`level-lab`](examples/level-lab) payload (879,176 bytes, half
  API JSON and half log lines): level 2 → 83,949 bytes beats level 3 → 87,141 *and* level 6
  → 93,557; level 10 → 66,512 beats level 15 → 68,612. On a second dataset of 3.85 MB of log
  lines the same thing happens in different places — level 2 → 331,223 against level 3 →
  368,026, an 11% swing the wrong way — and re-running each level three times produced
  byte-identical output every time, so this is the algorithm, not noise. The mechanism is
  visible in `ZstdCompressionParameters.from_level()`: levels 1 and 2 use `strategy 1` with
  `min_match` 7 and 6, where level 3 switches to `strategy 2` with `min_match` 5. **Measure on
  your own payload**, and default to 1–3 for anything written during a user interaction.
- **`max_output_size` is silently ignored when the frame declares its content size** — which
  is the default for `compress()`. `ZstdDecompressor().decompress(bomb, max_output_size=1 << 20)`
  returned 67,108,864 bytes from a 2,067-byte frame: a 32,467× expansion, with the limit set.
  The C source only consults `maxOutputSize` in the `ZSTD_CONTENTSIZE_UNKNOWN` branch;
  otherwise it allocates the declared size outright. For untrusted input, check first with
  `zstandard.frame_content_size(frame)` — it reads the header and allocates nothing, returning
  `-1` when the size is not declared — and decide yourself; or read through `stream_reader` in
  bounded chunks and stop, which is verified to halt after 1,114,112 bytes of a 64 MiB bomb
  read 64 KB at a time. `max_output_size` *does* work on frames with no declared size, where
  it raises `ZstdError: decompression error: did not decompress full frame`.
- **A streamed frame cannot be read back with `decompress()`.** `stream_writer` and
  `zstandard.open(path, "wb")` write no content size, so `frame_content_size` on the result is
  `-1` and `ZstdDecompressor().decompress(frame)` raises `ZstdError: could not determine
  content size in frame header`. Compress one way and decompress the other and it fails only
  at runtime, on device. Three fixes, all verified: pass `size=len(data)` to `stream_writer`;
  pass a `max_output_size=` to `decompress()` that is at least the real output length (too small
  and you get `did not decompress full frame` instead); or read it back with `stream_reader`,
  which never needs the header size. The recipe's own `tests/test_zstandard.py` already pairs
  `stream_writer` with `stream_reader`, which is why it does not trip on this.
- **Forgetting to close a `stream_writer` loses the file, and how it loses it depends on the
  size.** `w = cctx.stream_writer(sink, closefd=False); w.write(payload)` with no `close()`
  buffers up to about 128 KB of *compressed* output, and only what overflows that buffer has
  reached the sink. Measured at level 3: a 100,000-byte payload leaves the sink **empty**,
  where 1,000,000 bytes leaves 136 bytes and 3,853,317 bytes leaves 400 — a genuinely
  truncated frame, and not an inert one. `decompress()` refuses either way (empty or garbage
  gives `ZstdError: error determining content size from frame header`, a truncated frame gives
  `could not determine content size in frame header`, and neither message points near the
  cause) but `stream_reader` will happily decode a *prefix* out of the remnant — 3,670,016 of
  those 3,853,317 bytes — so a cache file written this way reads back short and silent. Always
  use `with cctx.stream_writer(handle) as w:`, and pass `closefd=False` when the sink is a
  `BytesIO` you still want to read.
- **Frame corruption is silent unless you asked for a checksum, and you did not.**
  `get_frame_parameters(cctx.compress(data)).has_checksum` is `False` by default. Flipping a
  single bit at each of 400 positions through a 342,082-byte frame: **141 of them decompressed
  to the wrong bytes with no exception at all**, and 259 raised. With
  `ZstdCompressor(write_checksum=True)` — four bytes longer — all 400 raised, and those same
  141 came back as `ZstdError: decompression error: Restored data doesn't match checksum`.
- **`ZstdError` inherits straight from `Exception`**, not from `OSError`, not from
  `zlib.error`, not from anything the stdlib codecs raise, so an existing
  `except (zlib.error, lzma.LZMAError)` block will not catch it. And it is not what argument
  mistakes raise: `ZstdCompressor(level=23)` gives `ValueError: level must be less than 23` and
  `compress("a str")` gives `TypeError: a bytes-like object is required, not 'str'`. In a Flet
  event handler catch broad `Exception` around whatever parses user input, because an
  unhandled raise there makes Flet send `SESSION_CRASHED`.
- **A trained dictionary is what makes zstd worth using on many small records — and it needs
  a real corpus.** 2,000 JSON records averaging 214 bytes, 428,694 bytes in total, dictionary
  trained on a disjoint 2,000, all at level 1: a frame per record with no dictionary is
  342,030 bytes (ratio 1.25 — very nearly nothing), with a 16 KB dictionary 101,620
  (ratio 4.22), and all 2,000 in a single frame 41,680 (ratio 10.29). The shape holds at every
  level on the dial. So reach for a dictionary when records must
  stay independently addressable, and batch into one frame when they need not.
  `train_dictionary(16384, samples)` costs about 11 ms on desktop for that corpus, but
  `train_dictionary(16384, samples[:3])` and `train_dictionary(16384, [])` both raise
  `ZstdError: cannot train dict: Src size is incorrect`, a message that does not say what is
  wrong — train on hundreds to thousands of representative records and catch `ZstdError`
  around the call. The size you pass is a ceiling, not a promise: on that corpus, asking for
  16,384 and 112,640 bytes returned exactly those, while asking for 1,048,576 returned
  218,891, so read the real size back with `len(d.as_bytes())`.
- **Dictionaries are safe to get wrong, and they persist.** The dictionary id travels in the
  frame header, so decompressing with a differently-trained dictionary — or with none —
  raises `ZstdError: decompression error: Dictionary mismatch` rather than returning garbage.
  `ZstdCompressionDict(d.as_bytes())` reproduces byte-identical output to the original object
  and decompresses frames made with it, so the 16 KB blob can be stored beside the data and
  reloaded.
- **High levels are a memory decision, not just a speed one, and streaming without `size=` is
  the worst case.** Peak RSS in a fresh desktop process, 3.85 MB input, 30.3 MB baseline:
  one-shot level 3 → no measurable extra, level 10 → 46.4 MB, level 15 → 90.2 MB, level 19 →
  75.1 MB, level 22 → 91.0 MB; `stream_writer` **without** `size=` at level 19 → 111.3 MB and
  at level 22 → **565.6 MB**. Passing `size=len(data)` cuts that level-22 case back to
  92.2 MB. The library will tell you before you try:
  `ZstdCompressionParameters.from_level(22).estimated_compression_context_size()` is
  672,399,510 bytes with an unknown source size against 1,303,576 at level 3. Decompression is
  cheap regardless — `estimate_decompression_context_size()` is 95,968 bytes at every level,
  and a level-22 frame decodes with a default decompressor.
- **On Python 3.14, some of this is already in the standard library.** Flet's 3.14 mobile
  runtime ships `compression.zstd` with the same libzstd 1.5.7 on both platforms; its 3.13 and
  3.12 runtimes ship no zstd at all, so an app supporting those still needs this wheel.
  Frames interoperate in both directions. What the wheel adds on 3.14: `stream_writer` /
  `stream_reader` / `chunker` / `read_to_iter` / `copy_stream`, `multi_compress_to_buffer` and
  the buffer types, `ZstdCompressionParameters`, `frame_content_size`, `get_frame_parameters`,
  `estimate_decompression_context_size`, and working multi-threaded compression — the stdlib
  `_zstd` in that runtime has no `pthread_*` symbols at all, where this wheel's `backend_c`
  has eleven, so libzstd's worker pool cannot be there. Which runtime an app ships is chosen
  by Flet, not by this repo, so treat that as a fact to re-check rather than a constant; the
  [`level-lab`](examples/level-lab) example prints `compression.zstd`'s version or `absent`
  in its header so you can read the answer for your own build.
- **57% of the wheel is a backend that can never load.** Both backends ship in every slice:
  the C extension *and* a compiled CFFI one, plus the 152,627-byte `backend_cffi.py`. On
  Android arm64 3.14 that dead half is 965,995 of 1,687,516 unpacked bytes; on the iOS device
  slice 1,047,035 of 1,844,965. `zstandard/__init__.py` selects `backend_c` unconditionally on
  CPython, so `zstandard.backend` is `"cext"`, and the CFFI half is not merely unused but
  unreachable: `_cffi.so` imports `_cffi_backend`, the top-level extension module that the
  `cffi` distribution ships, and nothing pulls `cffi` in. Setting
  `PYTHON_ZSTANDARD_IMPORT_POLICY=cffi` without it gives `ModuleNotFoundError: No module named
  '_cffi_backend'`, and you cannot generally fix that by asking for the extra: `zstandard[cffi]`
  resolves from this index on 3.12 only. Its own metadata requires `cffi~=1.17` below Python
  3.14, and the index carries `cffi` 1.17.1 for cp312 alone, so on 3.13 the install dies with
  `Could not find a version that satisfies the requirement cffi~=1.17 … (from versions: 2.0.0)`.
  There is no reason to want it. Leave the policy alone.
- **`import zstandard` costs about 85× `import zlib`.** Best of seven fresh desktop
  interpreters: 2.64 ms against `zlib`'s 0.031 ms, `lzma`'s 0.281 ms and `bz2`'s 0.272 ms.
  Most of that is loading the extension; the Python layer is one flat module that pulls in 13
  modules, none of them heavy — `platform`, `re`, `enum`, `copyreg`, `__future__` and their
  dependencies.
- **`zstandard.backend_features` is a `set`, not a list.** Flet 0.86 cannot serialise a `set`
  in a control property: it raises `TypeError: can not serialize 'set' object` from msgpack,
  and only once a real client attaches, so it looks fine headlessly and fails on device.
  `sorted(...)` or `", ".join(sorted(...))` it before it reaches a control.
- **Size: 610–822 KB to download and 1.30–1.99 MB unpacked** across all nineteen slices, of
  which the two extensions are 87–91%. Eleven files each. On Python 3.14 (3.12 is within 600
  bytes of 3.14 on Android arm64):

  | slice | wheel | unpacked | `backend_c` | `_cffi` (unused) |
  | --- | --- | --- | --- | --- |
  | Android arm64-v8a | 620 KB | 1.61 MB | 694,472 B | 813,368 B |
  | Android armeabi-v7a | 672 KB | 1.30 MB | 555,232 B | 629,940 B |
  | Android x86_64 | 743 KB | 1.85 MB | 827,560 B | 937,128 B |
  | iOS arm64 (device) | 611 KB | 1.76 MB | 770,904 B | 894,408 B |
  | iOS arm64 (simulator) | 632 KB | 1.76 MB | 777,048 B | 885,016 B |
  | iOS x86_64 (simulator) | 768 KB | 1.97 MB | 888,496 B | 995,600 B |

  Everything that is not an extension comes to 179,626–179,678 bytes, a spread of 52 bytes
  across all nineteen: `backend_cffi.py` (152,627 B), the 13,973-byte `__init__.pyi`, the
  7,235-byte `__init__.py`, an empty `py.typed` and a small `dist-info` — `METADATA` is only
  3,275 bytes here, since upstream's README is short.

## Build notes (maintainers)

A six-line `meta.yaml` naming the version and a build number, no `patches` directory, no
`build.sh`, no `requirements`, no `script_env`. That is the fact worth recording: zstandard
vendors the whole libzstd amalgamation in its sdist and drives it from a plain
`setuptools` build with no configure step, no system library to find and no platform
branching that a mobile triple falls off — so it cross-compiles to all nineteen slices on
forge's stock support alone. The day this recipe needs a patch, suspect the toolchain or an
upstream restructuring before reaching for one.

**No on-device run backs anything above this section.** Every claim came off the wheels or off
a desktop install of the same version, and the bridge that licenses the second kind is narrow
but real: `__init__.py`, `__init__.pyi`, `backend_cffi.py`, `py.typed` and `METADATA` are
byte-identical between the Android arm64 3.14 wheel, the iOS device 3.14 wheel, the Android
x86 3.12 wheel and a PyPI desktop install, and every diagnostic string quoted above is present
in the Android arm64, Android armeabi-v7a **and** iOS device binaries, as are the three
`backend_features` strings. All but one are single literals (`Dictionary mismatch`,
`Restored data doesn't match checksum`, `could not determine content size in frame header`,
`error determining content size from frame header`, `did not decompress full frame`,
`Data corruption detected`, `level must be less than`); the exception,
`cannot train dict: Src size is incorrect`, is assembled
at runtime and appears as its two halves — the `cannot train dict: %s` format string and
libzstd's `Src size is incorrect` — so grep for those, not for the message. What
that does not establish is that `import zstandard` succeeds on a phone at
all; the [`level-lab`](examples/level-lab) example is the missing evidence, and its header
lines are built to be the thing you read off the screen.

One oddity in the current build, harmless but worth knowing when reading timestamps: the 3.13
and 3.14 armeabi-v7a wheels are dated 2026-06-29 where the other seventeen are 2026-06-08
(every 3.12 slice, the 3.12 v7a included) or 2026-06-11 (the rest of 3.13 and 3.14) — the same
two-slice split [`orjson`](../orjson) shows. All nineteen say `Generator: setuptools (82.0.1)`
and carry a byte-identical `METADATA`, so unlike orjson there is no toolchain skew behind it.
The index
also still carries a 0.23.0 line at builds 1, 4 and 10, cp312 only; pip takes the highest
version, so 0.25.0 wins.

`tests/test_zstandard.py` is two docstringed functions — a one-shot round trip and a
`stream_writer`/`stream_reader` pair — with no version assertion, so it already matches the
repo's test conventions. What it does not cover is anything this page warns app authors about,
and three additions would be worth more than any timing: `zstandard.backend == "cext"` (the
whole [Install](#install) and size story assumes the C extension is what loads, and a wheel
that silently fell back to CFFI would still pass today's tests), a dictionary round trip plus
the mismatch raise, and `write_checksum=True` catching a flipped byte.

On a bump, in rough order of what a green build fails to tell you:

- **That libzstd is still 1.5.7, and still statically linked.** `strings -a` on `backend_c`
  should find the version, and `DT_NEEDED` / `otool -L` must still name no `libzstd`. A
  vendored-version change moves every ratio on this page; an *externally* linked libzstd would
  need a `flet-lib*` recipe and would break the [Install](#install) section outright.
- **`Requires-Dist` still gated behind `extra == "cffi"`, and still eleven files.** An
  ungated `cffi` requirement would silently add a dependency to every consumer app, and a new
  data file would put the no-`extract_packages` claim back in question.
- **`pthread_create` still present in `backend_c`, and `PyEval_SaveThread` too.** The first is
  the multi-threading build flag; the second is the whole [Threading](#threading) section. Both
  are invisible in a green build and both are compile-time decisions.
- **The thread-sharing failures.** Re-run two threads against one shared `ZstdCompressor` and,
  separately, one shared `ZstdDecompressor`. Give each thread a **different** payload and
  compare the round trip against that thread's own bytes: with a shared payload the
  decompressor's actual failure — wrong bytes, exit 0, no exception — is indistinguishable from
  success, which is how it gets written up as a clean crash. If a release ever makes either
  safe, the strongest warning on this page comes down; until then both must stay.
- **The `max_output_size` behaviour and the silent-corruption count.** Both are the kind of
  claim that a patch release can change quietly, and both are the reason the
  [Storage](#storage) advice is shaped the way it is.
- **Whether Flet's mobile runtime still matches what this page says about
  `compression.zstd`.** Checked here against python-build release 20260730 — Android and iOS
  3.14 bundles carry `_zstd` and `compression/zstd/`, 3.13 and 3.12 carry neither — but the
  runtime that ships in an app is chosen by Flet and serious_python, not by this repo's
  `PYTHON_BUILD_RELEASE` pin, so re-check it against the Flet version in use rather than
  against this pin.
- **Whether a bare `zstandard` still resolves from this index.** Today it must, because
  upstream publishes no mobile and no universal wheel — which also means the day it does, this
  recipe may stop being needed. Re-run one `pip download --only-binary :all: --platform …`
  per target and read the filename that comes back, rather than comparing version numbers.
- **The measurements**, all of them: the level tables, the GIL speedups with their `hashlib`
  control, the `multi_compress_to_buffer` 5×, the RSS peaks, the import timings and the size
  table. Re-measure rather than scaling — the shapes are the transferable part, and every
  absolute number above is a desktop number a phone will not reproduce.
