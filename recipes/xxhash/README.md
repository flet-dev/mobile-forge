# xxhash

[`xxhash`](https://github.com/ifduyue/python-xxhash) is the Python binding for
[xxHash](https://github.com/Cyan4973/xxHash), a family of non-cryptographic hash functions that
run at memory speed. Four algorithms — `xxh32`, `xxh64`, `xxh3_64` and `xxh3_128` (also spelled
`xxh128`) — each come as
[a one-shot function and an incremental object](https://github.com/ifduyue/python-xxhash#usage)
with `update`, `digest`, `copy` and `reset`. On a phone you want it for cache keys,
deduplication, content fingerprints, shard selection and "did this download arrive intact" —
the cases where hashing megabytes must not cost you a frame.

**It is not a checksum against tampering and it is not a substitute for a cryptographic hash.**
A 32-bit digest is milliseconds from a collision on the device itself, and a four-byte input
can be recovered from its `xxh32` digest by arithmetic; both are measured in
[Things to know](#things-to-know). Reach for xxhash where the other party is a disk or a
network, never where it might be an adversary.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "xxhash",
]
```

The entry belongs in top-level `[project] dependencies` and not in a `[tool.flet.<platform>]`
table: `flet build` resolves for the build host first, and PyPI has a desktop wheel for every
host you would build from, so `flet run` on your laptop gets the same API you ship.

**Unlike most packages on this index, upstream publishes mobile wheels of its own — and by
default your app gets those instead.** Which wheel you land on depends on the Python version
and, on Android, on the ABI:

| a bare `xxhash` resolves | 3.12 | 3.13 | 3.14 |
| --- | --- | --- | --- |
| android arm64-v8a | this index | **PyPI** | **PyPI** |
| android x86_64 | this index | **PyPI** | **PyPI** |
| android armeabi-v7a | this index | this index | this index |
| iOS device / both simulators | this index | **PyPI** | **PyPI** |

Upstream's mobile wheels start at cp313 and never include `armeabi-v7a`; those two holes are
what this recipe fills. The consequence is not hypothetical: serious_python runs pip **once per
Android ABI**, so on 3.13 or 3.14 an all-ABI build genuinely resolves a different release for
the 32-bit ABI than for the other two. Two ways to make it uniform:

- **Pin the version.** `"xxhash==3.8.0"` puts every slice on this index's wheels, verified for
  every Python and platform tag, which is what
  [`stream-digest`](examples/stream-digest) does.
- **Drop the 32-bit ABI**, if you were going to anyway. `["arm64-v8a", "x86_64"]` in
  [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) leaves
  nothing for this index to fill on 3.13 and 3.14, and a bare `xxhash` then resolves upstream
  everywhere. It is also the one ABI whose slice is built without NEON, so it is the slice
  least likely to show you the speed this page is about.

Do neither and the digests still agree — the releases involved bundle libxxhash 0.8.x and the
algorithms are frozen — but the version the app reports on one ABI will be wrong; see
[Version skew across Android ABIs](#version-skew-across-android-abis).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`stream-digest`](examples/stream-digest) — measures xxhash against `crc32`, `md5` and
  `sha256` on the device's own CPU, then breaks `xxh32` twice on screen.

## Usage in a Flet app

Two calls do the job, and the result is a short hex string you can put straight on screen:

```python
import flet as ft
import xxhash

key = xxhash.xxh3_64_hexdigest(payload)          # bytes or str, 16 hex characters
changed = key != stored_key

page.add(ft.Text(f"{key} — {'changed' if changed else 'unchanged'}"))
```

### Storage

**xxhash opens nothing.** Every function is bytes in, digest out: there is no cache directory
to relocate, no file to ship beside the wheel, and no environment variable to set before
importing. Hashing a file is therefore yours to write, and the incremental API is the shape
for it:

```python
import os
import xxhash

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "model.bin")
digest = xxhash.xxh3_64()
with open(path, "rb") as handle:
    while chunk := handle.read(1 << 16):
        digest.update(chunk)
status.value = digest.hexdigest()
```

64 KiB is not an arbitrary read size. Measured on a desktop over 16 MB, feeding `xxh3_64` in
4 KB pieces ran at 12,428 MB/s against 17,982 at 64 KB — a third of the throughput lost to
per-call overhead — while everything from 64 KB to 4 MB landed within 3% of each other. **Do
not take the chunk size from `h.block_size`**, which reports 32 for an `xxh3_64` object: the
binding returns XXH64's block size there, and XXH3's own buffer is 256 bytes with a 64-byte
stripe. 64 KiB is the right trade for one worker; several threads hashing at once want a far
bigger chunk, for the reason in [Threading](#threading).

The file itself goes where any Flet app file goes:
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for something the app owns and cannot rebuild,
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch.

**Store the digest, not the trust.** A digest written beside a file tells you the bytes did not
rot. It tells you nothing about who wrote them: anyone who can rewrite the file can rewrite the
digest, and can also produce a *different* file with the same digest in milliseconds. If the
file arrived over a network you do not control, that is
[`hashlib.sha256`](https://docs.python.org/3/library/hashlib.html#hashlib.sha256) territory.

### Threading

**`update()` releases the GIL; the one-shot functions do not.** The binding drops the
interpreter around the four `XXH*_update` calls and around nothing else, so
`xxh3_64_intdigest(data)` holds it for the whole hash — measured on a desktop at 1.4 ms over
64 MB and 6.1 ms over 256 MB, which is dropped frames on a large buffer rather than a frozen
app, and proportionally worse on a phone.

A single [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
worker feeding `update()` in 64 KiB chunks is the shape that works: it competes with an idle
event loop, and the GIL is free for the few microseconds each chunk takes.

**Do not expect that to turn into parallelism across several threads without a much bigger
chunk.** Four threads on a ten-core desktop, each hashing its own 64 MB buffer with `xxh3_64`,
serial wall time divided by parallel wall time, median of eleven runs:

| fed to `update()` in | speedup |
| --- | --- |
| — (one-shot call) | 0.97× |
| 4 KB | 0.18× |
| 64 KB | 1.03× |
| 256 KB | 2.86× |
| 1 MB | 3.32× |
| 4 MB | 3.29× |

The one-shot row is the expected result: the GIL never drops, so four threads take as long as
one. The 64 KB row is the one that surprises — dropping and re-taking the GIL a thousand times
per buffer costs about what the hashing costs — and at 4 KB four threads take five times
*longer* than doing the same work serially. Real parallelism starts around 256 KB.

Streaming is not free either, and the two algorithms differ: on the same desktop `xxh3_64` ran
at 17,691 MB/s streamed against 47,137 one-shot (**0.38×**), because XXH3's one-shot entry
point has a fast path the state machine cannot use, while `xxh64` showed no penalty at all
(23,697 against 24,036). If you need both parallelism and raw speed on large buffers, `xxh64`
is the algorithm that gives you both.

**One incremental object must not be shared between threads.** There is no lock in this
version of the binding, and because `update()` drops the GIL, two threads calling it on the
same object really do run inside the C update at the same time on the same state — an ordinary
data race with no exception to catch. Measured: two threads feeding an identical sequence into
one shared object produced **25 different digests in 25 identical runs and raised nothing**;
the same loop with a
[`threading.Lock`](https://docs.python.org/3/library/threading.html#threading.Lock) around each
`update()` produced one digest 25 times. Give each thread its own object, or hold the lock
across the whole sequence. The module-level one-shot functions are safe from any number of
threads, because each call builds its own state.

The Flet-side rules apply as everywhere else. A `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads, and its body must be wrapped in `try`/`except`, because
`run_thread` never retrieves the worker's future and discards whatever it raised — no log, no
dialog, no crash, just a screen that stopped updating.

### Choosing an algorithm

**Pick `xxh3_64` unless you have a reason not to.** Desktop throughput on the same bytes,
CPython 3.14.6 on an Apple M4, best of three runs of the example's own harness:

| MB/s | 1 KB | 64 KB | 1 MB | 16 MB |
| --- | --- | --- | --- | --- |
| xxh3_64 | 19,761 | 46,113 | 47,502 | 46,485 |
| xxh64 | 13,317 | 24,283 | 24,102 | 24,533 |
| xxh32 | 8,414 | 12,275 | 12,301 | 12,348 |
| crc32 | 14,304 | 41,309 | 40,778 | 42,036 |
| md5 | 720 | 884 | 886 | 880 |
| sha256 | 1,864 | 3,074 | 3,008 | 3,078 |

`xxh3_64` is roughly twice `xxh64` and four times `xxh32` above 1 KB, and a 64-bit digest is
what you want for a cache key anyway. Read the top rows as ratios rather than absolute rates:
above about 10,000 MB/s the buffer is cache-resident between batches.

**The ratio against a cryptographic hash does not travel, even though the throughput roughly
does.** Over a 1 MB buffer on 2026-08-20, both at CPython 3.14.6: an iPhone 16 simulator gave
`xxh3_64` 47,328 MB/s against `sha256`'s 590, an 80× win, and Android 14 on an arm64-v8a
emulator gave 16,554 against **17**, which reads as 999×. That second figure is an artefact and
should not be quoted — `sha256` at 17 MB/s is what a CPU *without* the ARMv8 SHA-2 extensions
looks like, and the emulator image does not expose them. Every arm64 phone worth shipping to
has them. The honest summary is the shape iOS shows: about one order of magnitude faster than
SHA-256, and roughly level with
[`zlib.crc32`](https://docs.python.org/3/library/zlib.html#zlib.crc32) (1.09× on iOS, 1.28× on
Android). Take xxhash for the win over
[`hashlib.md5`](https://docs.python.org/3/library/hashlib.html#hashlib.md5), never for the
`sha256` comparison alone — and if `crc32` already fits your problem, the gap is not the reason
to switch.

Streaming behaves the same on device as on desktop: 1 MB fed in 64 KiB updates matched the
one-shot digest exactly on both platforms, at 18,340 MB/s against 47,958 one-shot on iOS and
9,472 against 14,410 on Android.

When the other party might be hostile, the standard library already has the answer and it is
fast enough to measure rather than assume: `hashlib.sha256` or
[`hashlib.blake2b`](https://docs.python.org/3/library/hashlib.html#hashlib.blake2b) for
integrity, [`hmac.new(key, msg, hashlib.sha256)`](https://docs.python.org/3/library/hmac.html#hmac.new)
or `hashlib.blake2b(msg, key=...)` for authentication, and
[`hashlib.scrypt`](https://docs.python.org/3/library/hashlib.html#hashlib.scrypt) for passwords.

### Version skew across Android ABIs

On 3.13 and 3.14 an all-ABI build ships two different releases of this package, per
[Install](#install) — and **the version the app reports will be wrong on one ABI**. Flet builds
the ABI-common `sitepackages.zip` from a single ABI's tree, the first entry of `android_abis`,
which is `arm64-v8a` for every Python, while each ABI keeps its own native library. So the
`armeabi-v7a` device runs one release's compiled code under the other release's Python layer.

That combination imports and hashes correctly — reproduced on a desktop by crossing the two
layers, it produced the documented empty-string digests and imported the identical set of names
from the extension. What it gets wrong is the version: `xxhash.VERSION` reported the Python
layer's release while `xxhash.XXHASH_VERSION`, which comes from the C, correctly reported the
bundled libxxhash. Pin the version if anything you do depends on `xxhash.VERSION`.

### App size

Expect roughly 30–55 KB of compressed wheel per slice, unpacking to 90–140 KB, around 80% of
which is the compiled extension. That is small enough that the Android levers — an app bundle,
split APKs, or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) — will
be earning their keep on some other dependency rather than on this one. Flet's default
[cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) already drops the type stub
and the `py.typed` marker before the wheel reaches the device.

The `armeabi-v7a` slice is the outlier at the top of the compressed range, purely because its
32-bit code compresses worse; unpacked it is within 5% of arm64's. Figures are decimal KB, as a
package index reports them, so re-measure with `ls -l` rather than `du -h`.

### Other considerations

**A desktop `flet run` and a device build can be running different releases of xxhash.** On
your laptop, `flet run` resolves whatever PyPI's newest desktop wheel is; on device, several
slices resolve this index's instead, and the two are not the same release unless you pinned.
The digests match either way, so anything you can check by comparing hex strings will look
identical — but the Python layer around them differs, and that is where the attributes live.
Validate on a device or emulator/simulator anything that reads `xxhash.VERSION`,
`xxhash.VERSION_TUPLE` or the contents of `xxhash.algorithms_available`.

## Things to know

- **`xxh32` is a permutation on four-byte inputs, so it is reversible and collision-free
  there.** Every step XXH32 takes on a four-byte input is a bijection on 32 bits, so the
  function can be run backwards with arithmetic instead of search: 2,000 of 2,000 four-byte
  inputs were recovered byte-exact from their digest alone in 2 ms on a desktop, and 1,999,512
  distinct four-byte inputs produced 1,999,512 distinct digests where a uniform random hash
  would have collided about 465 times. Consequences run in both directions — a four-byte key
  hashed with `xxh32` can be recovered by anyone, and a table keyed on `xxh32` of four-byte ids
  will never collide, which looks like excellent luck and is actually arithmetic. A seed does
  not fix this; a seed is a parameter, not a key.

- **A wider digest is a delay, not a fix.** A seeded birthday search found two 32-byte inputs
  sharing an `xxh32` digest after 113,202, 39,741 and 16,915 tries for seeds 0, 1 and 2 — 21, 7
  and 3 milliseconds on a desktop, and the example does the same search on the phone. A 32-bit
  digest is 2^16 tries from a collision and no amount of speed changes that. `xxh3_64` moves
  the bound to 2^32, which is out of reach on a phone but not on a server.

- **Do not key a dict on xxhash from untrusted input.** CPython randomises `str.__hash__` per
  process precisely to make hash-flooding hard, and hashing with a fixed seed hands that back.
  One colliding `xxh32` pair costs the milliseconds above, and the same loop run longer keeps
  producing them.

- **The seed is silently truncated, never rejected.** The binding masks it, so
  `xxh64_intdigest(b"abc", 2**64)` equals `seed=0`, `2**64 + 7` equals `7` and `-1` equals
  `2**64 - 1`; `xxh32` masks to 32 bits the same way. All of them raise nothing — upstream's
  own [caveat](https://github.com/ifduyue/python-xxhash#seed-overflow) is to keep the seed in
  range. A seed derived from arithmetic that overflows will quietly hash under a different seed
  than you think.

- **`digest()` is big-endian canonical on every platform.** `xxh64_digest(x)` equals
  `xxh64_intdigest(x).to_bytes(8, "big")` and never the little-endian spelling, and `xxh3_128`
  puts the high 64 bits first. That is a property of the
  [format](https://github.com/ifduyue/python-xxhash#endianness), not of the CPU, so a digest
  written on one device reads back the same on another. Both platforms Flet targets are
  little-endian, so no device run can demonstrate the byte-order path — what a device run does
  prove is that upstream's published sanity vectors reproduce exactly, which is the check that
  says this build agrees with xxHash everywhere else.

- **`xxhash` accepts `str`; `hashlib` does not.** `xxhash.xxh64_hexdigest("abc")` works and
  encodes as UTF-8, where `hashlib.sha256("abc")` raises `TypeError: Strings must be encoded
  before hashing`. Convenient, and a trap when you swap one for the other — and a lone
  surrogate raises `UnicodeEncodeError` from inside what looks like a hash call. Encode
  explicitly if the code has to work with both.

- **These are not `hashlib` objects.**
  [`hashlib.new("xxh64")`](https://docs.python.org/3/library/hashlib.html#hashlib.new) raises
  `ValueError: unsupported hash type xxh64` and `"xxh64"` is not in
  [`hashlib.algorithms_available`](https://docs.python.org/3/library/hashlib.html#hashlib.algorithms_available);
  the package keeps its own `xxhash.algorithms_available` set. The instance attributes are close
  enough to fool a duck type — `name`, `digest_size`, `block_size`, `update`, `digest`,
  `hexdigest`, `copy` — plus `intdigest`, `reset` and `seed`, which `hashlib` has none of.
  `block_size` is the one that lies; see [Storage](#storage).

- **`digest()` does not finalise anything.** You can keep calling `update()` after reading a
  digest, and `copy()` forks the state so a common prefix is hashed once: a copy taken after
  `update(b"prefix")` and continued with `b"-B"` equals `xxh3_64_hexdigest(b"prefix-B")`.
  `reset()` returns the object to the empty-input digest.

- **Chunking never changes the answer.** The same 3 MB buffer fed in pieces of 1, 7, 4096,
  65,536 and 1,000,000 bytes gave the same `xxh3_64` digest as the one-shot call, five for
  five.

- **Python 3.14 does not make this redundant.** Nothing in the standard library offers XXH3;
  the non-cryptographic options remain `zlib.crc32` and
  [`zlib.adler32`](https://docs.python.org/3/library/zlib.html#zlib.adler32), and `hashlib` is
  cryptographic hashes only.

## Build notes (maintainers)

### Recipe shape

The recipe is a `meta.yaml` and nothing else: a name, a version and a build number, with no
patches, no `build.sh`, no requirements and no excluded architectures. That shape is earned
rather than lucky. Upstream's `setup.py` declares one `Extension` from `src/_xxhash.c` plus the
vendored `deps/xxhash/xxhash.c`, with no `define_macros`, no `libraries` and no platform
branches; the only conditional is an `XXHASH_LINK_SO` environment variable that would link a
system libxxhash instead, which forge does not set. There is nothing for a cross build to get
wrong, so a bump that suddenly needs a patch means upstream restructured, not that the
toolchain drifted.

Two things read out of the published wheels that are recorded nowhere else:

- **The 3.12 Android slices name the extension `_xxhash.cpython-312.so`, without the platform
  triplet, while 3.13 and 3.14 use the full `_xxhash.cpython-31X-<triplet>.so`.** Both spellings
  match the tag serious_python's `jniLibs` relocation keys on, so both work — but the
  untripleted form means forge's foreign-arch drop cannot tell the three 3.12 Android slices
  apart by filename. Currently harmless, since each slice's `e_machine` was checked and is
  right, but it is the first thing to look at if a 3.12 Android wheel ever imports on one ABI
  and not another.
- **The iOS extensions are `MH_DYLIB` already**, on all nine slices, so this recipe is not
  exposed to the `Unsupported mach-o filetype` breakage that hit CMake-built recipes before
  forge's `MH_BUNDLE → MH_DYLIB` converter landed. setuptools produces a dylib on iOS on its
  own; nothing in the recipe arranges it.

### Upgrade hazards

**[Install](#install) names a pin in prose, and it is the recipe's own version.** Bumping the
recipe without editing that line leaves consumers pinning a release this index no longer builds,
which fails to resolve rather than degrading quietly — but it fails in *their* build, not ours.
The example's `pyproject.toml` carries the same version and must move with it.

**Whether this recipe is still needed at all.** Upstream now publishes its own iOS and Android
wheels, and what is left for us is `armeabi-v7a` and Python 3.12. Check both before bumping:
the day upstream adds a 32-bit ABI, and the day Flet drops 3.12, this recipe stops earning its
place. Until then, note that bumping *to* a version upstream also publishes makes this index's
wheel win the tie on its build tag alone, which is a shadowing decision worth making
deliberately rather than by default.

**The 4.x series adds a per-object lock and rewrites [Threading](#threading) from the ground
up.** Upstream's current README documents streaming hash objects as thread-safe, serialised by
a per-object lock that is always active on Python 3.13+ and created lazily below it, with
updates of 64 KB or less never releasing the GIL at all. Every load-bearing claim in that
section — the shared-object race, the chunk-size speedup table, the advice to give each thread
its own object — is a statement about the version this recipe currently builds, and a bump
across that boundary is a documentation pass, not a version change. The 3.x README has no
thread-safety section at all, which is the quickest way to tell which regime a tag is in.

**The GIL split itself**, which the same section rests on: `Py_BEGIN_ALLOW_THREADS` around the
four `*_update` calls and nowhere else. Re-measure the parallel sweep across chunk sizes, not
at one size — the point of that table is that 64 KB and 1 MB give different answers (1.03×
against 3.32×), so a single-size re-check will confirm whichever conclusion you went looking
for.

**The vectorisation on the two 64-bit ABIs**, which is most of the performance story:
`umlal`/`uzp1` on arm64-v8a, `pmuludq`/`paddq` on x86_64. A toolchain change that dropped
either to the scalar path would build green, pass every test, and quietly cost most of the
speed this page is about. `armeabi-v7a` already ships scalar — the cross-Python's `CFLAGS`
carry an FPU setting that stops clang defining `__ARM_NEON`, so `xxhash.h` falls through its
`XXH_VECTOR` ladder to `XXH_SCALAR`; the lever is in the Python build, not in this recipe.
Decode Thumb-2 with an explicit `--triple=thumbv7a-…` anchored on a symbol address: the slices
are stripped, so there are no `$a`/`$t` markers and the default decode reports NEON that is not
in the file.

### Re-verification checklist

- **The resolution table in [Install](#install).** Re-derive it rather than assuming, with one
  `pip download --only-binary :all: --python-version … --platform … --extra-index-url
  https://pypi.flet.dev xxhash` per Python and platform tag — PyPI first, this index as the
  extra, which is how serious_python invokes pip. Upstream publishing one more mobile slice
  changes which column reads *this index*, and nothing here would fail.
- **That `METADATA` still declares no dependency**, and that no `.py` in the package has
  acquired a `__file__`, `importlib.resources`, `pkgutil` or `open` read. Either would falsify
  [Install](#install) and [Storage](#storage) without failing anything. The package payload
  should stay at ten files per wheel — one extension, `__init__.py`, `version.py`, the stub,
  `py.typed` and five `dist-info` entries — with no data file of any kind.
- **Coverage of the slices `flet build` asks for**: Android arm64-v8a, armeabi-v7a and x86_64
  plus iOS device, arm64-simulator and x86_64-simulator, on every Python built. Eighteen wheels
  at the current three minors. A gap in any of the six is a consumer-visible hole.
- **The extension filenames**, per slice: they must keep a CPython ABI tag, since an untagged
  `NAME.so` gets no `.soref`, is not relocated into `jniLibs`, and becomes a silent
  `ModuleNotFoundError` on device. Match the `_xxhash.cpython-` prefix, not an exact suffix.
- **The linkage**, per slice: Android `DT_NEEDED` exactly `libm.so`, `libpython3.<minor>.so`,
  `libdl.so` and `libc.so`, with no `SONAME`, `RPATH`, `RUNPATH` or `libc++_shared` — the
  sources are C, so none of the Android C++ staging applies — and 16 KB `PT_LOAD` alignment on
  all three ABIs for Android 15. On iOS, `otool -hv` must report `DYLIB` and not `BUNDLE`, with
  `otool -L` adding only `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`.
- **The "opens nothing" claim behind [Storage](#storage).** Dump the undefined symbols and
  confirm no file, directory, network or environment call at any binding. Everything outside
  CPython's own API was six libc symbols on Android arm64 and seven on the iOS device slice.
- **Size**, re-measured from the built wheels rather than scaled. [App size](#app-size) quotes
  decimal KB; `du -h` reports binary units and will read a 100 KB payload as 98 K.
- **The published sanity vectors**, which are the only check that this build agrees with xxHash
  on any other CPU, and the empty-string digests `xxh64` `ef46db3751d8e999` and `xxh3_64`
  `2d06800538d394c2` that the tests and the example both print.

### Coverage gaps

The device test is a single `test_basic`: one XXH64 vector, a streaming round trip against the
one-shot call, and a type check on `xxhash.VERSION`. It never touches `xxh3_128`, never pins
the canonical byte order claimed in [Things to know](#things-to-know), and carries the
published sanity vectors nowhere — those live in the
[example](examples/stream-digest) instead, where a test should have them. Its last line also
comments `xxhash.VERSION` as the "bundled libxxhash version", which is `xxhash.XXHASH_VERSION`;
that is exactly the distinction [Version skew across Android ABIs](#version-skew-across-android-abis)
turns on, so the comment is worth fixing at the next touch.

Nothing on device measures the GIL behaviour, and that is deliberate: a thread-timing assertion
is a poor fit for a CI test that must never flake. Everything under [Threading](#threading) is
therefore a desktop figure, as is the algorithm table in
[Choosing an algorithm](#choosing-an-algorithm) and the chunk-size sweep in
[Storage](#storage). The only measurements with a device behind them are the per-platform
throughput and streaming rates, and that device was an emulator and a simulator rather than a
phone — which is exactly how the `sha256` artefact recorded there arose. Running the
[example](examples/stream-digest) on real hardware is the missing evidence for all of it.
