# xxhash

[`xxhash`](https://github.com/ifduyue/python-xxhash) is the Python binding for
[xxHash](https://github.com/Cyan4973/xxHash), a family of non-cryptographic hash functions
whose selling point is that they run at memory speed. On an Apple M4 desktop under CPython
3.14.6, over a 1 MiB buffer, `xxh3_64` produced 47,502 MB/s against `hashlib.sha256`'s 3,008
and `hashlib.md5`'s 886 — 15× and 53×.

**The phone answered on 2026-08-20, and the ratio is not portable even though the throughput
is.** Over the same 1 MiB buffer, both at CPython 3.14.6: an iPhone 16 simulator gave
`xxh3_64` 47,328 MB/s against `sha256` 590, a **80.3×** win; an arm64-v8a Android 14 emulator
gave `xxh3_64` 16,554 against `sha256` **17**, which reads as 999×. The second number is an
artefact and you should not quote it. `sha256` at 17 MB/s is roughly 175× slower than the same
call on the simulator and ~35× slower than the desktop figure above, which is what a CPU
*without* the ARMv8 SHA-2 extensions looks like — the emulator image does not expose them. The
honest summary for a real arm64 phone is the shape iOS shows: xxh3_64 is around one order of
magnitude faster than SHA-256 and roughly level with `crc32` (1.09× on iOS, 1.28× on Android).
Take xxhash for speed over `md5`, never for the sha256 comparison alone.

Streaming costs something real and it is worth knowing before you design around it: feeding
1 MiB in 64 KiB updates matched the one-shot digest exactly on both platforms, at 18,340 MB/s
against 47,958 one-shot on iOS and 9,472 against 14,410 on Android — so roughly 2.6× and 1.5×
slower than hashing the buffer in one call.

The importable surface is four algorithms — `xxh32`, `xxh64`, `xxh3_64` and `xxh3_128` (also
spelled `xxh128`) — each available as a one-shot function and as an incremental object with
`update`/`digest`/`copy`/`reset`.

**It is not a checksum against tampering and it is not a substitute for a cryptographic
hash.** Two measurements make that concrete, and the
[`stream-digest`](examples/stream-digest) example runs both on the device:

- A seeded birthday search finds two 32-byte inputs sharing an `xxh32` digest after 113,202,
  39,741 and 16,915 tries for seeds 0, 1 and 2 — **21, 7 and 3 milliseconds** on that
  desktop. A 32-bit digest is 2^16 tries from a collision and no amount of speed changes it.
- For an input of exactly four bytes, XXH32 is a **permutation**: every step is a bijection
  on 32 bits, so it can be run backwards. 2,000 of 2,000 four-byte inputs were recovered
  byte-exact from their digest alone in 2.0 ms, and 1,999,512 distinct four-byte inputs
  produced 1,999,512 distinct digests where a uniform random hash would have collided about
  465 times. A seed does not fix this; a seed is a parameter, not a key.

So use it for cache keys, deduplication, content fingerprints, shard selection, change
detection and "did this file finish downloading intact" — the cases where the other party is
a disk or a network, not an adversary. When the other party might be hostile, the standard
library already has the answer and it is fast enough to measure rather than assume:
`hashlib.sha256` (3,008 MB/s here, because arm64 has SHA-256 instructions) or
`hashlib.blake2b` (1,385 MB/s) for integrity, `hmac.new(key, msg, hashlib.sha256)` or
`hashlib.blake2b(msg, key=...)` for authentication, and `hashlib.scrypt` for passwords.
`zlib.crc32` is the honest competitor at the accidental-corruption end and it is not slow:
40,778 MB/s at 1 MiB on this desktop, within 16% of `xxh3_64`.

**On-device numbers are not filled in yet.** Everything measured below was measured on a
desktop or read out of the published wheels, and each claim says which. The
[`stream-digest`](examples/stream-digest) example exists to replace the timings with a
phone's own.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "xxhash",
]
```

The entry belongs in top-level `[project] dependencies` and not in a
`[tool.flet.<platform>]` table: `flet build` resolves for the build host first, and PyPI has
desktop wheels for every host you would build from — the 3.8.0 release alone is 186 wheels
plus an sdist, covering CPython 3.8 through 3.14 (and free-threaded 3.13t/3.14t) on macOS,
Linux, musl and Windows, alongside the mobile slices discussed next. So `flet run` on your
laptop gets the same API you ship.

**Unlike most packages on this index, upstream publishes mobile wheels of its own — and by
default your app will get those instead.** This is the fact worth reading twice before
anything else on this page. Checked with `pip download --only-binary :all:` (pip 26.2.1),
PyPI first and `https://pypi.flet.dev` as `--extra-index-url`, which is exactly how
serious_python 4.5.1 invokes pip (`package_command.dart:283`, `:457`), once per Python and
per platform tag:

| bare `xxhash` | 3.12 | 3.13 | 3.14 |
| --- | --- | --- | --- |
| android arm64-v8a | this index 3.8.0 | **PyPI 4.0.1** | **PyPI 4.0.1** |
| android x86_64 | this index 3.8.0 | **PyPI 4.0.1** | **PyPI 4.0.1** |
| android armeabi-v7a | this index 3.8.0 | this index 3.8.0 | this index 3.8.0 |
| iOS device / both simulators | this index 3.8.0 | **PyPI 4.0.1** | **PyPI 4.0.1** |

Upstream's 4.0.1 release ships `android_24_arm64_v8a`, `android_24_x86_64` and all three iOS
slices for cp313, cp314 and cp315 — and **no `armeabi-v7a` for any Python, and no mobile
wheel at all for 3.12**, whose 4.0.1 wheels are desktop-only. This recipe is what fills those
two holes. That is not a hypothetical gap: serious_python runs pip **once per Android ABI**
into a separate directory (`package_command.dart:434`), so on Python 3.13 or 3.14 an all-ABI
build genuinely resolves 4.0.1 for two ABIs and 3.8.0 for the third.

Two ways to make it uniform, and one reason you might not bother:

- **Pin the version.** `"xxhash==3.8.0"` puts all eighteen slices on this index's wheels,
  verified for every Python and platform tag. It is not a walkover: upstream's own 3.8.0
  release publishes ten mobile wheels of its own — `android_21_arm64_v8a`,
  `android_21_x86_64` and all three iOS slices for cp313, and the same five with
  `android_24` for cp314 — so ten of the eighteen have a PyPI rival, and this index wins all
  ten for two different reasons. Eight of the ten (both cp314 Android ABIs and all six iOS
  slices) carry a byte-identical platform tag, and there the build tag `1` this index adds
  decides it. The other two are cp313 `arm64-v8a` and `x86_64`, upstream `android_21`
  against this index's `android_24`, and there the *platform tag* decides — pip offers
  Android tags from the target API level downwards, so `android_24` outranks `android_21`.
  Do not read that as the build tag winning: feed pip the same two candidates with
  `android_21` preferred and it takes upstream's untagged wheel instead. This is what
  [`stream-digest`](examples/stream-digest) does.
- **Drop the 32-bit ABI**, if you were going to anyway — `["arm64-v8a", "x86_64"]` in
  [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
  leaves nothing for this index to fill on 3.13 and 3.14, and a bare `xxhash` then resolves
  upstream everywhere. (The recipe itself excludes no architecture, so `target_arch` is
  never *required* for xxhash.) It is also the one ABI whose slice is built without NEON —
  see [Android notes](#android-notes) — so it is the slice least likely to show you the
  speed the rest of this page is about.
- **Or accept the skew.** The digests are identical: 3.8.0 and 4.0.1 agreed on all 40
  digests of 10 payload lengths × 4 algorithms on desktop, because both bundle libxxhash
  0.8.x and the algorithms are frozen. What differs is the Python layer — 4.0.1 dropped
  `VERSION_TUPLE` and added `algorithms_guaranteed` — and one consequence has teeth, in
  [Android notes](#android-notes).

Nothing comes along with the wheel: all eighteen `METADATA` files contain **zero**
`Requires-Dist` lines, so no `flet-lib*` wheel and no transitive dependency follows.
`Requires-Python` is `>=3.8` on every one of them, which constrains nothing you can ship —
the Python floor you actually hit is Flet's `>=3.10`.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Every wheel is ten files — one extension, `__init__.py`, `version.py`, a
`.pyi` stub, an empty `py.typed`, and five `dist-info` entries — with no data file of any
kind, and neither `__init__.py` nor `version.py` mentions `__file__`, `importlib.resources`,
`pkgutil` or `open`. The extension carries a CPython ABI tag on every slice, which is what
serious_python's Android packaging keys on when it relocates a module into `jniLibs`.

Eighteen wheels at build number 1: Android arm64-v8a, armeabi-v7a and x86_64 plus iOS
device, arm64-simulator and x86_64-simulator, on each of Python 3.12, 3.13 and 3.14. No
legacy 32-bit `android_24_x86` slice and no architecture excluded.

## Storage

**There is no file API, and xxhash opens nothing on its own.** The evidence is the
undefined-symbol table: outside CPython's API the Android arm64 slice imports exactly six
symbols — `malloc`, `free`, `memcpy`, `__cxa_atexit`, `__cxa_finalize`, `__register_atfork` —
and the iOS device slice seven, with `___memcpy_chk`, `___stack_chk_fail`/`_guard` and
`dyld_stub_binder` in place of the bionic three. Not one file, directory, network or
environment call at any binding. There is no cache directory to relocate and no environment
variable to set before importing.

So hashing a file is yours to write, and the incremental API is the shape for it:

```python
import os
import xxhash

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "model.bin")
digest = xxhash.xxh3_64()
with open(path, "rb") as handle:
    while chunk := handle.read(1 << 16):
        digest.update(chunk)
print(digest.hexdigest())
```

64 KiB is not an arbitrary number. Measured on desktop over 16 MiB, feeding `xxh3_64` in
4,096-byte pieces ran at 12,428 MB/s against 17,982 at 65,536 — 31% of the throughput lost
to per-call overhead — and everything from 64 KiB to 4 MiB was within 3% of each other. Do
not take the chunk size from `h.block_size`, which reports 32 for an `xxh3_64` object: the
binding returns `XXH64_BLOCKSIZE` there (`src/_xxhash.c:1302`), and XXH3's own internal
buffer is 256 bytes with a 64-byte stripe. 64 KiB is the right trade for one worker; if
several threads hash at once it is the wrong number, for the reason in
[Threading](#threading).

Where the file goes is the usual Flet split:
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for something the app owns and cannot rebuild,
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch.

**Store the digest, not the trust.** An xxhash digest beside a file tells you the bytes did
not rot; it tells you nothing about who wrote them, because anyone who can rewrite the file
can rewrite the digest, and — per the collision numbers above — can also produce a different
file with the *same* digest in milliseconds. If the file arrived over a network you do not
control, that is `hashlib.sha256` territory.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`stream-digest`](examples/stream-digest) — xxhash against `crc32`, `md5` and `sha256` on
  the same bytes at three sizes, the streaming API checked against the one-shot digest,
  upstream's published vectors recomputed, and a collision found on the device.

## Threading

**`update()` releases the GIL; the one-shot functions do not.** This is the single most
useful thing to know about running xxhash under Flet, and it is visible in three places at
once. `PyEval_SaveThread` and `PyEval_RestoreThread` are undefined symbols on all eighteen
slices. `src/_xxhash.c` wraps `Py_BEGIN_ALLOW_THREADS` around exactly four calls — the
`XXH32_update`, `XXH64_update`, `XXH3_64bits_update` and `XXH3_128bits_update` inside the
four `PYXXH*_do_update` helpers — and around nothing else, so `xxh3_64_intdigest(data)` holds
the interpreter for the whole hash.

**How much that is worth in parallel depends entirely on the chunk size, and 64 KiB is not
enough.** Four threads on a 10-core desktop, each hashing its own 64 MiB buffer with
`xxh3_64`, serial wall time divided by parallel wall time, median of eleven runs — CPython
3.14.6 first, 3.12.13 in brackets:

| fed to `update()` in | speedup |
| --- | --- |
| — (one-shot call) | 0.97× (0.99×) |
| 4 KiB | 0.18× (0.18×) |
| 64 KiB | 1.03× (1.09×) |
| 256 KiB | 2.86× (3.04×) |
| 1 MiB | 3.32× (3.46×) |
| 4 MiB | 3.29× (3.35×) |

The one-shot row is the expected result: the GIL is never dropped, so four threads take as
long as one. The 64 KiB row is the one that surprises — dropping and re-taking the GIL 1,024
times per buffer costs about what the hashing costs, so four threads still finish no sooner
than one, and at 4 KiB they take five times *longer* than doing the same work serially. Real
parallelism starts around 256 KiB and flattens by 1 MiB. Controls in the same harness:
`time.sleep` 3.97–4.04×, `hashlib.sha256` — which does release the GIL — 3.1–3.8×, a
pure-Python arithmetic loop 0.84–1.06×. So the harness sees parallelism when there is any.

**A single [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
worker is a gentler question, and there 64 KiB is fine.** It competes with an idle event
loop rather than with three other hashers, and the GIL is free for the ~3.6 µs each 64 KiB
chunk takes. The one-shot call is what blocks: it holds the interpreter for its whole
duration, measured on this desktop at 1.45 ms over 64 MiB and 6.06 ms over 256 MiB — dropped
frames on a large buffer rather than a frozen app, and proportionally worse on a phone. Use
`update()` when the input is large or arrives in pieces; do not expect it to turn
`run_thread` into four cores unless you feed it megabytes at a time.

Streaming is not free either: on desktop `xxh3_64` runs at 17,691 MB/s streamed against
47,137 one-shot (**0.38×**), because XXH3's one-shot entry point has a fast path the state
machine cannot use. `xxh64` shows no such penalty — 23,697 MB/s streamed against 24,036
one-shot, 0.99× — so if you need both parallelism and raw speed on large buffers, `xxh64` is
the algorithm that gives you both.

**There is no lock anywhere in the binding, and one incremental object must not be shared.**
`src/_xxhash.c` contains no `PyMutex`, no `PyThread_type_lock` and no critical section; it
declares `{Py_mod_gil, Py_MOD_GIL_NOT_USED}`, which is a statement about the module, not
about your object. Because `update()` drops the GIL around the C call, two threads calling
`update()` on the same `xxh3_64` really do run inside `XXH3_64bits_update` at the same time,
on the same state — an ordinary data race with no exception to catch. Measured on desktop:
two threads feeding the identical 64-piece sequence into one shared object produced **25
different digests in 25 identical runs and raised nothing**; the same loop with a
`threading.Lock` around each `update()` produced one digest 25 times. Give each thread its
own object, or hold a `threading.Lock` across the whole sequence. The module-level one-shot
functions are safe from any number of threads, because each call builds its own state.

The Flet-side rules apply as everywhere else, and the example shows both. A `run_thread`
worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads; and its body must be wrapped in `try/except`, because
`run_thread` never retrieves the worker's future and discards whatever it raised — with no
log, no dialog and no crash.

## Android notes

- **The extension links nothing but the interpreter and bionic.** `DT_NEEDED` is exactly
  `libm.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` on all nine Android slices,
  with no `SONAME`, no `RPATH`, no `RUNPATH` and no `libc++_shared` — xxHash is C, not C++,
  so none of the usual Android C++ staging applies. Every `PT_LOAD` segment carries 16 KB
  alignment, which Android 15 requires. arm64-v8a and x86_64 are `ELF64`; armeabi-v7a is a
  genuine `ELF32`/`ARM` `Thumb-2` build, not a stub. Its `Advanced_SIMD_arch` attribute reads
  `NEONv1` — which says NEON is *permitted*, not that the code uses any, and it does not; see
  the next bullet. Each slice imports 33 symbols (35 on armeabi-v7a, which additionally needs
  `memcmp` and `memset` where the 64-bit compilers inline them).
- **The two 64-bit ABIs are vectorised. armeabi-v7a is not.** Disassembling the cp314
  slices: arm64-v8a carries 104 `umlal` plus 34 `umlal2`, 34 `uzp1`/`uzp2` pairs and 34
  `shrn` — xxHash's NEON accumulator; x86_64 carries 237 `pmuludq` and 386 `paddq` and
  **zero** `ymm` operands, i.e. SSE2 and not AVX2, which is the correct baseline choice for a
  wheel that must run on any x86-64 emulator image. armeabi-v7a contains no NEON instruction
  at all: a Thumb-2 decode of its `.text` finds zero `vmlal.u32` and zero `vld1`, and 938
  scalar `umull`/`umlal`/`umaal`, identical on all three Pythons. Compiling the vendored
  `deps/xxhash/xxhash.c` for the same target with NDK r27 clang identifies which build it is,
  because the two options leave different fingerprints:

  | `umull` / `umlal` / `umaal` / `vmlal.u32` | |
  | --- | --- |
  | NDK r27 `-O3`, toolchain default | 428 / 10 / 184 / **184** |
  | NDK r27 `-O3 -mfpu=vfpv3-d16` | 482 / 282 / 174 / **0** |
  | **the published armeabi-v7a slice** | **482 / 282 / 174 / 0** |

  The shipped slice is the second one exactly. `-mfpu=vfpv3-d16` stops clang defining
  `__ARM_NEON`, `xxhash.h` then falls through its `XXH_VECTOR` ladder to `XXH_SCALAR`, and
  XXH3 runs without its accumulator on 32-bit Android. That is a flag in the cross-Python's
  `CFLAGS`, not anything in the recipe. What it costs is a device question the
  [example](examples/stream-digest) will answer.
  Beware when re-checking: the slices are stripped, so the `$a`/`$t` mapping symbols are gone
  and `objdump` decodes Thumb-2 as ARM by default — a quarter of the file then fails to
  decode and the rest invents NEON mnemonics that are not in the binary.
- **The module lands in `jniLibs` as `libxxhash-_xxhash.so`.** serious_python's Gradle step
  mangles the dotted name `xxhash._xxhash` by replacing dots with dashes
  (`mangledLib` in `serious_python_android-4.5.1/android/build.gradle.kts:161`), leaving an
  `xxhash/_xxhash.soref` marker in `sitepackages.zip`. Worth knowing because it is *not*
  `libxxhash.so` — nothing collides with a system xxHash. Read from serious_python's source,
  not from a built APK.
- **On 3.13 and 3.14 an all-ABI build can ship two different releases of this package, and
  the version it reports will be wrong on one ABI.** Per [Install](#install), a bare
  `xxhash` resolves 4.0.1 for arm64-v8a and x86_64 and 3.8.0 for armeabi-v7a. Flet then
  builds the ABI-common `sitepackages.zip` from **one** ABI's tree — `primaryAbi`, the first
  entry of `android_abis`, which is `arm64-v8a` for every Python
  (`serious_python_android-4.5.1/android/python_versions.properties`) — while each ABI keeps its
  own native library. So the armeabi-v7a device runs 3.8.0's compiled code under 4.0.1's
  Python layer. That combination imports and hashes correctly: reproduced on desktop by
  dropping 4.0.1's `__init__.py` and `version.py` onto a 3.8.0 install, it printed
  `ef46db3751d8e999` for the empty string and the two releases import the identical
  seventeen names from the extension. What it gets wrong is the version: `xxhash.VERSION`
  said `4.0.1` while `xxhash.XXHASH_VERSION` — which comes from the C — correctly said
  `0.8.2`. Pin the version if anything you do depends on `xxhash.VERSION`.

## iOS notes

- **The extensions are `MH_DYLIB`, which is what Flet 0.86 needs.** `otool -hv` reports
  filetype `DYLIB` (not `BUNDLE`) on all nine iOS slices, so the *Unsupported mach-o filetype
  (only MH_OBJECT and MH_DYLIB can be linked)* failure at app link time does not arise here.
  `otool -L` names exactly two libraries on every slice besides the extension's own install
  name: `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`. The three
  arm64-simulator slices are ad-hoc linker-signed; the other six are unsigned, as expected.
- **The file is two thirds bigger than Android's and the code is the same size.** 117,240
  bytes on the cp314 device slice against 70,312 on Android arm64-v8a — but `__text` is
  38,500 bytes against a `.text` of 39,368, so the difference is padding and link metadata,
  not code: `__TEXT` is rounded to 65,536, `__DATA_CONST` and `__DATA` to 16,384 each, plus
  18,936 of `__LINKEDIT` — which on iOS still carries the unstripped symbol table, per
  [Things to know](#things-to-know). Section contents across the whole file come to 49,509
  bytes. The x86_64 simulator slice is the smallest iOS build at 84,592 bytes.
- **Shipping a hash is not shipping a cipher.** xxhash contains no cryptography — that is the
  whole point of this page — so it does not by itself put your app into App Store Connect's
  "uses non-exempt encryption" category. Whatever else is in your app still decides that
  question, and `ITSAppUsesNonExemptEncryption` in `Info.plist` is where the answer is
  recorded.

## Things to know

- **Pick `xxh3_64` unless you have a reason not to.** Desktop throughput on the same bytes,
  best of three runs of the example's own `throughput()`, CPython 3.14.6 on an Apple M4:

  | MB/s | 1 KiB | 64 KiB | 1 MiB | 16 MiB |
  | --- | --- | --- | --- | --- |
  | xxh3_64 | 19,761 | 46,113 | 47,502 | 46,485 |
  | xxh64 | 13,317 | 24,283 | 24,102 | 24,533 |
  | xxh32 | 8,414 | 12,275 | 12,301 | 12,348 |
  | crc32 | 14,304 | 41,309 | 40,778 | 42,036 |
  | md5 | 720 | 884 | 886 | 880 |
  | sha256 | 1,864 | 3,074 | 3,008 | 3,078 |

  `xxh3_64` is roughly twice `xxh64` and four times `xxh32` at every size above 1 KiB, and
  the 64-bit digest is what you want for a cache key anyway. Read the top two rows as ratios
  rather than absolute rates: above about 10,000 MB/s the buffer is cache-resident between
  batches. The two rows that generalise least to a phone are `crc32` and `sha256`, both of
  which use CPU instructions here that a given Android device may not have — which is exactly
  why the [example](examples/stream-digest) measures them on the device rather than quoting
  these numbers. The `xxh3_64` row has its own asterisk on `armeabi-v7a`, whose slice is
  built without NEON and therefore runs XXH3's scalar path; see
  [Android notes](#android-notes).
- **`xxh32` is a permutation on four-byte inputs, so it is reversible and collision-free
  there.** Covered above with the numbers; repeated here because it is the property most
  likely to surprise. Consequences in both directions: a four-byte key hashed with `xxh32`
  can be recovered from its digest by anyone (1.0 µs on desktop), and a table keyed on
  `xxh32` of four-byte ids will never collide, which looks like excellent luck and is
  actually arithmetic. A wider digest is not a fix so much as a delay: `xxh3_64` moves the
  birthday bound to 2^32, which is far out of reach on a phone but not on a server.
- **Do not key a dict on xxhash from untrusted input.** CPython randomises `str.__hash__`
  per process precisely to make hash-flooding hard; xxhash with a fixed seed hands that back.
  One colliding `xxh32` pair costs the milliseconds measured above and the same loop run
  longer keeps producing them, and the seed is not a defence — it is an input to a public
  function, not a secret.
- **The seed is silently truncated, never rejected.** The binding reads it with
  `PyLong_AsUnsignedLongLongMask`, so `xxh64_intdigest(b"abc", 2**64)` equals
  `seed=0`, `2**64 + 7` equals `7`, `-1` equals `2**64 - 1`, and `xxh32` masks to 32 bits the
  same way — all verified on desktop, all raising nothing. A seed derived from arithmetic
  that overflows will quietly hash under a different seed than you think.
- **`digest()` is big-endian canonical, on every platform.** `xxh64_digest(x)` equals
  `xxh64_intdigest(x).to_bytes(8, "big")` and never the little-endian spelling; `xxh3_128`
  likewise puts the high 64 bits first. That is a property of the format (`XXH*_canonicalFromHash`),
  not of the CPU, so a digest written on one device reads back the same on another. **This
  page cannot prove endianness independence by running the app**: both platforms Flet targets
  are little-endian, so a matching pair of device runs confirms the vectors without testing
  the byte-order path at all. What the device run does prove is that 36 of upstream's own
  sanity vectors — 8 for XXH32, 9 for XXH64, 15 for XXH3-64 and 4 for XXH3-128, picked to
  straddle every length branch, over xxHash's own `XSUM_fillTestBuffer` stream — reproduce
  exactly; all 36 pass on desktop, checked value-for-value against
  `tests/sanity_test_vectors.h` at v0.8.2, which itself carries thousands.
- **The digest is stable across the two versions you might end up with.** 3.8.0 bundles
  libxxhash 0.8.2 and 4.0.1 bundles 0.8.3; on desktop the two produced identical digests for
  all 10 tested lengths × 4 algorithms. `xxhash.XXHASH_VERSION` reports the bundled C
  library's version and comes from the extension, while `xxhash.VERSION` comes from a `.py`
  file — see [Android notes](#android-notes) for why that distinction can matter.
- **`xxhash` accepts `str`; `hashlib` does not.** `xxhash.xxh64_hexdigest("abc")` works and
  encodes as UTF-8, where `hashlib.sha256("abc")` raises `TypeError: Strings must be encoded
  before hashing`. Convenient, and a trap when you swap one for the other — and a lone
  surrogate raises `UnicodeEncodeError` from inside what looks like a hash call. Encode
  explicitly if the code has to work with both.
- **These objects are not `hashlib` objects.** `hashlib.new("xxh64")` raises
  `ValueError: unsupported hash type xxh64` and
  `"xxh64" not in hashlib.algorithms_available`; the package keeps its own
  `xxhash.algorithms_available` set. The instance attributes are close enough to fool a duck
  type — `name` (`XXH32`, `XXH64`, `XXH3_64`, `XXH3_128`), `digest_size` (4, 8, 8, 16),
  `block_size`, `update`, `digest`, `hexdigest`, `copy` — plus `intdigest`, `reset` and
  `seed`, which `hashlib` has none of. `block_size` is the one that lies; see
  [Storage](#storage).
- **`digest()` does not finalise anything.** You can keep calling `update()` after reading a
  digest, and `copy()` forks the state so a common prefix is hashed once — verified on
  desktop: a copy taken after `update(b"prefix")` and continued with `b"-B"` equals
  `xxh3_64_hexdigest(b"prefix-B")`. `reset()` returns the object to the empty-input digest.
- **Chunking never changes the answer.** The same 3 MB buffer fed in pieces of 1, 7, 4096,
  65536 and 1,000,000 bytes gave the same `xxh3_64` digest as the one-shot call, five for
  five on desktop.
- **Size: 32–54 KB to download per slice, 90–137 KB unpacked, and 78–85% of that is the
  extension.** The Python half is 1,147 bytes of `__init__.py` plus a 101-byte `version.py`,
  byte-identical across all eighteen wheels; the `.pyi` stub and `py.typed` never reach the
  device, since serious_python's `junkFilesMobile` deletes `**.pyi` and `**.typed` and
  `flet build` passes `--cleanup-packages` by default. The nine Android slices are stripped —
  no `.symtab`, no `.debug_*` — but the nine iOS ones are not: each keeps an `LC_SYMTAB` of
  751 entries (757 on the x86_64 simulator), 550 of them stabs debug-map records, worth about
  16 KB of the device slice's 18,936-byte `__LINKEDIT`. `strip -x` takes that file from
  117,240 bytes to 103,856. The armeabi-v7a wheel is the outlier at 53–54 KB against 32–35
  for the rest, entirely because its Thumb-2 code deflates to 0.62 of its size where arm64
  reaches 0.38 and the iOS device slice 0.20; unpacked, the v7a extension is within 5% of
  arm64's.
- **The wheel exports the whole libxxhash C API.** 49 `XXH*` symbols are globally visible on
  every one of the eighteen slices — `XXH3_generateSecret`, `XXH128_cmp`,
  `XXH64_canonicalFromHash` and the rest — alongside `PyInit__xxhash`, because upstream
  compiles `deps/xxhash/xxhash.c` straight into the extension with default visibility. It
  costs nothing and nothing on the Python side reaches them; it is worth knowing only if you
  ever wonder whether a second extension could link against this one.
- **Python 3.14 does not make this redundant.** Nothing in the standard library offers XXH3;
  the stdlib non-cryptographic options remain `zlib.crc32` and `zlib.adler32`, and `hashlib`
  is cryptographic hashes only.

## Build notes (maintainers)

The recipe is `meta.yaml` and nothing else: a name, a version, a build number, no patches, no
`build.sh`, no `requirements`, no `script_env`, no `excluded_arches`. That shape is earned
rather than lucky — upstream's `setup.py` declares one `Extension` from
`src/_xxhash.c` plus the vendored `deps/xxhash/xxhash.c`, with no `define_macros`, no
`libraries` and no platform branches; the only conditional is an `XXHASH_LINK_SO` environment
variable that would link a system libxxhash instead, which we do not set. There is nothing
for a cross build to get wrong, so a bump that suddenly needs a patch means upstream
restructured, not that the toolchain drifted.

Two observations from the published wheels that are not recorded anywhere else:

- **The 3.12 Android slices name the extension `_xxhash.cpython-312.so`, without the platform
  triplet, while 3.13 and 3.14 use the full `_xxhash.cpython-31X-<triplet>.so`.** Both
  spellings match the `\.(cpython-[^/]+|abi3)\.so$` tag serious_python's `jniLibs` relocation
  keys on, so both work, but the untripleted form means forge's foreign-arch drop cannot
  distinguish the three 3.12 Android slices from each other by filename. Currently harmless —
  the `e_machine` of each was checked and every slice is the right architecture — but it is
  the first thing to look at if a 3.12 Android wheel ever imports on one ABI and not another.
- **The iOS extensions are `MH_DYLIB` already**, on all nine slices, so this recipe is not
  exposed to the `Unsupported mach-o filetype` breakage that hit CMake-built recipes published
  before forge's `MH_BUNDLE → MH_DYLIB` converter landed. setuptools produces a dylib on iOS
  on its own; nothing in the recipe arranges it.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **Whether this recipe is still needed at all.** Upstream started publishing its own iOS and
  Android wheels — 4.0.1 covers cp313/cp314/cp315 for arm64-v8a, x86_64 and all three iOS
  slices — and what is left for us is `armeabi-v7a` and Python 3.12. Check both before
  bumping: the day upstream adds a 32-bit ABI, and the day Flet drops 3.12, this recipe stops
  earning its place. Until then, note that bumping *to* a version upstream also publishes
  makes this index's wheel win the tie on the build tag alone, which is a shadowing decision
  worth making deliberately rather than by default.
- **The GIL split**, since [Threading](#threading) rests on it: `Py_BEGIN_ALLOW_THREADS`
  around the four `*_update` calls and nowhere else, and the parallel-speedup sweep that
  confirms it. Re-measure that sweep across chunk sizes, not at one size — the whole point
  of the table is that 64 KiB and 1 MiB give different answers (1.03× against 3.32×), so a
  single-size re-check can confirm whichever conclusion you went looking for. Upstream
  extending the release to the one-shot functions would invert the section's advice, and
  would be an improvement worth documenting rather than a regression.
- **That `METADATA` still has zero `Requires-Dist` lines**, and that no `.py` in the package
  has acquired a `__file__` read. Either would falsify [Install](#install) without failing
  anything.
- **The extension filenames**, per slice: they must keep a CPython ABI tag, since an untagged
  `NAME.so` gets no `.soref`, is not relocated into `jniLibs`, and becomes a silent
  `ModuleNotFoundError` on device. Match the `_xxhash.cpython-` prefix, not an exact suffix.
- **The linkage**, per slice: `DT_NEEDED` still four bionic and interpreter entries with no
  `libc++_shared`, 16 KB `PT_LOAD` alignment on all three Android ABIs, `MH_DYLIB` on all
  three iOS ones.
- **The vectorisation on the two 64-bit ABIs**, which is most of the performance story:
  `umlal`/`uzp1` on arm64-v8a, `pmuludq`/`paddq` on x86_64. A toolchain change that dropped
  either to the scalar path would build green, pass every test, and quietly cost most of the
  speed this page is about. armeabi-v7a already ships scalar (see
  [Android notes](#android-notes)); if that is ever worth fixing, the lever is the FPU
  setting in the cross-Python's `CFLAGS`, not the recipe — NDK clang defines `__ARM_NEON` for
  `armv7a-linux-androideabi24` on its own, and only `-mfpu=vfpv3-d16` or similar takes it
  away. Decode Thumb-2 with an explicit `--triple=thumbv7a-…` anchored on a symbol address;
  a stripped slice has no `$a`/`$t` markers and the default decode reports NEON that is not
  in the file.

`tests/test_xxhash.py` is a single `test_basic` covering one XXH64 vector, a streaming round
trip against the one-shot call, and the type of `xxhash.VERSION`. Its last line carries a
comment that is wrong and worth fixing while you are there: it calls `xxhash.VERSION` the
"bundled libxxhash version", which is `xxhash.XXHASH_VERSION` — the distinction that
[Android notes](#android-notes) shows can matter on a real device. Additions worth making at
the next touch, in rough order of value: **the published sanity vectors**, since
they are the only check that proves this build agrees with xxHash everywhere else and the
[example](examples/stream-digest) currently carries all 36 of them where a test should;
`xxh64_digest(x) == xxh64_intdigest(x).to_bytes(8, "big")`, which pins the canonical byte
order claimed in [Things to know](#things-to-know) to the shipped binary; and an `xxh3_128`
call, since nothing on device touches the 128-bit path today. The GIL behaviour is
deliberately not on that list: a thread-timing assertion is a poor fit for a CI test that
must never flake.
