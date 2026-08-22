# pycryptodome

[`pycryptodome`](https://www.pycryptodome.org/) is a self-contained cryptography library:
each primitive ships as its own small C extension, with **no OpenSSL, no libgmp and
nothing else borrowed from the operating system**. That self-sufficiency is why it ports
cleanly to mobile, and the reason to reach for it is everything the Python stdlib does not
give you: authenticated encryption (AES-GCM, ChaCha20-Poly1305), RSA/DSA/ECC/Ed25519
signatures, X25519 and ECDH key agreement, scrypt/bcrypt/PBKDF2/HKDF, Shamir secret
sharing, and PEM/PKCS#8 key I/O. `hashlib` and `hmac` already cover plain digests.

## Install

```toml
dependencies = [
    "flet",
    "pycryptodome",
]
```

**This wheel gives you `Crypto`, not `Cryptodome`.** The library is published twice under
two top-level names, and mobile-forge has a recipe for each. Install exactly one:

| Distribution | Choose it when |
| --- | --- |
| `pycryptodome` | The code you are porting imports `Crypto`. |
| [`pycryptodomex`](../pycryptodomex) | The code you are porting imports `Cryptodome`. |

Installing both is possible, and is a trap — see *Things to know*.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`known-answer`](examples/known-answer) — published NIST and RFC vectors recomputed on
  the device, and what a password KDF costs there.

## Usage in a Flet app

Encrypt with an AEAD mode, keep the nonce beside the ciphertext, and verify on the way
back:

```python
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

key = get_random_bytes(32)

cipher = AES.new(key, AES.MODE_GCM)        # no nonce= : let the library generate one
ciphertext, tag = cipher.encrypt_and_digest(note.value.encode())
nonce = cipher.nonce                       # store this beside the ciphertext

opener = AES.new(key, AES.MODE_GCM, nonce=nonce)
try:
    result.value = opener.decrypt_and_verify(ciphertext, tag).decode()
except ValueError as exc:
    result.value = f"{type(exc).__name__}: {exc}"   # MAC check failed
page.update()
```

