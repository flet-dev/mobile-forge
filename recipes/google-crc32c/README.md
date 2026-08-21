# google-crc32c

[`google-crc32c`](https://github.com/googleapis/google-cloud-python/tree/main/packages/google-crc32c)
wraps Google's [CRC32C](https://github.com/google/crc32c) C library. CRC32C is the
Castagnoli-polynomial 32-bit checksum that Google Cloud Storage, Ceph and iSCSI use to tell
whether a blob arrived, or came back off disk, exactly as it went in. In a Flet app it lets you
decide on the device whether a downloaded file, a cached image or a database you just wrote is
still the bytes you meant — cheaply enough to check on every read.

Import the package as `google_crc32c`.

## Install

Add it to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "google-crc32c",
]
```

`value()`, `extend()` and `Checksum.update()` take `bytes`. The extension parses that argument
with CPython's `y#` format, which turns down any type whose buffer it would have to release
afterwards — so a `bytearray`, an `array.array`, an `mmap`, and a `memoryview` even after
`.toreadonly()`, all raise a `TypeError` saying `must be read-only bytes-like object`, naming
the type you passed. Convert with `bytes(buffer)` and accept the copy, or read the source as
`bytes` in the first place.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`integrity-check`](examples/integrity-check) — stores an 8 MB blob under a per-chunk CRC32C
  manifest, flips one bit in it, and finds the damaged chunk.

## Usage in a Flet app

Checksum the bytes you have, and compare against the checksum you were promised:

```python
import google_crc32c

crc = google_crc32c.value(payload)            # int
if crc != expected:
    banner.value = "download is damaged"
```

The `Checksum` object is the hashlib-shaped form for data that arrives in pieces:

```python
running = google_crc32c.Checksum()
running.update(first)
running.update(second)
crc = int.from_bytes(running.digest(), "big")
```

### Storage

A checksum and the thing it describes are two files you place yourself. Put both in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which survives restarts, and read the file with `Checksum.consume(stream, chunksize)` — it
yields each chunk as it folds it into the running value, which is the moment to record a
per-chunk checksum too:

```python
data_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
running = google_crc32c.Checksum()
with open(os.path.join(data_dir, "vault.bin"), "rb") as blob:
    per_chunk = [google_crc32c.value(c) for c in running.consume(blob, 1_000_000)]
```

One whole-file value tells you that a file is damaged. A per-chunk list tells you *where*, which
is the difference between re-fetching a gigabyte and re-fetching a megabyte.

From Flet 0.86.0 that directory is also the process working directory, so a relative path lands
there; naming the variable still makes the intent obvious.
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
suits a checksum over something you can regenerate, and a file shipped with the app belongs in
the [assets directory](https://flet.dev/docs/cookbook/assets), reachable through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

### Threading

**The extension holds the GIL for the whole call.** It has no `Py_BEGIN_ALLOW_THREADS`, and no
built slice imports a GIL-releasing symbol, so a single `value()` over a large buffer stops every
other Python thread — including Flet's — until it returns. Measured on desktop macOS/arm64
against a second thread doing nothing but sampling the clock: one call over 512 MiB ran 93 ms and
starved that thread for 86 ms of them. The same bytes through `Checksum.update` in 1 MiB chunks
held the worst stall to 8 ms. `hashlib.sha256` over that buffer took longer overall, 183 ms, and
never stalled the other thread past a millisecond, because it does release the GIL.

Chunking is not a speed-up: with nothing else running the whole buffer goes through in 83 ms and
1 MiB at a time takes 93 ms, the extra being the slice copies. What it buys is that the other
thread gets to run at all, which is why the chunked job stretched to 163 ms while the sampler
kept going. That is the trade you want under a
UI — but do not chase the remaining 8 ms with a smaller chunk. At 64 KiB and at 4 KiB the worst
stall was still 8 ms, and it fell under 2 ms only after lowering `sys.setswitchinterval`:
the floor is CPython's 5 ms thread-switch interval, not this package. A 1 MiB call takes about
0.2 ms, already far below it, so shrinking further buys nothing and costs per-call overhead —
4 KiB chunks made the same work 14% slower. Hand the loop to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) so a slow
disk does not block the UI either, catch exceptions inside the worker because `run_thread`
swallows them, and end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Hardware path

