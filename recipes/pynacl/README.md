# pynacl

[`PyNaCl`](https://github.com/pyca/pynacl) is the Python binding for
[libsodium](https://doc.libsodium.org/), the maintained fork of Daniel Bernstein's NaCl. It
gives a Flet app the four things an offline device usually needs and cannot get from the
standard library: [Ed25519](https://pynacl.readthedocs.io/en/latest/signing/) signatures,
[X25519](https://pynacl.readthedocs.io/en/latest/public/) key agreement,
[authenticated symmetric encryption](https://pynacl.readthedocs.io/en/latest/secret/) with
XSalsa20-Poly1305, and [Argon2](https://pynacl.readthedocs.io/en/latest/password_hashing/)
password hashing. `hashlib` has SHA-2, BLAKE2 and `scrypt`, and `hmac` authenticates with a
shared key — but nothing in the standard library signs, agrees a key with a stranger, or
encrypts.

Two properties make it the one to reach for on a phone. Every primitive here is
**authenticated**, so a damaged ciphertext raises instead of decoding to something plausible.
And Curve25519 needs no big-integer library, no parameter files and no `libgmp`, so signing
and key agreement work with nothing but this wheel and the libsodium it links.

## Install

Add PyNaCl to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pynacl",
]
```

**The distribution is `pynacl` and the module is `nacl`** — `import nacl.signing`, and nothing
anywhere imports `pynacl`.

Keep the entry in top-level `[project] dependencies`. `flet build` resolves for the build host
first and PyPI publishes a desktop wheel for every host you would build from, so one line
covers `flet run` on your laptop and `flet build` for a device.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`sealed-note`](examples/sealed-note) — a note sealed under a passphrase and under a public
  key, signed, reopened, then attacked one bit at a time.

## Usage in a Flet app

An identity is 32 bytes, so persisting one is a file rather than a serialization format. Load
or create it, seal something under a passphrase, sign the result, and put it on screen:

```python
import os

import flet as ft
import nacl.secret
import nacl.signing
import nacl.utils
from nacl.pwhash import argon2id

path = os.path.join(os.environ["FLET_APP_STORAGE_DATA"], "identity.key")
try:
    with open(path, "rb") as handle:
        signing_key = nacl.signing.SigningKey(handle.read(32))
except OSError:
    signing_key = nacl.signing.SigningKey.generate()
    with open(path, "wb") as handle:
        handle.write(bytes(signing_key))
    os.chmod(path, 0o600)

salt = nacl.utils.random(argon2id.SALTBYTES)  # not a secret; store it with the ciphertext
key = argon2id.kdf(
    nacl.secret.SecretBox.KEY_SIZE,
    passphrase.encode(),
    salt,
    opslimit=argon2id.OPSLIMIT_INTERACTIVE,
    memlimit=argon2id.MEMLIMIT_INTERACTIVE,
)
sealed = bytes(nacl.secret.SecretBox(key).encrypt(note.encode()))  # nonce chosen for you
signature = signing_key.sign(salt + sealed).signature

page.add(ft.Text(f"{len(sealed)} B sealed by {bytes(signing_key.verify_key)[:8].hex()}"))
```

Opening it is the same calls in reverse — `verify_key.verify(salt + sealed, signature)`, then
`argon2id.kdf` with the stored salt, then `SecretBox(key).decrypt(sealed)`. Verify first: it
costs a fraction of a millisecond and rejects anything the signer did not assemble, which
saves running a memory-hard KDF over bytes already known to be wrong.

### Storage

**PyNaCl has no config directory, no cache and no state.** The Python layer's only filesystem
call is `os.urandom`; underneath, libsodium's generator reaches `getrandom(2)` on Android and
`/dev/urandom` on iOS, both of which the sandbox always grants. There is nothing to configure.

What you do have to place is key material, and it is refreshingly plain: an Ed25519 signing
key is 32 raw bytes, an X25519 private key is 32, and `bytes(key)` is the whole serialization
format. A 32-byte file under
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is the whole of persisting an identity, as in the snippet above.

**One X25519 key pair comes free with it.** `signing_key.to_curve25519_private_key()` converts
the Ed25519 key to its Curve25519 twin and `verify_key.to_curve25519_public_key()` does the
public half, so one stored secret covers signing *and*
[sealed boxes](https://pynacl.readthedocs.io/en/latest/public/#nacl.public.SealedBox).

**Do not write the key beside `main.py`.** With `[tool.flet.app] path = "src"` the whole
`src/` directory is packaged into the app, so a key file created there during a desktop
`flet run` ships inside the next build.

**There is no OS keychain here.** The storage surface Flet 0.86.5 exposes is
[`ft.StoragePaths`](https://flet.dev/docs/controls/storagepaths/) and
[`ft.SharedPreferences`](https://flet.dev/docs/controls/sharedpreferences/), with nothing
Keychain- or Keystore-shaped beside them, so a key in app storage is protected by the app
sandbox and by device encryption and by nothing else. If the threat model needs
hardware-backed storage, the key has to be held on the platform side.

One surprise worth knowing: **`nacl.utils.random()` is a one-line wrapper around
`os.urandom`**, not around libsodium's `randombytes`. Every key and nonce PyNaCl generates for
you goes through CPython — `SigningKey.generate()`, `PrivateKey.generate()` and the automatic
nonce in `SecretBox.encrypt()`. `nacl.bindings.randombytes()` reaches libsodium's own
generator if you want it.

### Threading

**The bindings release the GIL**, which makes this package unlike most compiled wheels on this
index: cffi wraps `Py_BEGIN_ALLOW_THREADS` around the generated C call. Measured on a desktop
against a counter thread whose rate is read as a percentage of an idle window,
`argon2id.kdf`, a 48 MiB `SecretBox.encrypt` and 2,000 consecutive Ed25519 verifies all left
the counter at 90–119%, where a GIL-holding extension (`math.factorial(60000)`) drops it to
11–22%. Four concurrent `argon2id.kdf` calls at the interactive preset finished in 464 ms
against 1,490 ms for the same four serially — 3.2× on four performance cores, where a
GIL-holding extension would have shown 1.0×.

**Budget the memory before the cores, though.** Argon2id is memory-hard on purpose, so *N*
threads at the interactive preset need *N* × 64 MiB resident at once, and at the moderate
preset *N* × 256 MiB. Two concurrent moderate derivations are half a gigabyte of live
allocation in an app process, which is a way to get killed on Android rather than a way to go
faster. One worker is the right default; parallelism is for verifying a batch, not for hashing
one password.

The Flet-side rules apply as everywhere else. A
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) worker must
end with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update),
because auto-update does not reach background threads; and its body must be wrapped in
`try`/`except`, because `run_thread` never retrieves the worker's future and discards whatever
it raised — with no log, no dialog and no crash.

**Sharing one key object across threads is safe.** A `SecretBox`, `SigningKey`, `VerifyKey`,
`PrivateKey` or `PublicKey` holds bytes and nothing mutable, and each call allocates its own
output buffer. Measured on desktop over five runs: eight threads pushing 2,000 messages
through one shared `SecretBox`, and eight signing and verifying through one shared key pair,
completed every message with nothing raised. `SecretStream` is the exception in the API — it
*is* a running state machine — and one of those belongs to one thread.

### Cost of each operation

Measured on an otherwise idle desktop (Apple M4, CPython 3.14.6), best per-call time of three
runs of the [example](examples/sealed-note)'s own `costs()`; a loaded machine moved every row
by up to 8%:

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

Read that as the shape rather than the ceiling, and expect a phone to be slower. The shape is
what carries: public-key work is hundreds of microseconds a call and symmetric work is tens, so
a screen that verifies a hundred signatures is doing real work while one that decrypts a
hundred short messages is not. Bulk throughput is the weak axis — on the same desktop, OpenSSL
through [`cryptography`](../cryptography) verified Ed25519 in 156.9 µs against libsodium's
473.3 and moved ChaCha20-Poly1305 at 2,175 MB/s against `SecretBox`'s 77 MB/s over 1 MiB — and
the gap follows the phone, because libsodium's only arm64 assembly is for AES-GCM and AEGIS.
Salsa20, ChaCha20, Poly1305, BLAKE2b, Ed25519 and X25519 all run portable C on every arm64
target, which is every real device. Choose PyNaCl for the primitives and the API, not for
throughput on bulk data.

**Do not size Argon2 parameters from an emulator.** The same interactive profile — 2 passes
over 64 MiB — took **65 ms to seal on an iPhone 16 simulator and 5,921 ms on an arm64-v8a
Android 14 emulator**, and the example's whole pass 210 ms against 25,127 ms. Argon2id is
deliberately memory-hard, which is exactly what an emulated memory subsystem is worst at, and
the simulator figure is your Mac's own CPU, so neither number is a phone's. Pick the preset on
hardware you can hold.

### App size

Approximately 90–310 KB compressed and 360–930 KB unpacked per slice. Everything native an
Android app ends up carrying for it comes to around 830 KB per ABI, and `armeabi-v7a` is the
smallest of them; on iOS it is one self-contained extension of roughly 570–680 KB. PyNaCl is
therefore never the reason to reach for an app bundle, split APKs or a
narrowed [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
— every Android ABI and every iOS slice is published, so those levers stay available for
whatever else the app carries.

### Other considerations

- **The desktop wheel is not the same libsodium build.** One `cp38-abi3` wheel serves CPython
  3.8 through 3.14, so `flet run` gets exactly the API you ship — but not the same compiled-in
  features. The macOS `universal2` wheel has no AES implementation in it at all (neither slice
  holds a single `aese` or `vaesenc` instruction), so
  `crypto_aead_aes256gcm_is_available()` answers 0 on a CPU that certainly has AES, while every
  64-bit mobile slice does carry one. Anything AES-shaped has to be validated on a device.
- **An x86_64 emulator or simulator runs a differently optimised libsodium.** Those builds
  carry the SSE2/AVX2 implementations of Salsa20, ChaCha20, BLAKE2b and Argon2, which the
  arm64 builds do not have, and AES-NI where arm64 has the ARMv8 crypto extensions. A ratio
  measured on x86 is not a phone's. 32-bit `armeabi-v7a` has no accelerated AES at all.
- **This is cryptography, and App Store Connect asks.** Unlike a hash library, shipping PyNaCl
  puts encryption in your binary, so `ITSAppUsesNonExemptEncryption` in `Info.plist` is a
  question you have to answer rather than ignore. Standard, published algorithms used for an
  app's own data are the ordinary case, but the declaration is still yours to make.

## Things to know

- **Every ciphertext carries its own authenticator, and a damaged one raises rather than
  decoding.** Measured on desktop by flipping every bit in turn: 736 of 736 flips of a
  `SecretBox` message, 736 of 736 of a `Box` message, 800 of 800 of a `SealedBox` message and
  928 of 928 of an Ed25519 signed message raised — 3,200 corrupted messages, 3,200 exceptions,
  nothing decoded to anything. An arm64-v8a Android 14 emulator and an iPhone 16 simulator
  answered the same way on 2026-08-20: 1,792 single-bit forgeries against a secretbox, a
  sealedbox and a signature, and not one of them decoded on either platform. That is not how a
  serialization format behaves — the same sweep against [`msgpack`](../msgpack), every one of
  the 432 bits of the 54-byte frame `msgpack.packb(b"x" * 52)`, raised 16 times and **silently
  handed back a value the other 416**, none of them the original. Truncation is caught too,
  though less gracefully: cutting a `SecretBox` message to 20 bytes gives
  `ValueError: The nonce must be exactly 24 bytes long` rather than a `CryptoError`. A wrong
  key gives `CryptoError: Decryption failed. Ciphertext failed verification`, a wrong
  `SealedBox` recipient `CryptoError: An error occurred trying to decrypt the message`, and a
  wrong signer `BadSignatureError: Signature was forged or corrupt`.
- **The failure authentication does *not* cover is nonce reuse, and it is silent and total.**
  Encrypting two messages under one key with the same 24-byte nonce leaks their XOR: measured
  on desktop, the XOR of the two ciphertext bodies equalled the XOR of the two plaintexts
  exactly, so knowing `b"transfer 100 to alice"` recovered `b"transfer 900 to carol"` byte for
  byte — and both messages still decrypted normally, with nothing raised anywhere. **Let
  `encrypt()` generate the nonce**: called without one it draws 24 fresh bytes from
  `os.urandom`, and two calls on the same plaintext produce different ciphertexts. If you must
  supply nonces yourself, a counter that can never repeat for a key is the only safe shape, and
  24 bytes is wide enough that random ones are fine.
- **Argon2id's presets are sized for servers, and one of them will get your app killed.**
  `MEMLIMIT_INTERACTIVE` is 64 MiB over 2 passes, `MEMLIMIT_MODERATE` is 256 MiB over 3, and
  `MEMLIMIT_SENSITIVE` is **1 GiB** over 4 — one allocation, live for the duration. On desktop
  the first two took 357 ms and 2,230 ms. Interactive is the sane mobile default and is what
  `nacl.pwhash.str()` uses (its output records `m=65536,t=2,p=1`); treat moderate as something
  to measure on your slowest device before shipping, and do not reach for sensitive at all.
  **The bounds check will not save you**: `MEMLIMIT_MAX` is 4,398,046,510,080 bytes, so an
  8 GiB request is accepted and simply runs — on this desktop it had not returned after two
  minutes and had to be killed. Below the floor it does raise, cleanly:
  `ValueError: memlimit must be at least 8192 bytes` and
  `ValueError: opslimit must be at least 1`.
- **Argon2 has no password-length limit**, which is a real difference from bcrypt: a 400-byte
  passphrase hashed here in 371 ms and verified in 374 ms, where [`bcrypt`](../bcrypt) raises
  above 72 bytes rather than truncating. If you are moving an app off bcrypt that restriction
  disappears and the stored-hash format changes — `$argon2id$v=19$…`, 97 bytes, against
  bcrypt's 60 — so plan the migration as a re-hash on next successful login.
  `nacl.pwhash.verify` rejects the other format outright with
  `CryptPrefixError: given password_hash is not in a supported format`.
- **`except CryptoError` does not mean "authentication failed".** `nacl.exceptions.TypeError`
  and `nacl.exceptions.ValueError` inherit from *both* the builtin and `CryptoError`, so a
  32-byte key passed as `str` raises something an `except CryptoError:` block will happily
  swallow as if the message had been tampered with. The real hierarchy is `BadSignatureError` →
  `CryptoError`, `InvalidkeyError` → `CryptoError`, `CryptPrefixError` → `InvalidkeyError`, and
  `UnavailableError` → `nacl.exceptions.RuntimeError` → builtin `RuntimeError` → `CryptoError`.
  Catch the specific class, and catch *something* — an unhandled exception in a Flet event
  handler ends the session with a crash screen.
- **Type errors surface as cffi's own message, not as a Python one.** `signing_key.sign("text")`
  raises `TypeError: initializer for ctype 'unsigned char *' must be a bytes or list or tuple,
  not str`, which is the binding layer talking. Encode before you call. Where PyNaCl checks
  first the message is much better: `SecretBox("x" * 32)` gives
  `TypeError: SecretBox must be created from 32 bytes` and `SecretBox(b"x" * 31)` gives
  `ValueError: The key must be exactly 32 bytes long`.
- **`nacl.hash` returns hex, not bytes.** `nacl.hash.blake2b(b"abc")` is 64 bytes of ASCII hex
  because the default encoder is `HexEncoder`; pass `encoder=nacl.encoding.RawEncoder` for the
  32 raw bytes. The same default applies to `sha256`, `sha512` and `siphash24`, and it is the
  opposite of `hashlib`, whose `digest()` is raw and whose `hexdigest()` is explicit.
- **AES-GCM and AEGIS are exposed but have no public availability check.**
  `nacl.bindings` carries `crypto_aead_aes256gcm_*` and `crypto_aead_aegis128l/256_*`, and
  libsodium requires `crypto_aead_aes256gcm_is_available()` to be called before the first of
  them — but no wrapper is exported for it, so the only way to ask is the raw handle,
  `from nacl._sodium import lib; lib.crypto_aead_aes256gcm_is_available()`. The
  [example](examples/sealed-note) prints the device's answer in its header. Unless you have a
  specific reason to want AES, `SecretBox` and the XChaCha20-Poly1305 AEAD need no such check
  and work everywhere.
- **Key material is bytes and nothing else.** `bytes(signing_key)` is a 32-byte seed,
  `bytes(verify_key)` a 32-byte public key, and the same for the X25519 pair — no PEM, no DER,
  no password-protected container. `key.encode(encoder=nacl.encoding.HexEncoder)` and the
  `Base64Encoder` / `URLSafeBase64Encoder` variants are there when a key has to travel as text.
  Comparison is by value (a `VerifyKey` reconstructed from bytes compares equal), and
  `nacl.bindings.sodium_memcmp` is the constant-time comparison for anything secret.
- **You cannot ask which libsodium you have.** `sodium_version_string` is not in PyNaCl's cdef
  and `nacl.bindings.sodium_version_string` does not exist, so there is no runtime way to
  confirm the library underneath. The `Requires-Dist` line in the wheel metadata is the
  checkable record, and it is a build-time fact rather than something the app can assert.
- **Python 3.14 does not make this redundant.** The standard library gained no asymmetric
  cryptography; `hashlib.scrypt` and `hashlib.blake2b(key=…)` overlap the password and MAC
  corners, and everything else here has no stdlib equivalent.

## Build notes (maintainers)

### Recipe shape

The recipe is a version, a build number, one host requirement and one patch, and the host
requirement is what makes it work: `flet-libsodium` puts a cross-compiled libsodium into the
cross environment as `opt/include` + `opt/lib`, forge adds those to the compile env, and cffi's
`ffi.set_source("_sodium", …, libraries=["sodium"])` finds `sodium.h` and `-lsodium` without
knowing anything about the target. `patches/mobile.patch` explains itself in its own preamble.

**The two platforms link the same recipe differently, and every platform-specific claim above
rests on that split.** On Android the extension names `libsodium.so` in `DT_NEEDED`; that file
reaches `jniLibs` only because it sits under `opt/`, which serious_python's `copyOpt_<abi>`
Gradle task copies wholesale into `src/main/jniLibs/<abi>`, flattened to the basename
(`serious_python_android-4.5.1/android/build.gradle.kts:256`). Separately
`splitSitePackages_<abi>` matches `nacl/_sodium.abi3.so` against its `\.(cpython-[^/]+|abi3)\.so$`
tag, relocates it to `jniLibs/<abi>/libnacl-_sodium.so` and leaves a `nacl/_sodium.soref`
marker naming it. The consequence: **if the `flet-libsodium` wheel is missing from the resolve,
the Android build succeeds and the import fails on device** with a linker error naming
`libsodium.so`. On iOS the static archive is absorbed instead — the extension is `MH_DYLIB`
with `NOUNDEFS`, exports the whole libsodium C API (492 globals on the device slice, 477 on the
x86_64 simulator, against exactly one on Android) and is about three times the Android
extension's size.

The iOS half of the `flet-libsodium` wheel also ships a root-level `libsodium.so` that nothing
loads, and serious_python's `sync_site_packages.sh` turns every `.so` under site-packages into
a framework, so an iOS app carries a `libsodium` framework it never dlopens.
`[tool.flet.ios.cleanup] package_files` (flet_cli `build_base.py:2454`) is where that could be
dropped without touching Android — **never verified against a build here**, and it would break
an app that also uses [`pysodium`](../pysodium), which resolves that very file through ctypes.

Two more observations from the published wheels that have no other home:

- **The extension is `_sodium.abi3.so` on every slice, which forge's foreign-arch guard cannot
  see.** That guard drops stale extensions left in a reused source tree by matching
  `\.cpython-\d+-<triplet>\.so$` (`src/forge/build.py:896`), and an `abi3` name never matches
  it. What protects this recipe instead is that the name is *identical* across ABIs, so each
  slice's build overwrites the previous one rather than accumulating beside it. Verified rather
  than assumed: the `e_machine` of every Android slice is the right architecture. Do not read
  `abi3` as "one wheel for every Python" either — each Android slice names its own
  `libpython3.<minor>.so` and each iOS slice its own framework compatibility version.
- **The wheels' `.py` files are byte-identical to the sdist**, so the patch changes only what
  it says it changes.

**Where libsodium's accelerated code actually is**, since the consumer sections rest on it: the
arm64 builds carry the ARMv8 AES-GCM and AEGIS implementations only (1,418 `aese` in the
arm64-v8a `libsodium.so`) and run the portable `*_ref*` objects plus `poly1305_donna` for
everything else, while the x86_64 builds carry the SSE2/AVX2 objects and AES-NI (1,718
`vaesenc`). The iOS static archives show it member by member: `libaesni_la-*`, `libsse2_la-*`
and `libavx2_la-*` are 808-byte stubs on arm64 and real code on x86_64, with
`libarmcrypto_la-aead_aes256gcm_armcrypto.o` reversing it. Grepping for the legacy
`aesenc`/`pclmulqdq` spellings finds zero everywhere and is the wrong question.

### Upgrade hazards

- **libsodium's version must move in lockstep.** Upstream vendors a libsodium release in the
  sdist and `flet-libsodium` builds one of its own; a PyNaCl release that vendors a newer
  libsodium and calls a symbol the older one lacks fails at link time rather than silently, but
  it does fail, and the fix is a `flet-libsodium` bump first.
- **The Argon2id preset values are libsodium's, not PyNaCl's**, and the consumer sections quote
  them in mebibytes. Read them out of the built wheel (`argon2id.MEMLIMIT_*`,
  `argon2id.OPSLIMIT_*`), not out of the docs.
- **Which `cffi` resolves varies across the iOS slices**, because upstream publishes iOS cffi
  wheels for some interpreter/arch combinations and not others; the rest fall back to this
  index. All of them must still satisfy the `cffi` floor in `METADATA` and ship the
  `_cffi_backend` extension that `nacl._sodium` imports at load time.
- **Upstream publishing mobile wheels changes the shape of the question**, not just the need
  for the recipe: their wheels would bundle their own libsodium rather than link ours, so the
  Android `DT_NEEDED` story and the size figures would both move.

### Re-verification checklist

- **That a bare `pynacl` still resolves from this index on every mobile target.** Check with
  `pip download --only-binary :all:` using `--index-url https://pypi.org/simple --extra-index-url
  https://pypi.flet.dev/`, which is the order serious_python uses, across the eighteen
  combinations: arm64-v8a, armeabi-v7a and x86_64 on Android, device and both simulators on
  iOS, times Python 3.12, 3.13 and 3.14.
- **That the Android extension still names `libsodium.so` in `DT_NEEDED` and the iOS one still
  reports `NOUNDEFS`.** A build that quietly static-linked on Android, or dynamic-linked on
  iOS, would pass every test in `tests/` and break on device.
- **That `METADATA` still carries the `flet-libsodium` pin at the bumped version.** It is
  appended from `requirements.host`, so it follows the recipe automatically — but it is what
  puts `libsodium.so` in the app.
- **The GIL release**, since Threading rests on it and the 3.2× parallel speedup follows from
  it: grep the new slices' undefined symbols for `PyEval_SaveThread`. cffi has released the GIL
  around generated calls for a long time, so this is a regression check rather than a likely
  change.
- **The Argon2id presets and the sizes**, both re-read from the built wheels. Sizes on this
  page are decimal; `du` is binary.
- **Whether upstream has started publishing mobile wheels**, which is what makes a bare
  `pynacl` resolve from this index everywhere.

### Coverage gaps

`tests/test_pynacl.py` is two functions: a `SecretBox` round trip and an Ed25519 sign/verify
round trip. Three gaps are worth closing at the next touch, in order of value. **Nothing tests
`nacl.pwhash`**, which is the heaviest code path in the library and the one most likely to
expose a libsodium that built wrong — a single `argon2id.kdf` at `OPSLIMIT_MIN`/`MEMLIMIT_MIN`
costs under a millisecond and would cover it. **Nothing asserts that tampering raises**: the
signing test carries a comment saying verification raises `BadSignatureError` on tamper but
never flips a bit to prove it, and that assertion is the central claim of this page. And
**nothing exercises the public-key half** — `SealedBox` is the one primitive whose failure
would implicate the X25519 code specifically, and `to_curve25519_private_key()` is the
conversion the example depends on.

The device evidence behind this page is an emulator and a simulator, not a phone, so every
timing quoted from them is an artefact of emulated hardware — the Argon2 figures especially.
That run also counted any exception as a refusal; the example now separates a refusal from an
unexpected error, so re-run it before quoting a refusal count again.
