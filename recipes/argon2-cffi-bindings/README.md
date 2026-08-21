# argon2-cffi-bindings

[`argon2-cffi-bindings`](https://github.com/hynek/argon2-cffi-bindings) is the CFFI binding
layer for [libargon2](https://github.com/P-H-C/phc-winner-argon2), the reference
implementation of Argon2 — the winner of the Password Hashing Competition, specified in
[RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html). In a Flet app it hashes a
passphrase for a local unlock screen, or derives a key for encrypting data the app keeps,
on the device and without a round trip.

The import name is `_argon2_cffi_bindings`, and its public surface is two objects: `ffi`
and `lib` — the C API as it stands, with integer status codes and buffers you size yourself.

## Install

Most apps want [`argon2-cffi`](https://argon2-cffi.readthedocs.io/) — the ergonomic wrapper
that adds [`PasswordHasher`](https://argon2-cffi.readthedocs.io/en/stable/api.html#argon2.PasswordHasher),
its exception types and the named
[profiles](https://argon2-cffi.readthedocs.io/en/stable/api.html#profiles) on top of the
compiled half this recipe builds:

```toml
dependencies = [
    "flet",
    "argon2-cffi",
]
```

Depend on the bindings directly when you want the C surface — a raw key rather than an
encoded hash, or control over each call:

```toml
dependencies = [
    "flet",
    "argon2-cffi-bindings",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`password-cost`](examples/password-cost) — measures what a hash costs on the device it
  runs on, and picks the strongest parameters that fit a latency budget.

## Usage in a Flet app

Through the wrapper, hashing and verifying are two calls, and the result is an ASCII string
you store:

```python
from argon2 import PasswordHasher

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
encoded = hasher.hash(passphrase)          # '$argon2id$v=19$m=65536,t=3,p=4$...'
hasher.verify(encoded, attempt)            # raises VerifyMismatchError if wrong
```

Through the bindings, the same work is one C call whose status you check yourself:

```python
from _argon2_cffi_bindings import ffi, lib

size = lib.argon2_encodedlen(3, 65536, 4, len(salt), 32, lib.Argon2_id)
encoded = ffi.new("char[]", size)
code = lib.argon2_hash(3, 65536, 4, secret, len(secret), salt, len(salt),
                       ffi.NULL, 32, encoded, size,
                       lib.Argon2_id, lib.ARGON2_VERSION_13)
if code != lib.ARGON2_OK:
    raise ValueError(ffi.string(lib.argon2_error_message(code)).decode())
```

`memory_cost` is in KiB, so 65536 is 64 MiB. Pass a `uint8_t[]` buffer in place of
`ffi.NULL` and `ffi.NULL` in place of `encoded` for raw key bytes — the tag the encoded
string carries, before base64.

### Storage

What you store is the encoded string, and it is built to be stored: algorithm, version,
cost parameters and salt are all inside it, and `lib.argon2_encodedlen` reports its length
in advance — 98 bytes for a 16-byte salt and a 32-byte tag. A single value such as a local
unlock hash fits
[`page.shared_preferences`](https://flet.dev/docs/controls/page/#flet.Page.shared_preferences),
whose methods are coroutines:

```python
await page.shared_preferences.set("unlock", encoded)             # in an async handler
page.run_task(page.shared_preferences.set, "unlock", encoded)    # from a worker thread
```

Write it bare from a handler that is not `async` and you get a coroutine nobody runs:
nothing stored, nothing raised, nothing to see.
[`page.run_task`](https://flet.dev/docs/controls/page/#flet.Page.run_task) is the way in
from a worker thread, because it schedules onto the page's own event loop.

If the hash belongs to a file or database the app owns, keep it in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
with the rest of that data — not in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache),
which the platform may clear. Never store the passphrase itself; and a key derived from one
is the case where nothing is stored at all — ask for raw output, use the bytes, let them go.

### Threading

A hash blocks for as long as its parameters make it, so it cannot run on the UI thread. Use
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), disable
the control that started it, and end the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update):

```python
def unlock():
    try:
        ok, _ = verify_password(stored, field.value)
        status.value = "unlocked" if ok else "wrong passphrase"
    except Exception as exc:
        status.value = str(exc)
    spinner.visible = False
    page.update()  # auto-update does not reach background threads
```

Moving the hash off the UI thread is what keeps the interface responsive; the spinner is
drawn by Flutter, not by your Python. Releasing the GIL is a separate property, and this
call has it — the CFFI call gives the GIL up for the duration of the C function, so the
rest of your Python carries on instead of queueing behind the hash, and threaded hashes
really do overlap: four sequential 64 MiB, three-pass hashes took 370 ms on a desktop and
the same four in Python threads took 140 ms. That overlap is the reason to serialise
deliberately — each concurrent hash allocates its own `memory_cost`.

### Cost calibration

Argon2 is memory-hard by design: it fills `memory_cost` KiB and passes over all of it
`time_cost` times, so the running time is a property of the device and the one thing you
have to establish for yourself before shipping. These are milliseconds on an Apple Silicon
**laptop**, single lane, here for their shape rather than their values — a phone is slower:

| `memory_cost` | `time_cost` 1 | `time_cost` 2 | `time_cost` 3 |
| --- | ---: | ---: | ---: |
| 8 MiB | 3 | 6 | 9 |
| 32 MiB | 13 | 28 | 42 |
| 64 MiB | 28 | 61 | 88 |
| 128 MiB | 59 | 125 | 186 |
| 256 MiB | 127 | 253 | 381 |

Doubling the memory doubles the time; raising `time_cost` multiplies it. Raising
`parallelism` divides the wall clock — four lanes cut that 64 MiB, three-pass hash from
90 ms to 27 ms on the same laptop — without changing how much memory is used, because lanes
split one block rather than adding blocks.

RFC 9106's first recommendation is 2 GiB of memory at one pass — offered as the uniformly
safe choice precisely when nothing is known about the hardware, which is not a phone's
situation. Its second, for when much less memory is available, is 64 MiB at three passes,
and that is also `PasswordHasher`'s default. Take the second as a starting point: fix a
budget the interface can hold — a quarter of a second suits an unlock screen — then raise
`memory_cost` until a hash fills it on the slowest device you support. Measure on the
hardware. An emulator or simulator runs on your desktop's memory subsystem and will lead
you to a `memory_cost` no phone can afford.

That memory is really allocated for the length of the call: a 128 MiB hash moved a desktop
process's peak resident set by about 130 MB, and four concurrent 64 MiB hashes by about
270 MB (decimal). Concurrent hashes add up, sequential ones do not — one in flight at a
time.

### App size

The wheel is approximately 27–30 KB compressed per architecture, and the compiled module
inside it 36–102 KB — too small for a
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) rule or a
narrower [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
to be worth reaching for. What this package spends is the runtime memory `memory_cost` asks
for, and no packaging option changes that.

### Other considerations

A desktop `flet run` uses PyPI's wheel. On an x86 desktop that wheel compiles libargon2's
SSE2 code path, while every ARM build — the phone, and an Apple Silicon Mac — uses the
portable reference implementation, because the optimised path is x86 SIMD only. The same
split runs through the mobile wheels: the x86 emulator and simulator slices carry the SSE2
code and the ARM device slices do not. The hashes are identical either way; the speed is
not, so a cost calibrated on an emulator, or under `flet run` on an Intel machine, is
misleading twice over — wrong memory subsystem and wrong implementation.

## Things to know

- **Nothing raises; every call returns a status code.** A mismatch is
  `lib.ARGON2_VERIFY_MISMATCH` (-35), a salt under 8 bytes is -6, and
  `ffi.string(lib.argon2_error_message(code))` turns any of them into text — "Salt is too
  short", "The password does not match the supplied hash". Ignore the return value of
  `lib.argon2_hash` and you read an untouched buffer: `ffi.string` on it gives `b""`.

- **The salt is yours to make.** libargon2 does not generate one, and reusing one across
  users removes the reason for having it. Take
  [`secrets.token_bytes(16)`](https://docs.python.org/3/library/secrets.html#secrets.token_bytes)
  per hash, or let `PasswordHasher` do it.

- **Verifying costs what hashing cost, and failure is not cheaper.** At 64 MiB and three
  passes, a desktop run took about 90 ms to hash, 90 ms to verify the right passphrase and
  90 ms to reject a wrong one. Budget the spinner for the failure path too, and rate-limit
  attempts rather than expecting a bad guess to be cheap.

- **The library attempts whatever you ask it for.** A `memory_cost` of 8 GiB returned
  success on a desktop with paging behind it, nearly 20 seconds and 7.5 GB of resident
  memory later; on a phone the same request is an out-of-memory kill, or
  `ARGON2_MEMORY_ALLOCATION_ERROR` (-22) if it merely fails.

- **Parameters travel with the hash, so raising the cost later is safe.** An old hash keeps
  verifying at the parameters recorded in its own string, and
  [`PasswordHasher.check_needs_rehash`](https://argon2-cffi.readthedocs.io/en/stable/api.html#argon2.PasswordHasher.check_needs_rehash)
  reports which stored hashes to re-make the next time the passphrase is typed.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` carries a name, a version and a build number, and that is the whole recipe: the
sdist vendors libargon2 under `extras/libargon2` and compiles it into the CFFI module
through the standard setuptools path, so there is no `flet-lib*` recipe to keep in step and
no patch to maintain.

The one build-time decision worth knowing about lives in the sdist's `_ffi_build.py`, which
picks between libargon2's `opt.c` and `ref.c` from `ARCHFLAGS` and `platform.machine()`
unless `ARGON2_CFFI_USE_SSE2` says otherwise. The optimised path is compiled with `-msse2`,
so an ARM slice that picked it would fail to build rather than mis-hash — but an x86
emulator or simulator slice can silently pick either.

### Upgrade hazards

The extension is built against the limited API and ships as `_ffi.abi3.so` unless the
interpreter reports `Py_GIL_DISABLED`, where upstream falls back to a version-specific
module — a move to free-threaded Python in the support builds changes the wheel tag with no
change here.

The vendored libargon2 is a submodule of the upstream repository, and a version bump can
move it independently of the Python-side version. Re-check the encoded output rather than
assuming it is the same C library.

### Re-verification checklist

- **Known answers:** check against RFC 9106's Argon2id vector rather than against another
  slice — two platforms agreeing proves only that they are wrong the same way. The vector
  needs a secret and associated data, so it goes through `lib.argon2_ctx` and an
  `argon2_context`, not `argon2_hash`; the 25.1.0 wheel reproduces its tag
  (`0d640df5…6b01e659`) exactly. A platform-dependent result from a cryptographic primitive
  is a defect, not a variation.
- **Return codes:** the constants and messages quoted above (-35 mismatch, -6 short salt,
  -22 allocation failure) must still read the same way.
- **Which implementation each slice compiled:** the x86 emulator and simulator slices take
  `opt.c` and the ARM device slices `ref.c`. Check it on the x86 slices, where either is
  possible: `objdump -d` shows `palignr` and `pshufb` in an `opt.c` build's mixing code and
  neither in a `ref.c` one, which uses `punpcklqdq`/`punpckhqdq` instead. Do not read
  `pmuludq` as the tell — both builds emit it, so it only says the slice is x86. A slice
  that changed sides would move its own timings without moving a device's.
- **Parallelism on device:** lanes dividing wall-clock time without changing memory is a
  desktop reading. Confirm it on hardware before repeating it.
- **Size:** re-measure the compressed wheels per slice.

### Coverage gaps

The device test hashes once at `t=2`, `m=64 MiB`, `p=1` through `ffi` and `lib`, checks the
encoded prefix, and verifies a right and a wrong password. It does not exercise parallelism
above one lane, allocation failure, raw output or the `argon2-cffi` wrapper, and it takes no
timings at all: every cost figure here is a desktop measurement, and the example exists to
take the device numbers this page cannot.