CRC32C has a dedicated CPU instruction — `crc32c*` on ARMv8, `crc32` on SSE4.2 — and the library
picks between that and a table-driven fallback the first time you call it. Which paths are even
available was fixed when the wheel was built, and it is not the same everywhere:

| Slice | Compiled paths |
| --- | --- |
| Android `arm64-v8a` | ARMv8 instruction and table |
| Android `x86_64` | SSE4.2 instruction and table |
| Android `armeabi-v7a` | table only |
| iOS device and simulator | instruction and table |

ARMv7 has no CRC32 instruction at all, so Android's one 32-bit target runs the table on every
device. Nothing in the API reports which path was taken, so the way to tell is to measure:
checksum a few megabytes and look at the rate. For the size of
the gap, a native build of the same library on desktop macOS/arm64 put 256 MiB through the
instruction path at about 32 GB/s and the table at about 6 GB/s — absolute rates on a phone are
lower, but the ratio is the thing. The consequence is a build setting, not a code change: if
throughput matters, drop `armeabi-v7a` from
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures), which
otherwise covers every ABI Flet builds for.

`google_crc32c.implementation` answers a coarser question — `"c"` when the extension loaded,
`"python"` when the package fell back to its own table written in Python, several hundred times
slower. The mobile wheels give you `"c"`; assert on it if the same code also runs somewhere
without a wheel.

### App size

This is one of the smallest recipes here. It installs as a pair — the extension and
`flet-libcrc32c` — and the two together come to roughly 110 KB compressed and 300 KB unpacked per
64-bit Android ABI, 25 KB and 43 KB on `armeabi-v7a`, and 33 KB and 110 KB on the iOS device
slice. The 64-bit Android figure is almost all shared library. Narrowing `target_arch` here buys
speed rather than bytes.

### Other considerations

A desktop `flet run` uses PyPI's own wheel, and both macOS wheels of 1.8.0 — arm64 and x86_64 —
contain only the portable table, where the Linux ones and the mobile wheels here also contain the
instruction path. Checksums come out identical either way; only the speed differs. A rate
measured on a Mac is a floor, not a forecast.

## Things to know

