# pycryptodome

[`pycryptodome`](https://www.pycryptodome.org/) is a self-contained cryptography library:
each primitive ships as its own small C extension, with **no OpenSSL, no libgmp and
nothing else borrowed from the operating system**. On Android every one of its compiled
extensions declares only `libm`, `libdl` and `libc`; on iOS each links only
`/usr/lib/libSystem.B.dylib` and the Python framework. That self-sufficiency is why it
ports cleanly to mobile, and the reason to reach for it is everything the Python stdlib
does not give you: authenticated encryption (AES-GCM, ChaCha20-Poly1305), RSA/DSA/ECC/
Ed25519 signatures, X25519 and ECDH key agreement, scrypt/bcrypt/PBKDF2/HKDF, Shamir
secret sharing, and PEM/PKCS#8 key I/O. `hashlib` and `hmac` already cover plain digests.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pycryptodome",
]
```

Nothing else to configure. The mobile wheels declare [`cffi`](https://cffi.readthedocs.io/)
as a runtime dependency — upstream's PyPI wheels declare none — and it resolves for mobile
too, so you neither list it nor exclude it; your app ships pycryptodome, cffi and
`pycparser` rather than one package. A desktop `uv sync` installs none of that, because
the PyPI wheel declares no dependencies — harmless there, and the reason a local run and a
device run report different native backends. No
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed: the wheel holds exactly one top-level package plus its `.dist-info`, and
inside `Crypto/` there is nothing but the compiled extensions, 206 `.py` files, 97 `.pyi`
stubs and a `py.typed` marker — no data files at all. It builds for all three Android ABIs
Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS device plus both simulator
architectures, on Python 3.12, 3.13 and 3.14.

**This wheel gives you `Crypto`, not `Cryptodome`.** The two namespaces are the same
library published twice, and mobile-forge has a recipe for each — the sibling
[`pycryptodomex`](../pycryptodomex) recipe ships it under `Cryptodome.*` at the same
version and build number, for the same six platform slices, and its wheel's file list is
identical once the top-level directory name is normalised away. Depend on whichever your
code already imports; installing both just carries the compiled extensions twice.

## Storage

Outside its bundled `Crypto/SelfTest`, pycryptodome opens exactly one file at runtime,
and only because of this recipe's own patch — nothing you would import reads a cache, a
config file or a data directory. (`Crypto/SelfTest` has ten `open()` call sites of its own,
all of them looking for vector files the wheel does not ship.) What does
need a home is everything you produce with it: salts, nonces, ciphertext, serialized keys.
Put those in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups. Spelling
the path out costs one line and behaves the same on desktop, where the variable is unset:

```python
vault = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "note.vault")
```

Never keep key material in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) — losing the key loses the data.

That directory is only as private as the OS makes it: unreadable by other apps and
encrypted at rest by Android file-based encryption and iOS Data Protection, but plainly
visible to a rooted or jailbroken device and to anyone who restores a backup elsewhere.
This wheel reaches neither the Android Keystore nor the iOS Keychain — nothing it produces
is hardware-backed. If a key must survive that threat model, derive it from something the
user knows, or reach for a Flet package that wraps the platform keystore.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`known-answer`](examples/known-answer) — published NIST and RFC vectors recomputed on
  the device, and what a password KDF costs there.

## Threading

**A cipher object is stateful, is not thread-safe, and fails silently.** Two threads
sharing one `AES.new(...)` object do not raise; they are handed the same keystream, which
for a stream mode means one XOR recovers both plaintexts. Measured here with eight threads
encrypting 400 identifiable blocks each through one shared AES-CTR object: four runs out of
five produced at least one counter block consumed by two different threads — six of them in
the worst run — with zero exceptions raised in any run. Five runs with a `threading.Lock`
taken around `encrypt()` produced none.

So either serialise a shared cipher with a lock held around the *whole* use, or give each
thread its own cipher object **and its own nonce**. Per-thread objects sharing one nonce is
not a fix; it is the same key/nonce pair used twice, deliberately.

**A shared hash or MAC object does not fail silently — it kills the process.** `update()`
mutates a C-side buffer with no locking, and a torn update trips an assertion that is
compiled into the shipped mobile modules. Eight threads updating one `Crypto.Hash.SHA256`
object aborted the interpreter in 8 runs out of 8, with `Assertion failed: (hs->curlen <
BLOCK_SIZE), function SHA256_update, file hash_SHA2_template.c, line 353`; `HMAC` over
SHA-256 did the same, `BLAKE2b` died in 6 runs out of 8 with `SIGSEGV`, `SIGBUS` or a
`Fatal Python error`, and SHA3-256 in 1. That is a native abort, not an exception —
`try`/`except` cannot see it and no crash screen is shown. The same eight threads with a
`threading.Lock` around `update()` ran clean every time and produced the serial digest.

This bites in Flet specifically because
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) hands
work to a shared thread pool, so two taps in quick succession really do overlap — and
`run_thread` never retrieves the worker's future, so an exception there would surface
nowhere anyway. A shared cipher raises nothing to miss, and a shared digest leaves no
process to report one.

**Background whole jobs, not individual calls.** pycryptodome releases the GIL for the
duration of each bulk call, so large work genuinely parallelises: on a 10-core arm64
desktop at four threads the measured speedups over one thread were 3.4 for scrypt at
`N=2^17`, 3.5 for PBKDF2 at a million iterations, and 3.1–3.4 for SHA-256, SHA3-256 and
AES-GCM over 8 MiB buffers — against 3.7 for a known GIL-releasing control
(`hashlib.sha256` over 128 MB) and 1.0 for a pure-Python loop. Repeat the same primitives
over 16 KiB buffers and the gain collapses to 1.7 for AES-GCM and 1.0 — the pure-Python
figure — for ChaCha20-Poly1305, because per-call GIL hand-off is then most of the cost.
Send a KDF, a file encryption or a whole batch off as one unit of work; do not fan a loop
of small signatures out across threads.

End every `run_thread` handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update): auto-update does
not reach background threads.

**Watch scrypt's memory when you background it.** Its cost is an allocation of exactly
`128*N*r` bytes, so two concurrent derivations ask the OS for twice that in one go, and an
Android low-memory kill is not something `try`/`except` can catch. One lock around the
derivation is cheaper than the alternative.

## Android notes

- **The x86_64 emulator runs different code from every real phone.** That slice's wheel
  carries two compiled extensions the ARM slices do not — `Crypto/Cipher/_raw_aesni` and
  `Crypto/Hash/_ghash_clmul`, 42 modules against 40 — and `Crypto.Cipher.AES` switches to
  `_raw_aesni` whenever `Crypto.Util._cpu_features.have_aes_ni()`, a CPUID probe, returns 1.
  So an emulator whose virtual CPU exposes AES-NI runs hardware AES and GHASH where any
  actual device runs portable C. Crypto timings
  taken on an x86_64 emulator are not noisy, they are measuring something else. (The iOS
  x86_64 simulator slice carries the same two modules; the four ARM slices carry neither.)
  Use an arm64 device or an arm64 system image, and read `have_aes_ni()` on screen if you
  want to be sure which path is live.
- **The `cffi` dependency exists for Android.** Without cffi, `Crypto/Util/_raw_api.py`
  falls back to `ctypes.pythonapi.PyObject_GetBuffer`, which dies at import with
  `AttributeError: undefined symbol: PyObject_GetBuffer` because Flet loads `libpython.so`
  through Dart's `DynamicLibrary.open` (that is, `RTLD_LOCAL`), hiding libpython's symbols
  from `dlsym(RTLD_DEFAULT)`. The dependency is declared unconditionally, so iOS carries
  cffi and pycparser too. Do not pin cffi away or vendor a cffi-free build.
- **Three ABIs mean three copies.** The extensions are per-ABI, so an APK covering all
  three carries the native payload three times unless you split by ABI. Every module's
  maximum `PT_LOAD` alignment is 16 KB, so they satisfy Android 15's page-size requirement.

## iOS notes

- **The same 40 extensions weigh about 2.9× more here.** 3.26 MiB of Mach-O on the device
  slice against 1.14 MiB of ELF on Android arm64, for identical source; unpacked the wheel
  is 5.68 MiB on iOS and 3.56 MiB on Android. The cause is per-dylib segment alignment
  rather than anything in the code — `size -m` on the iOS SHA-256 module reports `__TEXT`
  32768, `__DATA_CONST` 16384, `__DATA` 16384 and `__LINKEDIT` 16384 around 8256 bytes of
  actual `__text`, giving a 67,640-byte file where Android's is 13,160. The *download* is
  about 1.6 MB on every slice either way. Do not size an iOS build from the Android figure.
- **The x86_64 simulator slice is not what an iPhone runs.** Like the Android x86_64
  emulator wheel, it carries `Crypto/Cipher/_raw_aesni` and `Crypto/Hash/_ghash_clmul` —
  42 compiled modules against the 40 in the device and arm64-simulator slices — so AES and
  GHASH run on hardware instructions there and on portable C everywhere else. On an Apple
  Silicon Mac the simulator uses the arm64 slice and matches the device.
- **Shipping this makes your app "uses non-exempt encryption"** as far as App Store Connect
  is concerned, and every upload asks. Answer it deliberately —
  `ITSAppUsesNonExemptEncryption` in `Info.plist` records the answer so the question stops
  being asked per build. Apple's
  [export compliance documentation](https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations)
  is the authority on which exemption, if any, applies to you. Android has no equivalent
  prompt.

## Things to know

- **There is no hardware AES on any real device, so prefer ChaCha20-Poly1305 to AES-GCM.**
  pycryptodome's only accelerated AES is x86 AES-NI — the source contains no ARMv8
  crypto-extension path at all, and neither `_raw_aesni` nor `_ghash_clmul` is present in
  any ARM wheel, Android or iOS. AES therefore runs the portable T-table implementation and
  GHASH runs `_ghash_portable`. Measured on an arm64 host taking that same path (8 MiB
  buffers, best of five): ChaCha20-Poly1305 410 MB/s against AES-256-GCM 150 MB/s, a factor
  of 2.7. Those absolute rates are a desktop measurement; the ordering follows from the
  missing module and holds wherever `have_aes_ni()` reads 0.
- **Use `hashlib` for plain digests.** pycryptodome's hashes are portable C with no
  hardware path: on the same arm64 host `Crypto.Hash.SHA256` managed 264 MB/s against
  `hashlib.sha256`'s 2665 MB/s. Reach for `Crypto.Hash` for what the stdlib lacks —
  KMAC128/256, KangarooTwelve, TupleHash, cSHAKE, TurboSHAKE, RIPEMD160, MD2/MD4, Poly1305,
  CMAC — or where a pycryptodome API wants a `Crypto.Hash` module object. (The ratio is
  flattering to the stdlib on macOS, where `hashlib` is OpenSSL-backed with ARMv8 SHA-2
  instructions; it has not been measured against Flet's mobile Python.)
- **No libgmp ships on either platform, so prefer Ed25519, X25519 and P-256 to RSA.**
  pycryptodome tries to `dlopen` a bare `gmp` soname for its bignum backend and falls back
  to the bundled `_IntegerCustom`/`_modexp` one when that fails — and nothing supplies a
  libgmp on device: neither platform ships one, none of the 40 extensions links one, and
  mobile-forge has no gmp recipe. The elliptic-curve primitives have their own C modules
  and do not go through that layer: on an arm64 host reporting the same GMP-less backend,
  Ed25519 signing cost 0.125 ms and P-256 ECDSA signing 0.120 ms against RSA-2048's
  1.77 ms, X25519 agreement cost 0.066 ms, and RSA-2048 key generation cost 348 ms. If
  your Mac has Homebrew's libgmp installed you are benchmarking a code path the phone does
  not have; export
  `PYCRYPTODOME_DISABLE_GMP=1` to match it. The `known-answer` example prints
  `Crypto.Math.Numbers._implementation` on screen, which is the only way to be certain.
- **Authentication failure is a bare `ValueError("MAC check failed")`.** There is no
  `InvalidTag` class; the same `ValueError` also carries `Padding is incorrect.` and
  `Incorrect AES key length`. A blanket `except ValueError` around a decrypt
  therefore swallows tampering and configuration bugs alike — match on the message, or
  re-raise something of your own. And catch it: an unhandled exception in a Flet event
  handler ends the session with a crash screen, so render the class and message instead.
- **Nonces are yours to get right, and the defaults are not the ones you expect.** Omit
  `nonce=` and [GCM](https://www.pycryptodome.org/src/cipher/modern#gcm-mode) and EAX
  generate 16 bytes, CCM 11 and OCB 15 — where most other libraries hand you 12 for GCM, so
  code ported from elsewhere will not line up. Reusing a GCM nonce under one key raises
  nothing and leaks both plaintexts: two encryptions under the same key and nonce completed
  without error and `ct1 ^ ct2` equalled `pt1 ^ pt2` exactly. Let the library generate the
  nonce and store it beside the ciphertext. Where uniqueness genuinely cannot be
  guaranteed, [SIV mode](https://www.pycryptodome.org/src/cipher/modern#siv-mode) is
  nonce-misuse resistant — but it needs a double-length key, exposes no `nonce` attribute,
  and rejects `encrypt()` with `TypeError: encrypt() not allowed for SIV mode. Use
  encrypt_and_digest() instead.`
- **The RNG is the OS CSPRNG, with nothing in front of it.**
  [`Crypto.Random.get_random_bytes`](https://www.pycryptodome.org/src/random/random) *is*
  the `os.urandom` object, and `Random.new().read` calls `urandom` — the shipped module is
  byte-identical to upstream's. There is no userspace pool to seed, no state to fork-
  corrupt (`Crypto.Random.atfork()` does nothing), and no per-platform caveat: this is
  identical on Android and iOS.
- **[ECC](https://www.pycryptodome.org/src/public_key/ecc) supports nine curves and no
  others** — NIST P-192/224/256/384/521 (with the usual `prime256v1`/`secp256r1` aliases),
  Ed25519, Ed448, Curve25519 (X25519) and Curve448 (X448). `secp256k1` and the Brainpool
  curves raise `ValueError: Unsupported curve`, so anything Bitcoin-adjacent needs a
  different package.
- **Password KDFs, measured on an arm64 desktop** so you know the shape before you measure
  your own device: [`scrypt`](https://www.pycryptodome.org/src/protocol/kdf#scrypt) at
  `r=8, p=1` cost 5 ms at `N=2^12`, 21 ms at `2^14`, 175 ms at `2^17` and 1.7 s at `2^20`;
  PBKDF2-HMAC-SHA256 cost 6 ms at 10k iterations, 130 ms at 210k and 304 ms at OWASP's
  recommended 600k; bcrypt
  cost 13 / 53 / 211 / 854 ms at cost factors 8 / 10 / 12 / 14. A phone is slower, and the
  `known-answer` example exists to tell you by how much. HKDF is 16 µs and is not a password
  KDF.
- **scrypt's real constraint is memory, not time.** Peak RSS above baseline came out at
  exactly `128*N*r` — 16 MiB at `N=2^14`, 128 MiB at `2^17`, 512 MiB at `2^19`, a ratio of
  1.00 every time, with no hidden overhead. OWASP's first-choice setting is `N=2^17, r=8,
  p=1`, which is a 128 MiB allocation the OS has to satisfy in one piece; choose `N` against
  the device's memory budget rather than against a target duration.
- **What is compiled in.** AES with ECB/CBC/CFB/OFB/CTR/OPENPGP/KW/KWP and the AEAD modes
  GCM/EAX/CCM/OCB/SIV; ChaCha20, ChaCha20-Poly1305, Salsa20, ARC4; DES, 3DES, Blowfish,
  EKSBlowfish, CAST, ARC2. SHA-1/224/256/384/512, SHA3-224/256/384/512, SHAKE128/256,
  cSHAKE, TurboSHAKE, KangarooTwelve, KMAC128/256, TupleHash, BLAKE2b, BLAKE2s, MD2/MD4/MD5,
  RIPEMD160, Poly1305, CMAC, HMAC. RSA, DSA, ElGamal, ECC, Ed25519, Ed448, X25519, X448, DH,
  HPKE and Shamir secret sharing. KDFs PBKDF1, PBKDF2, HKDF, scrypt, bcrypt and
  SP800-108 Counter, plus PEM/PKCS#8/PBES key I/O.
- **A third of the wheel is upstream's own test suite, and you can run it.**
  `Crypto/SelfTest` is 97 files and 1.32 MiB unpacked — 37% of the Android unpacked size and
  23% of the iOS one — and no app imports it by accident. Nothing in the wheel lets you drop
  it, so use it instead: `Crypto.SelfTest.run()` is a known-answer sweep over the whole
  library, 16.8 s on an arm64 desktop. It skips the extended Wycheproof vector groups,
  because those are JSON data files the wheel does not carry.
- **Size.** About 1.6 MB downloaded per slice on both platforms. Unpacked: 3.56 MiB on
  Android arm64 (1.14 MiB of it compiled), 3.48 MiB on armeabi-v7a, and 5.68 MiB on iOS
  device arm64 (3.26 MiB compiled). The largest single extension by a wide margin is
  `Crypto/PublicKey/_ec_ws`, at 0.66 MiB on Android arm64 and 0.71 MiB on iOS; the next
  largest is under 50 KiB on Android.

## Build notes (maintainers)

`patches/mobile.patch` explains both of its halves in its own preamble and `meta.yaml`
explains why the cffi dependency had to go through `setup.py` rather than
`requirements.host`, so neither is repeated here. What is left is the bump checklist, and
it matters more than usual: this README makes a dozen claims a green build does not check.

- **`Requires-Dist: cffi` is the single load-bearing thing to re-verify.** It exists only
  because the patch edits `setup.py`, and upstream declares no dependencies at all. If a
  version bump moves that call or the hunk stops applying cleanly, the wheel still builds,
  still installs and still passes any test that runs on a machine where
  `dlsym(RTLD_DEFAULT, "PyObject_GetBuffer")` resolves — and then fails at import on
  Android only. Check `METADATA` in a built wheel, not the recipe.
  `tests/test_pycryptodome.py::test_import_aes` is the on-device assertion.
- **Recount the compiled modules per slice.** The consumer-facing claim that no ARM slice
  has hardware AES, and that the x86_64 Android slice has two extra modules, comes straight
  from upstream's `compiler_opt.py` probing the cross compiler for AES-NI and CLMUL support.
  It is a build-time decision, so a toolchain change can flip it silently in either
  direction. `unzip -l | grep -c '\.so$'` per slice is the whole test.
- **No gmp recipe exists, and adding one would invalidate the asymmetric guidance.** The
  "prefer Ed25519 over RSA" bullet, and the example's on-screen bignum readout, both assume
  `_IntegerGMP` cannot load. Shipping a libgmp would move every asymmetric number on this
  page in both directions at once, so re-measure before such a recipe lands rather than
  after.
- **The size, throughput and KDF numbers are measurements, not estimates.** Re-measure them
  rather than scaling them by eye; the iOS/Android ratio in particular is an artefact of
  Mach-O segment alignment and moves with the linker, not with pycryptodome.
- **Keep the sibling in step.** `recipes/pycryptodomex` is the same source under the
  `Cryptodome` namespace and carries the same patch rationale; bump and re-verify the two
  together, or the "same version and build number" claim in *Install* goes stale.
