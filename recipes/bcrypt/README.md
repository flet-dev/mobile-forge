# bcrypt

[`bcrypt`](https://github.com/pyca/bcrypt) is the password hashing function whose whole design
goal is to be *slow*: a tunable cost factor makes each hash deliberately expensive, so guessing
passwords stays expensive too. The API is four functions —
[`gensalt`](https://github.com/pyca/bcrypt#adjustable-work-factor),
[`hashpw`](https://github.com/pyca/bcrypt#password-hashing), `checkpw` and
[`kdf`](https://github.com/pyca/bcrypt#kdf) — and nothing else. On a phone you want it for a
local unlock code, for credentials an app verifies offline, or to produce and check hashes a
server shares with you; the 60-byte output is portable in both directions.

The cost factor is what makes this recipe different from most on this index. **It is the one
number bcrypt asks you to choose, the work doubles for every step you add, and the right value
depends on the slowest device you ship to** — so it is a number to measure rather than copy
from a tutorial written on a workstation. The
[`cost-factor-explorer`](examples/cost-factor-explorer) example exists to measure it.

Two things then set bcrypt apart from the other compiled recipes here. The extension **releases
the GIL for the whole hash**, so a background thread genuinely buys you parallelism instead of
just an early return — see [Threading](#threading). And **5.0.0 stopped silently truncating
passwords at 72 bytes and raises instead**, which invalidates most of what is written about
bcrypt online and can crash a Flet session outright; that is the first entry in
[Things to know](#things-to-know).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "bcrypt",
]
```

**Nothing else comes along and nothing needs configuring.** The wheel's `Requires-Dist` has two
entries and both are extras-gated (`pytest; extra == "tests"` and `mypy; extra == "typecheck"`),
so a plain `bcrypt` resolves to exactly one wheel — measured, `pip download` with dependencies
for Android arm64 / Python 3.14 saved one file. No `flet-lib*` wheel, no `cffi`, and in
particular no `flet-libcpp-shared`: the Rust extension links nothing but `libpython`, `libdl`
and `libc` on Android (see [Android notes](#android-notes)).

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry either. There are no data files to find — the wheel is nine entries, of which one is the
extension and the rest are 23.5 KB of licence, metadata and a 1,000-byte `__init__.py` that
contains nothing but `from ._bcrypt import (…)` and an `__all__`. Nothing builds a path,
reads its own source, or opens a file, so it runs as-is out of Android's zipped site-packages, and
Flet's default [`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup) and
cleanup take away nothing it needs — what they do remove is the last bullet of
[Things to know](#things-to-know).

**A bare `bcrypt` always resolves from this index.** Upstream publishes 63 files for 5.0.0 and
not one of them is an Android or iOS wheel, so there is no version race of the kind
[`sqlalchemy`](../sqlalchemy) and [`aiohttp`](../aiohttp) describe: measured, one
`pip download --only-binary :all: --extra-index-url https://pypi.flet.dev` per target returned
this index's own wheel every time — Android arm64-v8a, armeabi-v7a and iOS device on both
Python 3.12 and 3.14, and the 32-bit `android_24_x86` on 3.12, the only minor that has one. No
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed.

Nineteen wheels at one build number: all three Android ABIs Flet targets and all three iOS
slices on Python 3.12, 3.13 and 3.14, plus a legacy 32-bit `android_24_x86` slice that only
3.12 gets. Every one of them carries the extension, and every other file in them — `__init__.py`,
the stub, `py.typed`, `METADATA`, the licence, `top_level.txt` — is byte-identical across all
nineteen; only the extension, and the `RECORD` and `WHEEL` lines that name it, change.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`cost-factor-explorer`](examples/cost-factor-explorer) — measures milliseconds per cost
  factor on the device, proves the hash is right three independent ways, and shows what a
  password over 72 bytes does.

## Threading

**The extension drops the GIL around the whole hash, so hashing in a background thread is real
parallelism and the UI thread is not starved.** This is the opposite of
[`pyyaml`](../pyyaml) and [`pydantic-core`](../pydantic-core), and it is the most useful thing
to know about bcrypt in a Flet app.

The evidence is the source and the behaviour; the symbols only narrow it down. `hashpw` wraps its
work in `py.detach(|| bcrypt::hash_with_salt(…))` and `kdf` in
`py.detach(|| bcrypt_pbkdf::bcrypt_pbkdf(…))` (the 5.0.0 sdist's `src/_bcrypt/src/lib.rs`), and
the module is declared `#[pyo3::pymodule(gil_used = false)]`. Every one of the nineteen wheels'
extensions does import `PyEval_SaveThread` and `PyEval_RestoreThread`, the pair a GIL release
compiles to (`llvm-nm -D -u` on the ten Android slices, `nm -u` on the nine iOS ones) — but that
pair is necessary, **not sufficient**, and on its own proves nothing: pyo3 emits it for its own
internal lock waits too, which is why [`pydantic-core`](../pydantic-core) on this index imports
both symbols and still holds the GIL for a whole validation. What settles it is behaviour. On
desktop, four cost-11 hashes took 373 ms one after another against 106 ms across four threads
(3.52x), eight took 775 ms against 128 ms (6.05x), and a busy loop standing in for the UI thread
counted 33,645 turns/ms idle against 33,109 during a cost-12 hash — within a couple of percent,
on a machine with other work on it. Worth repeating the measurement rather than the grep: an
extension that stopped detaching would keep both symbols.

So the shape is the ordinary Flet one, and it pays off rather than merely tidying up. Push the
hash to [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), end
the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) because auto-update does
not reach background threads, and wrap the body in `try/except` — `run_thread` never retrieves
the worker's future, so a raised exception surfaces nowhere and a failed login just looks like a
screen that stopped updating. The re-entrancy guard belongs in the *handler*, not in the worker:
`run_thread` only schedules, so a `disabled` set inside the worker has not happened yet when
Flet pushes the control states.

There is no pool to size and no shared state to serialise. **Nothing in the wheel starts a
thread of its own** — `pthread_create` is absent from the undefined symbols of all nineteen
slices; what Android imports is thread-local-storage keys
(`pthread_key_create`/`getspecific`/`setspecific`/`key_delete`) plus, on every ABI except
armeabi-v7a, `pthread_rwlock_rdlock`/`wrlock`/`unlock`, and what iOS imports is the
`pthread_mutex_*` family, `pthread_threadid_np` and three `dispatch_semaphore_*` calls. Every
function is byte-in, byte-out with no handle to keep, so N simultaneous verifications are N
independent hashes, and the ceiling on that is the device's core count. The example prints
`os.cpu_count()` beside its measured speedup for exactly that reason.

All of those numbers are desktop numbers. The ratio is the transferable part; the milliseconds
are not.

## Android notes

**The extension is a plain, self-contained CPython extension module.** `DT_NEEDED` is
`libpython3.<minor>.so`, `libdl.so` and `libc.so` on all ten Android slices, with no `SONAME`, no
`RPATH` and no `RUNPATH` (`llvm-readelf -dW`), and exactly one exported symbol, `PyInit__bcrypt`.
All four `PT_LOAD` segments carry 16 KB (`0x4000`) alignment, which Android 15 requires — checked
on the same ten, the legacy 32-bit `x86` slice included.

**`gensalt` draws its randomness from the `getrandom` syscall here.** The extension leaves
`syscall` undefined and carries `/dev/urandom` and `/dev/random` as the
[`getrandom`](https://docs.rs/getrandom/) crate's fallback path. Nothing to configure, and it is
effectively free — 1,000 calls to `bcrypt.gensalt(12)` took 0.84 ms in total on desktop.

**The extension's filename is not uniform across Python versions, and it does not matter.** The
cp313 and cp314 Android wheels ship `bcrypt/_bcrypt.cpython-3XX-<triple>.so`, while all four
cp312 Android wheels ship `bcrypt/_bcrypt.cpython-312.so` with no platform triple. Both are
`*.cpython-*.so`, which is the whole of what serious_python's Android packaging matches on: read
out of `serious_python_android` 4.5.1's Gradle build, the tag regex is
`\.(cpython-[^/]+|abi3)\.so$`, and the module is relocated to `jniLibs` under
`lib<dotted-name-with-dashes>.so` with a `.soref` marker left at the import path — so both
names mangle to the same `libbcrypt-_bcrypt.so` and the same `bcrypt/_bcrypt.soref`. That rule's
output has been measured for another recipe on this index ([`pyyaml`](../pyyaml) reports
`libyaml-_yaml.so` on an arm64 emulator), but **not for bcrypt**: read the real value off the
[`cost-factor-explorer`](examples/cost-factor-explorer) example's header line rather than off
this page. Either way, code that locates something relative to a native module's `__file__`
breaks here — for the same Flet version [`pydantic-core`](../pydantic-core) reports no `__file__`
at all on Android.

## iOS notes

**The extension needs no fixing up, no preloading and no side library.** `otool -hv` reports
`DYLIB … NOUNDEFS DYLDLINK TWOLEVEL NO_REEXPORTED_DYLIBS MH_HAS_TLV_DESCRIPTORS` on all nine iOS
slices, so it is already the `MH_DYLIB` that Flet 0.86's iOS packaging needs and cannot hit the
`MH_BUNDLE` link failure other recipes here have. Its undefined symbols resolve to CPython and
libSystem and nothing else on every slice — 124 to 129 of them, 65–69 from CPython and 59–60
from libSystem, the cp314 device slice being 129 = 69 + 60 (`nm -m … | grep undefined`) — and
like Android it exports exactly one symbol, `PyInit__bcrypt`.

`otool -L` names one library you did not ask for, `/usr/lib/libiconv.2.dylib`. **Ignore it.** No
symbol is taken from it (`nm -mu … | grep -ci iconv` is 0), iOS ships it, and upstream's own
macOS wheel links the identical path — it is a rustc target artefact, not something this recipe
introduced.

**`gensalt` uses CommonCrypto here rather than a syscall**: the undefined symbol is
`_CCRandomGenerateBytes`, with a `SecRandomCopyBytes` failure string as the fallback path. Both
platforms are OS CSPRNGs, and salts are identical in format and cost either way.

**The iOS extension is about 19% larger than the Android arm64 one for the same Python** —
534,724 B against 450,368 B on cp314 — with no extra functionality behind it. Part of it is
Mach-O overhead, and part is unwinding machinery Android does without: the iOS slice imports
twelve `_Unwind_*` symbols and dispatch semaphores where Android imports none of the former.

Flet turns each site-packages `.so` into a framework and leaves a `<name>.fwork` pointer file at
the module's original path, and CPython's `AppleFrameworkLoader` reports that pointer as
`__file__` — which is how [`pydantic-core`](../pydantic-core) comes to report
`_pydantic_core.fwork` on an iOS device. bcrypt's own value has **not** been read off a device;
the example prints it.

## Things to know

- **bcrypt 5.0.0 no longer truncates at 72 bytes — it raises `ValueError`, from `checkpw` as
  well as `hashpw`.** Every pre-5.0 tutorial and answer says the opposite, and the one place
  upstream records the change is its
  [changelog](https://github.com/pyca/bcrypt#changelog), under 5.0.0: *"Passing `hashpw` a
  password longer than 72 bytes now raises a `ValueError`. Previously the password was silently
  truncated"*. Upstream's own *Maximum Password Length* section has **not** been updated and still
  describes the old behaviour — "only handles passwords up to 72 characters, any characters beyond
  that are ignored" — so that section is the wrong thing to check this against, in two ways: the
  truncation is gone, and the limit was never in characters (next bullet). The check
  is the first statement in `hashpw`, before the salt is even parsed, and `checkpw` is
  implemented as `hashpw` plus a compare, so a user pasting a long passphrase into a login field
  takes the session down rather than failing to log in — **an unhandled exception in a Flet
  handler makes Flet send `SESSION_CRASHED`, a crash screen.** Measured on 5.0.0: 71 and 72
  bytes hash, 73 and 100 raise, and `checkpw(b"a" * 73, …)` raises before it looks at the hash
  at all — the same error for an empty hash, a garbage one and a valid one. Catch `ValueError`
  around both calls and decide the policy explicitly. Three policies, all tested:

  | policy | what it costs |
  | --- | --- |
  | reject the input with a message | nothing, but you must say "bytes" — see the next bullet |
  | `password[:72]` | keeps 4.x behaviour, and is the *only* way pre-5.0 hashes stay verifiable |
  | `base64.b64encode(hashlib.sha256(password).digest())` | upstream's suggestion; 44 bytes, always in range, and unlike truncation two long passwords stay distinct — but it changes every hash you store, so it is a migration |

  That middle row is not optional if you have existing data. Measured end to end: a hash written
  by bcrypt 4.2.0 for a 100-byte password raises `ValueError` on 5.0.0 when checked against the
  full candidate, and returns `True` when the candidate is cut to 72 bytes first.
- **The limit counts bytes, not characters, so a 37-character passphrase can be over it.**
  Measured: `"é".encode() * 36` is 72 bytes at 36 characters and hashes; `"é".encode() * 37` is
  74 bytes at 37 characters and raises. Validate `len(password.encode("utf-8")) <= 72`, never
  `len(password)` — and say "bytes" in the message, because a user counting characters will not
  understand a limit of 72 that rejects their 37.
- **Everything takes `bytes`, and only exactly `bytes`.** A `str` raises
  `TypeError: argument 'password': 'str' object cannot be converted to 'PyBytes'`, and so do
  `bytearray` and `memoryview` — measured for `hashpw`'s password and salt, `checkpw`'s password
  and hash, `gensalt`'s prefix and `kdf`'s password; `gensalt(4.0)` raises on the rounds instead.
  A [`TextField`](https://flet.dev/docs/controls/textfield/) hands you a `str`, so encode once at
  the UI boundary (`pw = field.value.encode("utf-8")`) and keep bytes inward. Forgetting it at
  one call site is a crash, not a silent mismatch.
- **`checkpw` raises `ValueError("Invalid salt")` on a malformed stored hash instead of
  returning `False`.** An empty column, a truncated write, a cost byte out of range or a NUL
  inside the hash all raise; only a *well-formed* hash that does not match returns `False`.
  Measured: `b""`, `b"notahash"`, `b"$2b$"`, `b"$2b$12$short"`, a one-digit cost and a cost of 99
  all raise, while dropping the hash's last byte, changing it, or appending extra data all return
  `False`. Wrap `checkpw` in `try: … except ValueError:` and treat that as "this stored credential
  is corrupt", distinct from "wrong password" — and do not let it reach Flet's handler boundary.
- **Re-hashing and comparing does not work, and `==` on hashes leaks timing.** The salt lives
  inside the hash, so `hashpw(password, gensalt()) == stored` is `False` for the right password
  as much as the wrong one — measured, along with the two that do work: `hashpw(password, stored)
  == stored` is `True` and `hashpw(b"wrong", stored) == stored` is `False`, because `hashpw`
  decodes only the first 22 base64 characters of the salt field and therefore accepts a whole
  60-byte hash where a 29-byte salt goes. That is exactly how `checkpw` is implemented, plus one
  thing you would lose by hand-rolling it: a `subtle::ConstantTimeEq` compare. Call
  `bcrypt.checkpw(password, stored)`.
- **The cost factor is the decision, the work doubles per step, and `gensalt` will happily
  accept a value that hangs your app.** The library default is 12, and `gensalt` accepts 4
  through 31 (3 and 32 raise `ValueError: Invalid rounds`). Measured on desktop, best of three
  per cost: 0.76 ms at 4, 11.97 at 8, 46.86 at 10, 187.68 at 12, 741.75 at 14 and 2,994.51 at
  16. The doubling is exact where it can be measured cleanly — the step ratio held 2.00 ± 0.01
  across costs 11 → 14 over three independent passes on an otherwise idle machine. **It is only
  the average that is stable, and only on an idle machine**: repeating the same sweep of costs
  8 → 12 on the same desktop under load (load average 19 on ten cores) kept a median of 1.97 over
  32 readings but spread them from 1.52 to 2.56, with more than half outside 1.90–2.10. Contention
  moves an individual reading far more than the cost factor being small does, so treat a single
  ratio as a noise gauge and the trend across rows as the measurement. Extrapolating that doubling, cost
  31 is 2^19 times cost 12 — around 27 hours on the machine those numbers came from, with no
  error and no way to interrupt it. **A phone core is slower than any of those figures**, and no
  device measurement backs this page: cap what a slider or config field can reach at a value you
  measured on the slowest device you support, which is what the
  [`cost-factor-explorer`](examples/cost-factor-explorer) example is for. Because the curve
  doubles exactly, one measurement fixes the whole table.
- **Verifying costs the same as hashing; producing a salt costs nothing.** `checkpw` *is*
  `hashpw` plus a constant-time compare, so a login screen pays the full cost factor once per
  attempt whether the password is right or wrong — measured at cost 12: 185.7 ms to hash,
  186.6 ms to verify correctly, 187.1 ms to reject. Moving a cost slider, by contrast, is free:
  the cost is recorded in the salt rather than spent producing it, and 1,000 `gensalt(12)` calls
  took 0.84 ms in total.
- **The hash is self-describing and always 60 ASCII bytes, which is what makes raising your cost
  factor a non-event.** The first 29 bytes are the salt string `$2b$<cost>$<22 base64 chars>`
  (measured: `hashpw(pw, salt)[:29] == salt`), and `checkpw` re-derives the cost from the hash it
  is given — so hashes written at an old cost keep verifying after you raise your default, with
  no migration. Being 60 ASCII bytes, a hash round-trips through `.decode("ascii")`, so any text
  column, key-value store or file in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  holds one; encode it back before `checkpw`. bcrypt itself never chooses a path — it opens no
  file of its own and no sockets at all (no socket, connect, send, recv or getaddrinfo symbols on
  either platform; the only path it can ever open is `getrandom`'s `/dev/urandom` fallback), so
  where the hash lives is entirely your app's decision.
- **Hashes are portable to and from a server, in both directions.** Three of upstream's own test
  vectors verify against these wheels' code, two of them `$2a$` hashes. `hashpw` accepts `$2a$`,
  `$2b$`, `$2y$` and `$2x$` in the salt's version field (`$2c$` and `$2$` raise
  `ValueError: Invalid salt`), and the digest bytes come out identical across `$2a$`, `$2b$` and
  `$2y$` for the same password and salt — only the version field differs, measured. So a `$2y$`
  hash verifies, which is the prefix upstream's README calls "still supported in `hashpw` but
  deprecated"; that was checked against a `$2y$` hash produced here, not against one from another
  implementation. `gensalt` only ever *produces* `$2a$` or `$2b$`
  (`gensalt(4, b"2y")` raises `ValueError: Supported prefixes are b'2a' or b'2b'`).
- **NUL bytes are hashed rather than treated as a terminator, and that is not new in 5.0.0.**
  `hashpw(b"ab\x00cd", salt)` succeeds, `checkpw(b"ab", …)` is `False` and
  `checkpw(b"ab\x00cd", …)` is `True` — identical results from bcrypt 4.2.0 in a second
  environment, so do not file this with the 5.0.0 changes. The one thing to remember is that a
  NUL *inside a stored hash* is one of the `Invalid salt` cases above, so it belongs in the
  corrupt-credential branch.
- **`kdf`'s `rounds` is linear, not logarithmic like `hashpw`'s cost, and the library warns you
  if you get that wrong.** Measured: 50 rounds 146.1 ms, 100 rounds 292.5 ms, 200 rounds
  590.2 ms. Below 50 it emits `UserWarning: Warning: bcrypt.kdf() called with only N round(s).
  This few is not secure: the parameter is linear, like PBKDF2.`, silenced with
  `ignore_few_rounds=True`. Unlike `hashpw` it takes passwords longer than 72 bytes, it is
  deterministic for the same inputs, `desired_key_bytes` must be 1–512, and neither password nor
  salt may be empty.
- **bcrypt's own description tells you to prefer argon2id, and argon2 is on this index.** The
  first line of prose in the `METADATA` description — upstream's README, under the badges, not the
  `Summary` field — is *"Acceptable password hashing for your software and your servers (but you
  should really use argon2id or scrypt)"*. Both alternatives are reachable from a Flet app:
  `argon2-cffi` resolves for mobile as four wheels — measured for Android arm64 / 3.14, the pure
  `argon2_cffi` 25.1.0 front end and `pycparser` 3.0 from PyPI plus `argon2_cffi_bindings` 25.1.0
  and `cffi` 2.0.0 from this index. `hashlib.scrypt` needs no dependency at all, and the
  OpenSSL-backed function it wraps is compiled into Flet's mobile Python on both platforms — the
  `_hashlib` extension in the python-build runtime carries the `scrypt(…)` argument-clinic
  signature and OpenSSL's `EVP_PBE_scrypt`, imported from `libcrypto` on Android and statically
  linked on iOS — though nothing here has called it on a device. Reach for bcrypt when something
  else already chose it: an existing hash column, a server, or a format you have to interoperate
  with.
- **Size: a quarter of a megabyte, and 95% of it is the extension.** The nineteen wheels span
  229,658–273,979 B, unpacking to 473,924–570,157 B; on cp314, 232,286 B / 473,924 B unpacked on
  Android arm64-v8a and 229,831 B / 558,270 B on the iOS device slice. Everything that is not the
  extension comes to the same 23,528–23,561 B on every single slice — the whole 33-byte spread
  being the length of the extension's filename in `RECORD` and of the platform tag in `WHEEL`.
  Flet's default cleanup deletes `bcrypt/__init__.pyi` and `bcrypt/py.typed` by name (`**.pyi`
  and `**.typed` are on serious_python's junk-file list), which leaves one compiled
  `__init__`, the `dist-info`, and the extension. Nothing here is worth trimming.

## Build notes (maintainers)

The build side of the recipe is two files — a `meta.yaml` naming the version and one test — with no
`patches/` directory and no `build.sh`. That is the fact worth recording: bcrypt is a Rust/PyO3
extension built through setuptools-rust (`build-system.requires` is `setuptools`, `wheel` and
`setuptools-rust>=1.7.0`), and it cross-compiles to every slice of all three Python minors on
forge's stock support with one environment variable and nothing else. The day it needs a patch,
suspect the toolchain or an upstream restructuring before reaching for one.

**No on-device run backs any claim on this page.** Everything above was read off the nineteen
wheels or measured on a desktop install of the same version, and the central number a consumer
wants — milliseconds per cost factor on a phone — is missing by construction. What licenses the
desktop evidence is that the mobile wheels run the same code: `bcrypt/__init__.py`,
`__init__.pyi` and `py.typed` hash identical across all nineteen mobile wheels *and* upstream's
`cp38-abi3-macosx_10_12_universal2` wheel (`__init__.py` at
`72ff8dba9217e8fee8e80e0f2bf174babe886680ebdc69efcb314ef64d7ac0a4`), `METADATA` differs from
upstream's only in `Metadata-Version` and one `Dynamic:` line, and `strings -a` on both the
Android and iOS extensions names the same crate versions the sdist's `Cargo.lock` pins
(`bcrypt-0.17.1`, `bcrypt-pbkdf-0.10.0`, `blowfish-0.9.1`, `base64-0.22.1`, `pbkdf2-0.12.2`,
`pyo3-0.26.0`). An Android and an iOS run of the
[`cost-factor-explorer`](examples/cost-factor-explorer) example is the missing evidence, and its
header line is built to be the thing you read off the screen.

**The test covers verification only, and not the thing most likely to break.**
`tests/test_bcrypt.py` is one function without a docstring — which the repo's test convention
requires — performing two cost-12 `checkpw` calls against a hardcoded hash. It never calls
`gensalt`, `hashpw` or `kdf`, never asserts the 72-byte `ValueError` that is the whole
behavioural story of 5.0.0, and spends about 400 ms doing it on a fast desktop — more on a
phone. Worth adding, in rough order of value: the 71/72/73-byte boundary
asserting `ValueError` at 73; a `gensalt` → `hashpw` → `checkpw` round trip at cost 4 so the
suite stops paying for 12; a `ValueError` assertion for a malformed stored hash; and the GIL
relationship, N threads against N serial hashes, which is the one claim on this page a device
could confirm cheaply. Per the repo's convention, assert relationships rather than version
numbers, and give every test function a docstring.

On a bump — everything above this section is a claim a bump can falsify without the build
failing:

- **The 72-byte behaviour, first.** It changed in 5.0.0 and it is the load-bearing claim of
  [Things to know](#things-to-know), the example and half the consumer advice on this page. Check
  the boundary directly (71 and 72 hash, 73 raises, `checkpw` raises too) and check the *error
  string*, which is quoted verbatim here and in the example and is upstream's prose. Upstream's
  own suite parametrises `(71, False), (72, False), (73, True)`, so the behaviour is at least
  guarded there.
- **The API surface.** The non-underscore names in `dir(bcrypt)` must still be exactly `checkpw`,
  `gensalt`, `hashpw` and `kdf`, with the signatures `__init__.pyi` declares.
  `bcrypt.__version__` is re-exported from the extension's `__version_ex__` — deliberately not
  named `__version__` in Rust, because passlib treats that attribute's presence as proof of a
  different module — so a rename there breaks the example's header line silently.
- **The GIL release**, which is [Threading](#threading) entirely — and it is the timing that
  checks it, not the symbols. Grep the sdist's `lib.rs` for `py.detach`, then measure: N threads
  must be measurably faster than N serial hashes (3.52x at four, 6.05x at eight, measured on
  desktop), with each worker hashing a *different* password so a shared or dropped result cannot
  pass as a speedup. `PyEval_SaveThread`/`PyEval_RestoreThread` stay in the binary either way, so
  a release that stopped detaching would rewrite that section without failing any grep.
- **The exact doubling.** Every extrapolation on this page and in the example — the next cost up,
  the cost-31 figure, "one measurement fixes the table" — rests on the step ratio staying at
  2.00. Re-measure costs 8 through 16; below 8 the ratios are noisy because a single hash is
  under 10 ms and overhead dominates, which is also why the example's slider starts at 8.
- **The extension's presence and its name per Python minor.** One `.so` per wheel, nineteen
  wheels, and cp312's Android extensions still `_bcrypt.cpython-312.so` while cp313/cp314 carry
  the platform triple. There is no pure-Python fallback anywhere — `__init__.py` is bare imports
  with no `try/except` — so a wheel that lost the extension fails at `import bcrypt` rather than
  degrading quietly, which is the one failure mode that cannot hide. Confirm `import bcrypt`
  passes on device on **every** leg, cp312 Android included, since the naming is the one axis on
  which the three legs genuinely differ.
- **The linkage on both platforms.** Android `DT_NEEDED` is `libpython3.<minor>`/`libdl`/`libc`
  with no `SONAME`, `RPATH` or `RUNPATH`; iOS is `MH_DYLIB`/`NOUNDEFS` with `Python.framework`,
  `libSystem` and the unused `libiconv`. Anything new is a runtime dependency
  [Install](#install) does not mention, and an iOS extension that came back `MH_BUNDLE` would
  fail at link time. Re-check the 16 KB `PT_LOAD` alignment too, which comes from forge rather
  than from this recipe.
- **That upstream still publishes no mobile wheels**, which is what makes [Install](#install)'s
  no-version-race paragraph true. It is a fact about upstream's release matrix, not about this
  recipe, and it is one `pip download --only-binary :all: --platform … --extra-index-url
  https://pypi.flet.dev bcrypt` per target to re-establish. If upstream ever ships Android or iOS
  wheels, that paragraph inverts into the warning [`aiohttp`](../aiohttp) carries — and the
  question of whether this recipe is still needed.
- **The byte-identical Python payload and the crate versions**, per the paragraph above, against
  the desktop wheel and the sdist's `Cargo.lock` of the *same* version. They are what licenses
  every desktop measurement quoted here.
- **The measurements.** The cost curve, the thread speedups, the `gensalt` and `kdf` timings and
  the per-slice sizes are all measured, all on a desktop. Re-measure; do not scale. The ratios
  transfer, the milliseconds do not.