- **CRC32C detects accidents, not tampering.** It is linear over GF(2): for equal-length
  messages, `value(a ^ b ^ c) == value(a) ^ value(b) ^ value(c)`, so anyone editing a file can
  keep its checksum unchanged without searching for a collision. And 32 bits is small — a
  birthday search over random 64-byte messages on desktop found a colliding pair in 20,000 to
  230,000 tries across eleven runs, none taking a quarter second. For anything an attacker
  touches use [`hashlib`](https://docs.python.org/3/library/hashlib.html) or
  [`hmac`](https://docs.python.org/3/library/hmac.html); use CRC32C for bit rot, truncated
  writes and flaky transfers.

- **`hexdigest()` returns `bytes`, not `str`.** That is the opposite of hashlib, and it bites
  when the value goes into a JSON body or an f-string: you get `b'e3069283'` embedded in the
  output. Call `.decode()`. `digest()` is four bytes, most significant first — base64 them and
  you have the value Google Cloud Storage carries as
  [`x-goog-hash: crc32c=...`](https://cloud.google.com/storage/docs/data-validation). Upstream's
  docstring credits RFC 4960 for that order, but the RFC byteswaps the value before it goes on
  the wire; big-endian here is Cloud Storage's convention, not SCTP's.

- **[`zlib.crc32`](https://docs.python.org/3/library/zlib.html#zlib.crc32) is a different
  checksum.** Both are 32-bit CRCs, but zlib uses the IEEE 802.3 polynomial `0x04C11DB7` and
  this package uses Castagnoli's `0x1EDC6F41`. For `b"123456789"`, `zlib.crc32` gives
  `0xcbf43926` and `google_crc32c.value` gives `0xe3069283`. A service that asked for one will
  reject the other, and neither name usually says which is meant.

## Build notes (maintainers)

### Recipe shape

Two recipes: [`flet-libcrc32c`](../flet-libcrc32c) builds Google's C library with CMake, and this
one builds upstream's small `setup.py` extension against it. The split is forced by upstream: the
sdist carries the binding's single `_crc32c.c` and no vendored library, and expects to find one
installed, so there is no self-contained variant to prefer.

The two platforms differ in how the library arrives. Android builds it shared, so
`_crc32c.cpython-*.so` carries a `DT_NEEDED` on an unversioned `libcrc32c.so` that Flet packages
as a `jniLibs` entry; iOS builds it static and the extension absorbs it, which is why the iOS
device extension is around 68 KB against Android's 5 KB. The host requirement becomes
`Requires-Dist: flet-libcrc32c (==1.1.2)` on both platforms, so the wheels are only valid as a
pair — and on iOS that ships a build-time `libcrc32c.a` into the app too.

### Upgrade hazards

Upstream now lives in the `google-cloud-python` monorepo; `googleapis/python-crc32c` is archived
and will not show a bump's changes. The pin runs one way: `google-crc32c`'s metadata names an
exact `flet-libcrc32c` version, so a library bump means rebuilding and republishing the consumer
too.

Upstream's `setup.py` builds the extension inside a `try`/`except SystemExit` and calls
`build_pure_python()` when that fails, unless `CRC32C_PURE_PYTHON` is set in the environment. A
toolchain break therefore produces a green build whose wheel carries no `.so` at all — and the
device tests still pass, because the pure-Python implementation returns identical values. Confirm
`_crc32c.cpython-*.so` is in the wheel before publishing.

The other silent hazard: whether the instruction path is compiled in is decided by upstream's
own CMake feature probes (`HAVE_ARM64_CRC32C`, `HAVE_SSE42`), not by anything here. A probe that
stops firing under a new toolchain produces a wheel that builds, tests and behaves correctly
while running several times slower. Upstream's own macOS wheels are the cautionary case: 1.8.0
ships there with only `crc32c::ExtendPortable`. Every speed claim above rests on the check below.

### Re-verification checklist

- **Compiled paths per slice:** `llvm-readelf --dyn-syms` on the ELF side and
  `llvm-nm --demangle` on the Mach-O side must show `crc32c::ExtendArm64` in the Android
  `arm64-v8a` library and both iOS `arm64` extensions, `crc32c::ExtendSse42` in Android `x86_64`
  and the iOS `x86_64` simulator extension, and only `crc32c::ExtendPortable` in `armeabi-v7a` and
  in the `x86` slice forge still emits for cp312. Confirm with a disassembly that actually
  contains `crc32c{b,h,w,x}` or `crc32` instructions; an exported symbol name is weaker evidence
  than the instruction.
- **Runtime gates:** a compiled-in path with a broken probe is never taken, and the probes
  differ. Only the `arm64-v8a` library imports `getauxval` — Android `x86_64` uses `cpuid` and
  imports nothing — and only the two iOS `arm64` extensions import `sysctlbyname`. Android's ARM
  probe demands both the `CRC32` and `PMULL` HWCAP bits, so losing either loses the path.
- **Exported C++ runtime:** the 64-bit Android `libcrc32c.so` statically absorbs libc++ and
  exports `std::bad_alloc`, `std::type_info` and friends — which is why it is around 260 KB
  against 10 KB on the 32-bit ABIs. Check a bump has not turned that into a `libc++_shared.so`
  dependency or a duplicate-symbol clash with another package.
- **Linkage:** unversioned `libcrc32c.so` soname with the extension's `DT_NEEDED` naming it on
  Android; `MH_DYLIB` on all three iOS extension slices.
- **Argument parsing:** the `y#` in upstream's `_crc32c.c` is what makes `bytearray` and
  `memoryview` fail. If a bump moves to `s*`, the Install section is wrong.
- **Size:** re-measure from the wheels rather than scaling these figures.

### Coverage gaps

The device tests cover three standard CRC32C check values — `b""`, `b"123456789"` and `b"a"` —
and the chunked `update`/`digest` path. They do not check which implementation was selected, the
hardware-versus-table split, the read-only-buffer rejection, `consume`, `copy` or `hexdigest`, or
a round trip through app storage. The pure-Python fallback returns the same values, so a green run
does not even prove the extension loaded, let alone that it computes quickly — the claim most
likely to break on a bump.