Omitting `nonce=` and storing what comes back is the habit worth forming, and
`decrypt_and_verify` rather than `decrypt` is what turns tampering into an error instead of
into plausible garbage. The `except` is not optional either: render the class and message
into a [`ft.Text`](https://flet.dev/docs/controls/text/), because an unhandled exception in
a Flet event handler ends the session with a crash screen.

### Storage

Nothing you import reads a cache, a config file or a data directory. What does need a home
is everything you produce with the library: salts, nonces, ciphertext, serialized keys. Put
those in
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
visible on a rooted or jailbroken device and to anyone who restores a backup elsewhere.
This wheel reaches neither the Android Keystore nor the iOS Keychain — nothing it produces
is hardware-backed. If a key must survive that threat model, derive it from something the
user knows, or reach for a Flet package that wraps the platform keystore.

### Threading

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

### Choosing primitives

**Prefer ChaCha20-Poly1305 to AES-GCM, because no real device has hardware AES here.**
pycryptodome's only accelerated AES is x86 AES-NI — the source contains no ARMv8
crypto-extension path at all, and neither `_raw_aesni` nor `_ghash_clmul` is present in any
ARM wheel, Android or iOS. AES therefore runs the portable T-table implementation and GHASH
runs `_ghash_portable`. Measured on an arm64 host taking that same path (8 MiB buffers,
best of five): ChaCha20-Poly1305 410 MB/s against AES-256-GCM 150 MB/s, a factor of 2.7.
Those absolute rates are a desktop measurement; the ordering follows from the missing module
and holds wherever `have_aes_ni()` reads 0.

**Prefer Ed25519, X25519 and P-256 to RSA, because no libgmp ships on either platform.**
pycryptodome tries to `dlopen` a bare `gmp` soname for its bignum backend and falls back to
the bundled `_IntegerCustom`/`_modexp` one when that fails — and nothing supplies a libgmp
on device: neither platform ships one, no extension in the wheel links one, and mobile-forge
has no gmp recipe. The elliptic-curve primitives have their own C modules and do not go
through that layer: on an arm64 host reporting the same GMP-less backend, Ed25519 signing
cost 0.125 ms and P-256 ECDSA signing 0.120 ms against RSA-2048's 1.77 ms, X25519 agreement
cost 0.066 ms, and RSA-2048 key generation cost 348 ms. If your Mac has Homebrew's libgmp
installed you are benchmarking a code path the phone does not have; export
`PYCRYPTODOME_DISABLE_GMP=1` to match it.

**Use `hashlib` for plain digests.** pycryptodome's hashes are portable C with no hardware
path: on the same arm64 host `Crypto.Hash.SHA256` managed 264 MB/s against
`hashlib.sha256`'s 2665 MB/s. Reach for `Crypto.Hash` for what the stdlib lacks —
KMAC128/256, KangarooTwelve, TupleHash, cSHAKE, TurboSHAKE, RIPEMD160, MD2/MD4, Poly1305,
CMAC — or where a pycryptodome API wants a `Crypto.Hash` module object. (The ratio is
flattering to the stdlib on macOS, where `hashlib` is OpenSSL-backed with ARMv8 SHA-2
instructions; it has not been measured against Flet's mobile Python.)

**Budget for the password KDF, measured on an arm64 desktop** so you know the shape before
you measure your own device:
[`scrypt`](https://www.pycryptodome.org/src/protocol/kdf#scrypt) at `r=8, p=1` cost 5 ms at
`N=2^12`, 21 ms at `2^14`, 175 ms at `2^17` and 1.7 s at `2^20`; PBKDF2-HMAC-SHA256 cost
6 ms at 10k iterations, 130 ms at 210k and 304 ms at OWASP's recommended 600k; bcrypt cost
13 / 53 / 211 / 854 ms at cost factors 8 / 10 / 12 / 14. A phone is slower, and the
`known-answer` example exists to tell you by how much. HKDF is 16 µs and is not a password
KDF.

**scrypt's real constraint is memory, not time.** Peak RSS above baseline came out at
exactly `128*N*r` — 16 MiB at `N=2^14`, 128 MiB at `2^17`, 512 MiB at `2^19`, a ratio of
1.00 every time, with no hidden overhead. OWASP's first-choice setting is `N=2^17, r=8,
p=1`, which is a 128 MiB allocation the OS has to satisfy in one piece; choose `N` against
the device's memory budget rather than against a target duration.

### App size

Approximately 1.6–1.7 MB compressed per slice on both platforms, unpacking to about 3.7 MB
on Android arm64-v8a, about 3.6 MB on armeabi-v7a and about 6.0 MB on iOS device arm64. The
extra iOS bytes are Mach-O segment padding across forty small binaries rather than extra
code, so do not size an iOS build from the Android figure. Roughly a third of the unpacked
payload is upstream's own bundled test suite, about 1.4 MB, which nothing in the wheel lets
you drop — so run it instead (*Things to know*).

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI: the extensions are per-ABI, so an APK covering all
three carries the native payload three times. These figures describe the package payload,
not the exact amount added to the final APK or IPA.

### Other considerations

A desktop `flet run` and a device can be running different native-call code. The library
picks a [`cffi`](https://cffi.readthedocs.io/)-based layer when cffi is importable and falls
back to `ctypes` when it cannot; the mobile wheel gets the cffi one and PyPI's desktop wheel
gets the `ctypes` one. The readout is one line:

```python
from Crypto.Util import _raw_api
print(_raw_api.backend)
```

Both backends compute the same results, but a crash or a buffer-protocol edge case seen on
one is not evidence about the other. Do not pin cffi out of the app to make the two match:
without it the `ctypes` path runs, and on Android it dies at import with
`AttributeError: undefined symbol: PyObject_GetBuffer`.

`Crypto.Math.Numbers._implementation` and `Crypto.Util._cpu_features.have_aes_ni()` split a
laptop from a phone the same way, and the `known-answer` example puts all three on screen.

## Things to know

- **Installing both distributions gives you two sets of classes that are not each other.**
  The wheels share no file path, so pip installs both happily and both import in one
  process — but a function that checks its argument with `isinstance` refuses a key made
  under the other namespace, while a function that duck-types accepts it, so mixing fails in
  some places and not others. Measured on desktop with both installed, passing a `Crypto`
  key into a [`Cryptodome`](../pycryptodomex) call:

  | Call | Result |
  | --- | --- |
  | `Signature.pkcs1_15`, `Signature.pss`, `Cipher.PKCS1_OAEP` with an RSA key | accepted |
  | `Signature.eddsa` with an Ed25519 key | `ValueError: EdDSA can only be used with EdDSA keys` |
  | `Signature.DSS` with a P-256 key | `ValueError: Unsupported key type <class 'Crypto.PublicKey.ECC.EccKey'>` |
  | `Protocol.DH.key_agreement` with an X25519 key | `TypeError: 'static_priv' must be an ECC key` |

  Bytes cross freely, which is the way out when the situation is unavoidable: a key exported
  to PEM under one namespace imports cleanly under the other, and digests, ciphertext and
  tags are just bytes. Objects do not cross. A third-party package that imports `Crypto` can
  drag this in without you choosing it.

- **Authentication failure is a bare `ValueError("MAC check failed")`.** There is no
  `InvalidTag` class; the same `ValueError` also carries `Padding is incorrect.` and
  `Incorrect AES key length`. A blanket `except ValueError` around a decrypt therefore
  swallows tampering and configuration bugs alike — match on the message, or re-raise
  something of your own. And catch it: an unhandled exception in a Flet event handler ends
  the session with a crash screen, so render the class and message instead.

- **Nonces are yours to get right, and the defaults are not the ones you expect.** Omit
  `nonce=` and [GCM](https://www.pycryptodome.org/src/cipher/modern#gcm-mode) and EAX
  generate 16 bytes, CCM 11 and OCB 15 — where most other libraries hand you 12 for GCM, so
  code ported from elsewhere will not line up. Reusing a GCM nonce under one key raises
  nothing and leaks both plaintexts: two encryptions under the same key and nonce completed
  without error and `ct1 ^ ct2` equalled `pt1 ^ pt2` exactly. Let the library generate the
  nonce and store it beside the ciphertext. Where uniqueness genuinely cannot be guaranteed,
  [SIV mode](https://www.pycryptodome.org/src/cipher/modern#siv-mode) is nonce-misuse
  resistant — but it needs a double-length key, exposes no `nonce` attribute, and rejects
  `encrypt()` with `TypeError: encrypt() not allowed for SIV mode. Use encrypt_and_digest()
  instead.`

- **The RNG is the OS CSPRNG, with nothing in front of it.**
  [`Crypto.Random.get_random_bytes`](https://www.pycryptodome.org/src/random/random) *is*
  the `os.urandom` object, and `Random.new().read` calls `urandom` — the shipped module is
  byte-identical to upstream's. There is no userspace pool to seed, no state to
  fork-corrupt (`Crypto.Random.atfork()` does nothing), and no per-platform caveat: this is
  identical on Android and iOS.

- **The x86_64 emulator and simulator run different code from every real phone.** Both
  x86_64 slices — the Android emulator one and the Intel-Mac iOS simulator one — carry two
  compiled extensions that no ARM slice has, `Crypto/Cipher/_raw_aesni` and
  `Crypto/Hash/_ghash_clmul`, and `Crypto.Cipher.AES` switches to `_raw_aesni` whenever
  `Crypto.Util._cpu_features.have_aes_ni()`, a CPUID probe, returns 1. So an x86_64 image
  whose virtual CPU exposes AES-NI runs hardware AES and GHASH where any actual device runs
  portable C: crypto timings taken there are not noisy, they are measuring something else.
  Use an arm64 device or an arm64 system image — on an Apple Silicon Mac the iOS simulator
  already takes the arm64 slice and matches the device — and read `have_aes_ni()` on screen
  if you want to be sure which path is live.

- **[ECC](https://www.pycryptodome.org/src/public_key/ecc) supports nine curves and no
  others** — NIST P-192/224/256/384/521 (with the usual `prime256v1`/`secp256r1` aliases),
  Ed25519, Ed448, Curve25519 (X25519) and Curve448 (X448). `secp256k1` and the Brainpool
  curves raise `ValueError: Unsupported curve`, so anything Bitcoin-adjacent needs a
  different package.

- **An iOS build has an export-compliance question attached to it.** Shipping a cryptography
  library makes App Store Connect treat the app as using non-exempt encryption, and it asks
  at every upload until `ITSAppUsesNonExemptEncryption` in `Info.plist` records the answer.
  Apple's
  [export compliance documentation](https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations)
  is the authority on which exemption, if any, applies to you. Android asks nothing.

- **What is compiled in.** AES with ECB/CBC/CFB/OFB/CTR/OPENPGP/KW/KWP and the AEAD modes
  GCM/EAX/CCM/OCB/SIV; ChaCha20, ChaCha20-Poly1305, Salsa20, ARC4; DES, 3DES, Blowfish,
  EKSBlowfish, CAST, ARC2. SHA-1/224/256/384/512, SHA3-224/256/384/512, SHAKE128/256,
  cSHAKE, TurboSHAKE, KangarooTwelve, KMAC128/256, TupleHash, BLAKE2b, BLAKE2s, MD2/MD4/MD5,
  RIPEMD160, Poly1305, CMAC, HMAC. RSA, DSA, ElGamal, ECC, Ed25519, Ed448, X25519, X448, DH,
  HPKE and Shamir secret sharing. KDFs PBKDF1, PBKDF2, HKDF, scrypt, bcrypt and SP800-108
  Counter, plus PEM/PKCS#8/PBES key I/O.

- **Upstream's own test suite ships inside the wheel, and you can run it.**
  `Crypto.SelfTest.run()` is a known-answer sweep over the whole library, 16.8 s on an arm64
  desktop, and no app imports it by accident. It skips the extended Wycheproof vector
  groups, because those are JSON data files the wheel does not carry.

## Build notes (maintainers)

### Recipe shape

Upstream ships two separate sdists, so `recipes/pycryptodomex` is a second recipe rather
than a rename applied to this one. Both are the plain Python-package shape with one patch
each, and the two patches apply line-for-line equivalent hunks under the two namespaces.
`patches/mobile.patch` owns what it changes in its own preamble, and `meta.yaml` owns why
the cffi dependency had to go through `setup.py` rather than `requirements.host`. Neither is
repeated here.

There is deliberately no gmp recipe. The library's bignum layer `dlopen`s a bare `gmp`
soname and falls back to its bundled implementation, and the fallback is what every mobile
slice takes.

### Upgrade hazards

**`Requires-Dist: cffi` is the single load-bearing thing to re-verify.** It exists only
because the patch edits `setup.py`, and upstream declares no dependencies at all. If a
version bump moves that call or the hunk stops applying cleanly, the wheel still builds,
still installs and still passes any test that runs on a machine where
`dlsym(RTLD_DEFAULT, "PyObject_GetBuffer")` resolves — and then fails at import on Android
only. Check `METADATA` in a built wheel, not the recipe.
`tests/test_pycryptodome.py::test_import_aes` is the on-device assertion.

**Bump the two recipes together, to the same version and build number.** The *Install*
table, the size figures and the cross-namespace table all assume the pair are the same
source at the same revision, and `recipes/pycryptodomex` carries the matching assumption.
Nothing in CI compares the two wheels, so a bump applied to one alone produces a divergence
no job reports.

**Adding a libgmp recipe would invalidate the asymmetric guidance.** The "prefer Ed25519
over RSA" advice and the example's on-screen bignum readout both assume `_IntegerGMP`
cannot load. Shipping a libgmp would move every asymmetric number on this page in both
directions at once, so re-measure before such a recipe lands rather than after.

### Re-verification checklist

- **Compiled modules per slice.** The claim that no ARM slice has hardware AES, and that the
  two x86_64 slices carry two extra modules, comes straight from upstream's
  `compiler_opt.py` probing the cross compiler for AES-NI and CLMUL support. It is a
  build-time decision, so a toolchain change can flip it silently in either direction.
  `unzip -l | grep -c '\.so$'` per slice is the whole test.
- **Published tags versus the example's floor.** The recipe publishes per-version wheels
  (currently three CPython legs) for three Android ABIs and iOS device plus both simulator
  architectures. `examples/known-answer/pyproject.toml` pins the package with `==`, so its
  `requires-python` must stay at or above the lowest CPython tag actually published for that
  build — otherwise the lowest split resolves an *older build number* of the same version
  and the example silently stops testing the current one. Check it the way a consumer meets
  it: copy the `pyproject.toml` alone into an empty directory and run `uv lock` there.
- **Android package layout.** Test from zipped site-packages. Add
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) to consumer
  guidance only if a real runtime filesystem read makes it mandatory, and include the failure
  symptom.
- **Android 16 KB alignment.** Every module's maximum `PT_LOAD` alignment must stay 16 KB,
  which is what satisfies Android 15's page-size requirement across forty small binaries.
- **Cross-namespace mixing.** The table in *Things to know* is a property of upstream's
  argument checks, which move between releases. Re-run it against the new version rather
  than carrying the rows forward.
- **Backend readout.** Confirm `Crypto.Util._raw_api.backend` still switches on whether cffi
  is importable, since the *Other considerations* advice depends on that being the observable
  signal.
- **Size, throughput and KDF numbers are measurements, not estimates.** Re-measure them from
  the built wheels rather than scaling them by eye; the iOS/Android ratio in particular is an
  artefact of Mach-O segment alignment and moves with the linker, not with pycryptodome.

### Coverage gaps

The device tests are three: that `Crypto.Cipher.AES` imports at all, an AES-CBC round trip,
and a SHA-256 known answer. Everything else on this page is unchecked by a green run. They
do not exercise any AEAD mode, the `MAC check failed` path, nonce generation, any asymmetric
primitive, any KDF, `Crypto.Random`, the bundled self-test suite, or more than a handful of
the wheel's compiled modules — so a passing job is not evidence that the rest of the wheel
loads. The threading figures, throughput ratios, KDF timings and cross-namespace table are
desktop measurements against the PyPI wheels of the same version; that the same native
abort is available on device is a `strings` reading of the mobile binaries, not a device run.
