# pynacl

[`PyNaCl`](https://github.com/pyca/pynacl) is the Python binding for
[libsodium](https://doc.libsodium.org/), the maintained fork of Daniel Bernstein's NaCl. It
gives a Flet app the four things an offline device usually needs and cannot get from the
standard library: [Ed25519](https://pynacl.readthedocs.io/en/latest/signing/) signatures,
[X25519](https://pynacl.readthedocs.io/en/latest/public/) key agreement,
[authenticated symmetric encryption](https://pynacl.readthedocs.io/en/latest/secret/) with
XSalsa20-Poly1305, and [Argon2](https://pynacl.readthedocs.io/en/latest/password_hashing/)
password hashing. `hashlib` has SHA-2, BLAKE2 and `scrypt`, and `hmac` has authentication with
a shared key — but nothing in the standard library signs, agrees a key with a stranger, or
encrypts.

**The property worth the page is that every one of these primitives is authenticated, and it
fails loudly.** Measured on a desktop by flipping *every* bit of a ciphertext one at a time:
736 of 736 flips of a `SecretBox` message raised `CryptoError`, 736 of 736 of a `Box` message
raised `CryptoError`, 800 of 800 of a `SealedBox` message raised `CryptoError`, and 928 of 928
of an Ed25519 signed message raised `BadSignatureError`. **3,200 corrupted messages, 3,200
exceptions, nothing decoded to anything.** That is not how a serialization format behaves: the
same sweep against [`msgpack`](../msgpack) 1.1.2 — every one of the 432 bits of the 54-byte
frame `msgpack.packb(b"x" * 52)` — raised 16 times and **silently handed back a value the other
416**, not one of them the original. That is the difference between a cipher and an
*authenticated* cipher. The [`sealed-note`](examples/sealed-note) example runs a smaller fixed
version of the same sweep on the device and prints the count.

The curve primitives are the reason to reach for this package rather than a general-purpose
crypto library on mobile: Curve25519 needs no big-integer library, no parameter files and no
`libgmp`, so signing and key agreement work on a phone with nothing but this wheel and the
libsodium it links.

What they cost, measured on an otherwise idle desktop (Apple M4, macOS, CPython 3.14.6, PyNaCl
1.6.2 from PyPI), best per-call time of three runs of the [example](examples/sealed-note)'s own
`costs()`; a loaded machine moved every row by up to 8%:

| operation | µs |
| --- | --- |
| ed25519 keygen | 141.0 |
| ed25519 sign, 256 B | 150.4 |
| ed25519 verify | 473.3 |
| x25519 keygen | 138.0 |
| `Box` shared-key precompute (one X25519 DH) | 414.6 |
| `SealedBox` seal, 256 B (ephemeral keypair + DH) | 567.9 |
| `SealedBox` open | 428.1 |
| `SecretBox` seal, 1 KiB | 15.9 |
| `SecretBox` open, 1 KiB | 15.7 |

Read those as the shape rather than the ceiling. On the same machine and the same call,
OpenSSL through [`cryptography`](../cryptography) 50.0.0 did ed25519 verify in 156.9 µs
against libsodium's 473.3 and X25519 exchange in 142.7 against 414.6, and
ChaCha20-Poly1305 at 2,175 MB/s against `SecretBox`'s 77 MB/s over 1 MiB. The gap is
structural and it follows the phone: libsodium's only arm64 assembly is for AES-GCM and AEGIS —
see [Android notes](#android-notes) — so Salsa20, ChaCha20, Poly1305, BLAKE2b, Ed25519 and
X25519 all run portable C on every arm64 target, which is every real device. Choose PyNaCl for
the primitives and the API, not for throughput on bulk data.

**Nothing on this page has been measured on a device yet.** Every figure below is a desktop
measurement or an inspection of the published wheels, and each says which. The
[`sealed-note`](examples/sealed-note) example exists to replace the timings with a phone's own.

**Measured on device, 2026-08-20**, on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6. **Every forgery was refused on both platforms: 1,792 of 1,792** —
512 single-bit flips against a secretbox, 576 against a sealedbox and 704 against an Ed25519
signature, with 0 accepted anywhere. That is the property to hold on to, and it is the opposite
of what an unauthenticated format does with the same experiment: the same 120-flip test decodes
to silently wrong data 49 times through [`brotli`](../brotli) and 86 times through
[`msgpack`](../msgpack). A flipped bit here raises `CryptoError: Decryption failed. Ciphertext
failed verification`, and a wrong passphrase raises the same thing after paying the full
derivation cost.

**Do not size Argon2 parameters from an Android emulator.** The same `interactive` profile —
2 passes over 64 MiB — took **65 ms to seal on the iPhone simulator and 5,921 ms on the Android
emulator**, and the whole sweep 210 ms against 25,127 ms. Argon2id is deliberately memory-hard,
which is exactly what an emulated memory subsystem is worst at, so the Android figure says
almost nothing about a real phone. Pick your parameters on hardware you can hold.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pynacl",
]
```

**The distribution is `pynacl` and the module is `nacl`** — `import nacl.signing`, and nothing
anywhere imports `pynacl`.

The entry belongs in top-level `[project] dependencies` and not in a `[tool.flet.android]` /
`[tool.flet.ios]` table: `flet build` resolves for the build host first, and PyPI has a desktop
wheel for every host you would build from. The 1.6.2 release is 25 files — an sdist, twelve
`cp38-abi3` wheels covering macOS `universal2`, `manylinux`/`musllinux` on x86_64 and aarch64
and Windows `win32`/`win_amd64`/`win_arm64`, and the same twelve again for free-threaded
`cp314t`. Not one of them carries an Android or iOS tag, which is why this recipe exists. The
`abi3` tag means one desktop wheel serves CPython 3.8 through 3.14, so `flet run` on your laptop
gets the same API you ship.

**A bare `pynacl` resolves from this index on every mobile target.** Checked with
`pip download --only-binary :all:` (pip 26.2.1) using `--index-url https://pypi.org/simple
--extra-index-url https://pypi.flet.dev/`, which is the order serious_python uses: all
eighteen combinations — arm64-v8a, armeabi-v7a and x86_64 on Android, device and both
simulators on iOS, across Python 3.12, 3.13 and 3.14 — came back with this index's
`pynacl-1.6.2-1-…` wheel. There is no version race, because upstream publishes no mobile wheel
to lose to.

**Three more wheels come with it, and one of them is load-bearing on Android.** `METADATA` on
all nineteen slices carries `Requires-Dist: cffi>=2.0.0` (plus a `<3.9` variant that never
applies) and `Requires-Dist: flet-libsodium (==1.0.20)`, the second appended by the recipe.
Resolving the closure for Android arm64-v8a / cp314 fetched four wheels — `pynacl` 94,484 B,
`cffi` 195,958 B, `flet_libsodium` 232,234 B and the pure-Python `pycparser` 48,172 B — and for
the iOS device slice four again, at 253,900 / 194,064 / 818,885 / 48,172 B. The two halves
behave differently and it matters:

- **Android links libsodium dynamically.** `DT_NEEDED` on the extension names `libsodium.so`,
  and that file arrives inside the `flet-libsodium` wheel as `opt/lib/libsodium.so`
  (351,904 B on arm64-v8a). Nothing you write puts it where the loader looks; serious_python's
  Gradle step does, and only because it is under `opt/` — see [Android notes](#android-notes).
- **iOS absorbs it.** The iOS extension is `NOUNDEFS` and names no libsodium symbol at all, so
  the `flet-libsodium` wheel's iOS payload is inert at runtime — see [iOS notes](#ios-notes)
  for what it still costs you.

Which `cffi` resolves varies across the iOS slices, and only there. Upstream publishes iOS wheels
for cffi now, but 2.1.1 ships exactly six — cp313, cp314 and cp315, `arm64` device and `arm64`
simulator — so the cp314 device slice takes PyPI's own
`cffi-2.1.1-cp314-cp314-ios_13_0_arm64_iphoneos.whl` while the three cp312 iOS slices and both
`x86_64` simulator slices fall back to this index's `cffi-2.0.0-1-…` (188,592 B for cp314
`x86_64`). Android is this index's throughout. All of them satisfy `cffi>=2.0.0` and ship the
same `_cffi_backend` extension that `nacl._sodium` imports at load time.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Each wheel is 38 entries — one extension, 30 `.py` files, an empty `py.typed`,
and six `dist-info` files including two licences — with no data file of any kind. Nothing in the
Python layer touches `__file__`, `open()`, `importlib.resources`, `pkgutil` or `os.environ`
(grepped across all 30 modules; the only `os` call anywhere is `os.urandom`), so Flet 0.86's
zipped Android site-packages has nothing to bite on. Both `nacl.bindings` and `nacl.pwhash` ship
a real `__init__.py`, so neither is a namespace package and neither depends on the zero-byte
`__init__.py` that serious_python synthesises for namespace directories on Android.

The extension is named `_sodium.abi3.so` on all nineteen slices, which carries the ABI tag
serious_python's `jniLibs` relocation keys on — see [Android notes](#android-notes). **Do not
read `abi3` as "one wheel for every Python".** The Android slices name `libpython3.12.so`,
`libpython3.13.so` and `libpython3.14.so` respectively in `DT_NEEDED`, and the iOS ones name
`@rpath/Python.framework/Python` at compatibility version 3.12/3.13/3.14 — the file name is
version-agnostic, the binary is not.

Nineteen wheels at build number 1: Python 3.12 across all four Android ABIs (arm64-v8a,
armeabi-v7a, x86_64 and the legacy 32-bit `android_24_x86`), 3.13 and 3.14 across three each,
plus all three iOS slices for each of the three Pythons. No architecture is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. The wheels are 89,880–307,204 bytes to download and 363,627–926,800
unpacked; the Python half is exactly 233,313 bytes on every one of them.

## Storage

**PyNaCl has no config directory, no cache and no state — it opens exactly one file, and only
on the libsodium side.** The Python layer's only filesystem call is `os.urandom`. Underneath,
libsodium's own generator reaches `getrandom(2)` through `syscall(2)` on Android and keeps
`/dev/urandom` as its fallback (both the `/dev/urandom` string and a bare `syscall` import are
present in the shipped `libsodium.so`), and on iOS it takes the `/dev/urandom` path outright —
the static archive's `randombytes_sysrandom.o` imports `open`, `read`, `close`, `fcntl` and
`fstat` and does **not** import `arc4random_buf`, because libsodium reserves that branch for
OpenBSD. That file is a device node the sandbox always grants, so there is nothing to configure.

Worth knowing which generator you are actually using, because it is not the one the package
name suggests: **`nacl.utils.random()` is a one-line wrapper around `os.urandom`**, not around
libsodium's `randombytes`. Every key and nonce PyNaCl generates for you goes through CPython —
`SigningKey.generate()`, `PrivateKey.generate()` and the automatic nonce in
`SecretBox.encrypt()` all call it. libsodium's own generator is still initialised (importing
`nacl.bindings` calls `sodium_init()`) and is what produces the ephemeral key pair inside
`SealedBox`. `nacl.bindings.randombytes()` reaches it directly if you want it.

What you *do* have to place is the key material, and it is refreshingly plain: an Ed25519
signing key is 32 raw bytes, an X25519 private key is 32, and `bytes(key)` is the whole
serialization format. So persisting an identity is a 32-byte file under
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which is what the [example](examples/sealed-note) does:

```python
import os
import nacl.signing

path = os.path.join(os.environ["FLET_APP_STORAGE_DATA"], "identity.key")
try:
    with open(path, "rb") as handle:
        signing_key = nacl.signing.SigningKey(handle.read(32))
except OSError:
    signing_key = nacl.signing.SigningKey.generate()
    with open(path, "wb") as handle:
        handle.write(bytes(signing_key))
    os.chmod(path, 0o600)
```

One X25519 key pair comes free with it — `signing_key.to_curve25519_private_key()` converts the
Ed25519 key to its Curve25519 twin, and `verify_key.to_curve25519_public_key()` does the public
half; verified on desktop that the two agree, so one stored secret covers signing *and* sealed
boxes.

**Do not write the key beside `main.py`.** With `[tool.flet.app] path = "src"` the whole `src/`
directory is packaged into the app, so a key file created there during a desktop `flet run` ships
inside the next build.

Two limits to know before you design around this. **There is no OS keychain here** — the
storage surface Flet 0.86.5 exposes is `ft.StoragePaths` and `ft.SharedPreferences`, with
nothing Keychain- or Keystore-shaped beside them, so a key in app storage is protected by the
app sandbox and by device encryption and by nothing else. If the threat model needs
hardware-backed storage, the key has to be held on the platform side. And **the passphrase path
is the one that costs**: deriving a key from a passphrase with Argon2id is deliberately hundreds
of milliseconds and hundreds of mebibytes, which is a [Threading](#threading) question and a
[Things to know](#things-to-know) question, not a storage one.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`sealed-note`](examples/sealed-note) — a note sealed under a passphrase and under a public
  key, signed, reopened, then attacked one bit at a time.

## Threading

**The bindings release the GIL, which makes this package unlike most compiled wheels on this
index.** `PyEval_SaveThread` and `PyEval_RestoreThread` are undefined symbols on every one of
the nineteen slices — cffi wraps `Py_BEGIN_ALLOW_THREADS` around the C call in the generated
module — and measurement on a desktop agrees. With a pure-Python counter thread running beside
the work and its rate given as a percentage of an idle window: controls first, `time.sleep`
(releases) 100–102%, `zlib.decompress` of a 48 MB blob — a C extension that does release it —
84–98%, and `math.factorial(60000)` (holds) **11–22%**. Every PyNaCl case landed with the first
group and none near the third: `argon2id.kdf` at the interactive preset 90–99%,
`SecretBox.encrypt` of 48 MiB 98–111%, and 2,000 consecutive `ed25519 verify` calls 98–119%.
Those are the spread of two independent runs of the harness — read the band and not the figure,
because the counter's rate moves with machine load and one run put two of the PyNaCl cases
*above* the idle window. The factorial control is what shows the harness could have said
otherwise.

That is worth real money on the one operation that needs it. Four threads each running
`argon2id.kdf` at the interactive preset finished in 464 ms against 1,490 ms for the same four
serially — **3.2×** best of eight trials on a desktop with four performance cores, 3.0× at the
median — where a GIL-holding extension would have shown 1.0×. So
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is not just
a way to keep the UI alive here; it is a way to use the phone's cores.

**Budget the memory before the cores, though.** Argon2id is memory-hard on purpose, so *N*
threads at the interactive preset need *N* × 64 MiB resident at once, and at the moderate preset
*N* × 256 MiB. Two concurrent moderate derivations are half a gigabyte of live allocation in an
app process, which is a way to get killed on Android rather than a way to go faster. One worker
is the right default; parallelism is for verifying a batch, not for hashing one password.

The Flet-side rules apply as everywhere else, and the [example](examples/sealed-note) shows
both. A `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads; and its body must be wrapped in `try`/`except`, because
`run_thread` never retrieves the worker's future and discards whatever it raised — with no log,
no dialog and no crash.

**Sharing one key object across threads was safe in every test, and the objects are immutable
anyway.** Measured on desktop, five runs each: eight threads pushing 2,000 messages through one
shared `SecretBox` completed all 2,000 every run with zero exceptions, and eight threads signing
and verifying 2,000 messages through one shared `SigningKey`/`VerifyKey` pair completed 10,000
across the five runs, likewise with none raised. A `SecretBox`, `SigningKey`, `VerifyKey`,
`PrivateKey` or `PublicKey` holds bytes and nothing mutable, and each call allocates its own
output buffer, so there is no shared state to corrupt. `SecretStream` is the exception in the
API — it *is* a running state machine — and one of those belongs to one thread.

## Android notes

- **The extension links libsodium by bare soname, and that is the whole Android story.**
  `DT_NEEDED` on all ten Android slices is exactly `libm.so`, `libsodium.so`,
  `libpython3.<minor>.so`, `libdl.so` and `libc.so`, with no `SONAME`, no `RPATH`, no
  `RUNPATH` and no `libc++_shared` — libsodium is C. Of the extension's 252 undefined symbols
  on cp314 arm64-v8a, 235 are `crypto_*` / `sodium_*` / `randombytes*` resolved out of
  `libsodium.so`, 13 are CPython's, and four are bionic's (`memset`, `__cxa_atexit`,
  `__cxa_finalize`, `__register_atfork`). It exports exactly one symbol, `PyInit__sodium`.
- **`libsodium.so` reaches `jniLibs` because it sits under `opt/`, not because anything
  special was done for it.** serious_python's Gradle step has a `copyOpt_<abi>` task that copies
  `**/*.so` out of each ABI's `opt/` directory straight into `src/main/jniLibs/<abi>`, flattened
  to the basename (`serious_python_android-4.5.1/android/build.gradle.kts:256`) — which is
  exactly the layout the `flet-libsodium` wheel installs. Separately, `splitSitePackages_<abi>`
  matches `nacl/_sodium.abi3.so` against its `\.(cpython-[^/]+|abi3)\.so$` tag, relocates it to
  `jniLibs/<abi>/libnacl-_sodium.so` (dots to dashes) and leaves a `nacl/_sodium.soref` marker
  in `sitepackages.zip` naming it. Read from serious_python's source, not from a built APK.
  The consequence to remember: **if the `flet-libsodium` wheel is missing from the resolve, the
  build succeeds and the import fails on device** with a linker error naming `libsodium.so`.
- **Native payload is 829,704 bytes per ABI** on cp314 arm64-v8a — `libnacl-_sodium.so`
  175,192, `libsodium.so` 351,904 and cffi's `lib_cffi_backend.so` 302,608 — plus one shared
  copy of the Python layer. armeabi-v7a is the smallest at 114,740 + 239,576 for the first two.
  Every `PT_LOAD` segment carries 16 KB alignment, which Android 15 requires; arm64-v8a and
  x86_64 are `ELF64`, armeabi-v7a and the legacy `x86` slice are genuine `ELF32`/`ARM` and
  `ELF32`/`i386` builds rather than stubs.
- **The hardware AES is compiled in; whether it is used is a runtime question.**
  Disassembling the arm64-v8a `libsodium.so` finds 1,418 `aese`, 1,337 `aesmc` and 436
  `pmull`/`pmull2` instructions — libsodium's ARMv8 crypto-extension implementations of AES-GCM
  and AEGIS — and the library exports `sodium_runtime_has_armcrypto` to decide at load time
  whether to use them. Nothing else is accelerated: on arm64 salsa20, chacha20, blake2b, argon2,
  ed25519 and x25519 come from the portable `*_ref*` objects and poly1305 from `poly1305_donna`,
  verified member by member in the iOS device archive, where all fifteen x86-specific objects
  (`libaesni_la-*`, `libsse2_la-*`, `libssse3_la-*`, `libsse41_la-*`, `libavx2_la-*`,
  `libavx512f_la-*`) are empty 808-byte stubs while
  `libarmcrypto_la-aead_aes256gcm_armcrypto.o` is 183,344 bytes of real code. The
  [example](examples/sealed-note) prints the runtime answer in its header.
- **The x86_64 emulator runs a differently optimised libsodium, so do not size a phone from
  it.** Disassembling the two Android libraries: the x86_64 `libsodium.so` carries 167
  `pmuludq`, 1,178 `paddq`, 1,093 `vpaddq` and 1,414 `vpxor` — the SSE2/AVX2 implementations
  libsodium ships for Salsa20, ChaCha20, BLAKE2b and Argon2 — where the arm64-v8a library
  carries none of them and runs the portable objects instead. **AES is the one thing both
  have.** The x86_64 library carries 1,718 `vaesenc` and 490 `vpclmulqdq` — the VEX encodings
  of AES-NI and carry-less multiply — and the iOS x86_64 simulator's static archive holds
  `libaesni_la-aead_aes256gcm_aesni.o` at 151,992 bytes of real code where the arm64 archive
  has an 808-byte stub, exactly reversing the arm64 picture. **Grepping for the legacy `aesenc`
  and `pclmulqdq` spellings finds zero everywhere and is the wrong question**; on the iOS
  slices, which absorb the archive, the count is visible in the extension itself — 1,718
  `vaesenc` in the x86_64 simulator's `_sodium.abi3.so` against 1,418 `aese` in the device's.
  The only library here with no accelerated AES at all is 32-bit `armeabi-v7a`, which has zero
  of every one of those mnemonics. An emulator and a phone will still disagree about every
  *other* primitive, which is why the [example](examples/sealed-note) times them where they
  run.

## iOS notes

- **The extension is self-contained, and that is why it is three times the size.** `otool -hv`
  reports `MH_DYLIB` with the `NOUNDEFS` flag on all nine iOS slices — so the *Unsupported
  mach-o filetype (only MH_OBJECT and MH_DYLIB can be linked)* failure does not arise, and
  there is no libsodium to find at runtime. `otool -L` lists exactly two dependencies besides
  the extension's own install name: `@rpath/Python.framework/Python` and
  `/usr/lib/libSystem.B.dylib`. The static `libsodium.a` is absorbed, so `_sodium.abi3.so` is
  569,952 bytes on the cp314 device slice against 175,192 on Android arm64-v8a, and 677,904 on
  the x86_64 simulator.
- **It exports the whole libsodium C API.** 492 global symbols on the device and arm64-simulator
  slices: `PyInit__sodium` plus 491 `crypto_*` / `sodium_*` / `randombytes*` entries, because the
  static archive is linked in with default visibility. Costs nothing and nothing on the Python
  side reaches them; worth knowing only if you ever wonder whether a second extension could link
  against this one. The x86_64 simulator slice exports 477, the missing fifteen being the
  `crypto_core_salsa20` / `salsa2012` / `salsa208` family, which that build does not pull out of
  the archive because its SSE2 stream implementation does not reference it. Android exports
  exactly one symbol, so the two platforms differ here by 491.
- **The `flet-libsodium` wheel still ships you a shared library nothing loads.** Its iOS wheels
  contain `libsodium.so` at the root (458,648 B on device, 447,184 on the arm64 simulator,
  561,672 on the x86_64 simulator) alongside the `opt/lib/libsodium.a` and headers the build
  actually consumed. `flet build`'s package step deletes `**.a` and `**.h` as junk — 1,978,368
  and 166,485 bytes gone — but a root-level `.so` is not junk, and serious_python's
  `sync_site_packages.sh` converts *every* `.so` under site-packages into a framework, so the
  app ends up carrying a `libsodium` framework it never dlopens. flet_cli 0.86.5 does read a
  per-platform cleanup table (`tool.flet.<platform>.cleanup.package_files`, `build_base.py:2454`),
  so `[tool.flet.ios.cleanup]` is the place to drop it without touching Android — where the same
  basename is load-bearing. **That glob has not been verified against a build here**; check the
  result before relying on it, and note the same reasoning says the pure-Python `cffi` package
  and `pycparser` are also dead weight (see [Things to know](#things-to-know)).
- **This is cryptography, and App Store Connect asks.** Unlike a hash library, shipping PyNaCl
  puts encryption in your binary, so `ITSAppUsesNonExemptEncryption` in `Info.plist` is a
  question you have to answer rather than ignore. Standard, published algorithms used for an
  app's own data are the ordinary case, but the declaration is still yours to make.

## Things to know

- **Every ciphertext carries its own authenticator, and a damaged one raises rather than
  decoding.** The measurement is at the top of this page: 3,200 single-bit flips across
  `SecretBox`, `Box`, `SealedBox` and an Ed25519 signed message produced 3,200 exceptions and
  zero decodes on desktop. Truncation is caught too, though less gracefully — cutting a
  `SecretBox` message to 20 bytes raises `ValueError: The nonce must be exactly 24 bytes long`
  rather than a `CryptoError`. A wrong key gives
  `CryptoError: Decryption failed. Ciphertext failed verification`, a wrong `SealedBox`
  recipient gives `CryptoError: An error occurred trying to decrypt the message`, and a wrong
  signer gives `BadSignatureError: Signature was forged or corrupt`.
- **The failure authentication does *not* cover is nonce reuse, and it is silent and total.**
  Encrypting two messages under one key with the same 24-byte nonce leaks their XOR: measured on
  desktop, the XOR of the two ciphertext bodies equalled the XOR of the two plaintexts exactly,
  so knowing `b"transfer 100 to alice"` recovered `b"transfer 900 to carol"` byte for byte —
  and both messages still decrypted normally, with nothing raised anywhere. **Let
  `encrypt()` generate the nonce**: called without one it draws 24 fresh bytes from
  `os.urandom`, and two calls on the same plaintext produced different ciphertexts. If you must
  supply nonces yourself, a counter that can never repeat for a key is the only safe shape, and
  24 bytes is wide enough that random ones are fine.
- **Argon2id's presets are sized for servers, and one of them will get your app killed.**
  `MEMLIMIT_INTERACTIVE` is 64 MiB over 2 passes, `MEMLIMIT_MODERATE` is 256 MiB over 3, and
  `MEMLIMIT_SENSITIVE` is **1 GiB** over 4 — one allocation, live for the duration. On desktop
  those took 357 ms and 2,230 ms for the first two. Interactive is the sane mobile default and
  is what `nacl.pwhash.str()` uses (its output records `m=65536,t=2,p=1`); treat moderate as
  something to measure on your slowest device before shipping, and do not reach for sensitive at
  all. **PyNaCl's own bounds check will not save you**: `MEMLIMIT_MAX` is 4,398,046,510,080
  bytes, so an 8 GiB request is accepted and simply runs — on this desktop it had not returned
  after two minutes and had to be killed. Below the floor it does raise, cleanly:
  `ValueError: memlimit must be at least 8192 bytes` and
  `ValueError: opslimit must be at least 1`.
- **Argon2 has no password-length limit**, which is a real difference from bcrypt: a 400-byte
  passphrase hashed here in 371 ms and verified in 374 ms, where [`bcrypt`](../bcrypt) 5.0.0
  raises above 72 bytes rather than truncating. If you are moving an app off bcrypt, that
  restriction disappears and the stored-hash format changes — `$argon2id$v=19$…`, 97 bytes,
  against bcrypt's 60 — so plan the migration as a re-hash on next successful login.
  `nacl.pwhash.verify` rejects the other format outright with
  `CryptPrefixError: given password_hash is not in a supported format`.
- **`except CryptoError` does not mean "authentication failed".** `nacl.exceptions.TypeError`
  and `nacl.exceptions.ValueError` inherit from *both* the builtin and `CryptoError`, so a
  32-byte key passed as `str` raises something a `except CryptoError:` block will happily
  swallow as if the message had been tampered with. The real hierarchy is
  `BadSignatureError` → `CryptoError`, `InvalidkeyError` → `CryptoError`, `CryptPrefixError` →
  `InvalidkeyError`, and `UnavailableError` → `nacl.exceptions.RuntimeError` → builtin
  `RuntimeError` → `CryptoError`. Catch the specific class, and catch *something* — an unhandled
  exception in a Flet event handler ends the session with a crash screen.
- **Type errors surface as cffi's own message, not as a Python one.** `signing_key.sign("text")`
  raises `TypeError: initializer for ctype 'unsigned char *' must be a bytes or list or tuple,
  not str`, which is the binding layer talking. Encode before you call. Where PyNaCl checks
  first, the message is much better: `SecretBox("x" * 32)` gives
  `TypeError: SecretBox must be created from 32 bytes` and `SecretBox(b"x" * 31)` gives
  `ValueError: The key must be exactly 32 bytes long`.
- **`nacl.hash` returns hex, not bytes.** `nacl.hash.blake2b(b"abc")` is 64 bytes of ASCII hex
  because the default encoder is `HexEncoder`; pass `encoder=nacl.encoding.RawEncoder` for the
  32 raw bytes. The same default applies to `sha256`, `sha512` and `siphash24`, and it is the
  opposite of `hashlib`, whose `digest()` is raw and whose `hexdigest()` is explicit. Verified
  that `nacl.hash.sha256` and `hashlib.sha256` agree on the same input once the encodings match.
- **AES-GCM and AEGIS are exposed but have no public availability check.** 1.6.2 added
  `crypto_aead_aes256gcm_*` and `crypto_aead_aegis128l/256_*` to `nacl.bindings`, and libsodium
  requires you to call `crypto_aead_aes256gcm_is_available()` before using the first of them —
  but `nacl.bindings` does not export a wrapper for it, so the only way to ask is the raw handle,
  `from nacl._sodium import lib; lib.crypto_aead_aes256gcm_is_available()`. That returned **0**
  on the PyPI desktop wheel on Apple Silicon — and not because the CPU lacks AES
  (`sysctl hw.optional.arm.FEAT_AES` is 1 on an M4) but because that wheel's bundled libsodium
  has no AES implementation compiled in at all: neither slice of the `universal2` binary holds
  a single `aese` or `vaesenc`. **The desktop answer therefore says nothing about the phone**,
  whose libsodium does carry them — see [Android notes](#android-notes). The
  [example](examples/sealed-note) prints the device's answer. Unless you have a specific reason
  to want AES, `SecretBox` and the XChaCha20-Poly1305 AEAD need no such check and work
  everywhere.
- **Both sides link libsodium 1.0.20, and you cannot ask which.** PyNaCl 1.6.2's sdist vendors
  libsodium 1.0.20 (`AC_INIT([libsodium],[1.0.20]…)` in the bundled `configure.ac`) and the
  `flet-libsodium` wheel this recipe substitutes builds the same release, so mobile and desktop
  agree by version rather than by luck. There is no way to confirm that from Python:
  `sodium_version_string` is not in PyNaCl's cdef, and
  `nacl.bindings.sodium_version_string` does not exist. `Requires-Dist:
  flet-libsodium (==1.0.20)` in the wheel metadata is the checkable record.
- **`compile.packages` costs you more bytes than the source suggests, and about half of them
  are never imported.** The Python layer is 233,313 bytes of source, which compiles to roughly
  302,000 bytes of `.pyc` under CPython 3.14 — the exact total swings a kilobyte with the
  install path, because every `.pyc` records it in `co_filename` (301,590 under a one-character
  directory, 302,880 under a 44-character one). Flet compiles packages by default and ships no
  `.py` beside them, so `__file__` on any `nacl` module points at a `.pyc` on **both**
  platforms. Harmless here, since nothing in the package reads it. What is less harmless is the
  dependency: importing every public PyNaCl module loads `_cffi_backend` but leaves `cffi` and
  `pycparser` out of `sys.modules` entirely, so the `cffi` package's Python half — 331,951 bytes
  in the 2.0.0 Android resolves to, 337,601 in the 2.1.1 iOS gets — and `pycparser`'s 188,588
  are payload nothing runs, unless something *else* in your app builds an FFI at runtime.
- **Key material is bytes and nothing else.** `bytes(signing_key)` is a 32-byte seed,
  `bytes(verify_key)` a 32-byte public key, and the same for the X25519 pair — no PEM, no DER,
  no password-protected container. `key.encode(encoder=nacl.encoding.HexEncoder)` and the
  `Base64Encoder` / `URLSafeBase64Encoder` variants are there when a key has to travel as text.
  Comparison is by value (`VerifyKey` reconstructed from bytes compares equal), and
  `nacl.bindings.sodium_memcmp` is the constant-time comparison for anything secret.
- **Python 3.14 does not make this redundant.** The standard library gained no asymmetric
  cryptography; `hashlib.scrypt` and `hashlib.blake2b(key=…)` overlap the password and MAC
  corners, and everything else here has no stdlib equivalent.

## Build notes (maintainers)

The recipe is a version, a build number, one host requirement and one patch. The host
requirement is what makes it work: `flet-libsodium 1.0.20` puts a cross-compiled libsodium into
the cross environment as `opt/include` + `opt/lib`, and forge adds those to `CFLAGS`/`LDFLAGS`,
so cffi's `ffi.set_source("_sodium", …, libraries=["sodium"])` finds `sodium.h` and `-lsodium`
without knowing anything about the target. `patches/mobile.patch` exists only to stop upstream's
`setup.py` building the libsodium it vendors, and explains itself in its own preamble —
including the alternative (`SODIUM_INSTALL=system` via `build.script_env`) that would have done
the same job without a patch.

The one number that must move in lockstep is libsodium's. Upstream vendors 1.0.20 in the 1.6.2
sdist and `flet-libsodium` builds 1.0.20; a PyNaCl release that vendors a newer libsodium and
uses a symbol the older one lacks will fail at link time rather than silently, but it will fail,
and the fix is a `flet-libsodium` bump first.

Two observations from the published wheels that have no other home:

- **The extension is `_sodium.abi3.so` on every slice, which forge's foreign-arch guard cannot
  see.** That guard drops stale extensions left in a reused source tree by matching
  `\.cpython-\d+-<triplet>\.so$` (`src/forge/build.py:896`), and an `abi3` name never matches
  it. What protects this recipe instead is that the name is *identical* across ABIs, so each
  slice's build overwrites the previous one rather than accumulating beside it. Verified rather
  than assumed: the `e_machine` of all ten Android slices was checked and each is the right
  architecture (`AArch64`, `ARM`, `i386`, `x86-64`). If a future build ever produces
  per-triplet names here, the guard starts applying and this note stops mattering; if the wheels
  ever import on one ABI and not another, this is the first thing to look at.
- **The wheels' `.py` files are byte-identical to the sdist**, all 30 of them, so the patch
  changes only what it says it changes and nothing about the package's behaviour is this
  recipe's doing.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **That the Android extension still names `libsodium.so` in `DT_NEEDED` and the iOS one still
  reports `NOUNDEFS`.** The two platforms link the same recipe differently, and
  [Install](#install) and both platform sections rest on that split. A build that quietly
  static-linked on Android, or dynamic-linked on iOS, would pass every test in `tests/` and
  break on device.
- **That `METADATA` still carries `flet-libsodium (==1.0.20)` at the bumped version.** It is
  appended from `requirements.host`, so it follows the recipe automatically — but it is what
  puts `libsodium.so` in the app, and an app that resolves without it fails at import.
- **The GIL release**, since [Threading](#threading) rests on it and the 3.2× parallel speedup
  follows from it: grep the new slices' undefined symbols for `PyEval_SaveThread`. cffi has
  released the GIL around generated calls for a long time, so this is a regression check rather
  than a likely change.
- **The Argon2id preset values**, which [Things to know](#things-to-know) quotes in mebibytes
  and which are libsodium's rather than PyNaCl's. Read them out of the built wheel
  (`argon2id.MEMLIMIT_*`), not out of the docs.
- **Whether upstream has started publishing mobile wheels.** 1.6.2 is 25 files on PyPI with no
  Android or iOS tag among them, which is what makes a bare `pynacl` resolve from this index
  everywhere; the day that changes, this recipe may stop being needed — and the shape of the
  question changes with it, since upstream's wheels would bundle their own libsodium rather
  than link ours.

`tests/test_pynacl.py` is two functions with docstrings and no version assertion, in line with
the repo's conventions: a `SecretBox` round trip and an Ed25519 sign/verify round trip. Three
gaps are worth closing at the next touch, in order of value. **Nothing tests `nacl.pwhash`**,
which is the heaviest code path in the library and the one most likely to expose a libsodium
that built wrong — a single `argon2id.kdf` at `OPSLIMIT_MIN`/`MEMLIMIT_MIN` costs under a
millisecond and would cover it. **Nothing asserts that tampering raises**: the signing test
carries a comment saying verification raises `BadSignatureError` on tamper, but never flips a
bit to prove it, and that assertion is the central claim of this page. And **nothing exercises
the public-key half** — `SealedBox` is the one primitive whose failure would implicate the
X25519 code specifically, and `to_curve25519_private_key()` is the conversion the
[example](examples/sealed-note) depends on.
