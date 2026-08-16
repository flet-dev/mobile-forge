# cryptography

[`cryptography`](https://cryptography.io/) is the Python ecosystem's default answer for
encryption, signatures, key derivation and X.509 — the thing `requests`, `paramiko`,
`pyjwt`, `josepy` and half of PyPI reach for. It is a Rust extension wrapped around
**its own statically linked copy of OpenSSL**, which is the reason it works at all on
mobile: neither Android nor iOS gives an app a usable system OpenSSL, and this wheel does
not need one. The Python stdlib's `hashlib`/`hmac` cover digests; everything past that —
AES-GCM, RSA, ECDSA, Ed25519, PBKDF2/scrypt, Fernet, certificate parsing and path
validation — is what this package is for.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "cryptography",
]
```

Nothing else to configure. `cryptography` declares
[`cffi`](https://cffi.readthedocs.io/) as a dependency and that resolves for mobile too, so
you do not list it yourself; the package needs no
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry. It builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a,
x86_64) and for iOS, on Python 3.12, 3.13 and 3.14.

**Which version you get depends on the Python you build for.** This is the one thing to
know before you write any code against it:

| `flet build --python-version` | you get |
| --- | --- |
| 3.12, 3.13 | cryptography 43.0.1 (September 2024) |
| 3.14 — Flet's default today | cryptography 48.0.0 |

`--python-version` is not the only way to pick: `flet build` also derives it from
`project.requires-python`, so a `requires-python = "==3.12.*"` quietly puts you on 43.0.1.
The split exists because 43.0.1 is built on pyo3 0.22, which refuses to compile against
Python 3.14 at all; 48.0.0 moves to pyo3 0.28. There is no build that gives you the new
version on the old Python.

Five upstream majors separate the two, so **check the
[changelog](https://cryptography.io/en/latest/changelog/) before you assume an API exists**.
The differences an app author actually trips over:

- **43.0.1 predates three security fixes** — CVE-2026-26007 (binary-curve private key
  leak), CVE-2026-34073 (name constraints skipped for wildcard DNS SANs during
  verification), CVE-2026-39892 (buffer overflow on non-contiguous buffers). If any of
  those matter to you, build for 3.14.
- **Things 48.0.0 removed or moved:** binary elliptic curves (the `SECT*` classes) are
  gone; `Camellia`, `CFB`, `OFB` and `CFB8` moved to
  [`hazmat.decrepit`](https://cryptography.io/en/latest/hazmat/decrepit/index.html);
  loading a key with an unsupported algorithm now raises `UnsupportedAlgorithm` rather
  than `ValueError`, and `public_bytes`/`private_bytes` raise `TypeError` rather than
  `ValueError` on a bad encoding.
- **What you gain by moving up:** `Hash.hash()` one-shot digests,
  `derive_into`/`encrypt_into`/`decrypt_into` for pre-allocated buffers, `HKDF.extract`,
  `ssh_key_fingerprint`, PKCS#7 decryption, the `PrivateKeyUsagePeriod` extension, and the
  declarative [`hazmat.asn1`](https://cryptography.io/en/latest/hazmat/asn1/) module.
- **What you appear to gain but do not:**
  [Argon2](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/),
  [ML-KEM](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/mlkem/),
  [ML-DSA](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/mldsa/),
  [HPKE](https://cryptography.io/en/latest/hazmat/primitives/hpke/) and deterministic
  ECDSA. They import fine and then raise
  [`UnsupportedAlgorithm`](https://cryptography.io/en/latest/exceptions/), because they
  need a newer OpenSSL than these wheels carry — see *Things to know*.

## Storage

The library never touches the filesystem itself, but the things you produce with it —
salts, ciphertext, serialized keys, certificate bundles — have to live somewhere. Put them
in [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups. From
Flet 0.86.0 it is also the process working directory on device, so a bare relative filename
lands there; spelling it out costs one line and behaves the same on desktop:

```python
vault = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "note.vault")
```

Never keep key material in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) — losing the key loses the data.

App-private storage is only as private as the OS makes it: it is unreadable by other apps
and encrypted at rest by Android file-based encryption and iOS Data Protection, but a
rooted or jailbroken device, and any backup the user restores elsewhere, sees it plainly.
This wheel gives you no access to the Android Keystore or the iOS Keychain — nothing here
is hardware-backed. If a key must survive that threat model, derive it from something the
user knows (what the example does) or reach for a Flet package that wraps the platform
keystore.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`secret-note`](examples/secret-note) — a note sealed under a passphrase.

## Threading

Key derivation is *deliberately* slow — that is the entire point of
[PBKDF2, scrypt and friends](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/).
A single scrypt derivation at the interactive settings (`n=2**14, r=8, p=1`) costs 16 MB
and a visible fraction of a second on a mid-range phone, and any parameters worth using are
slower than that. Run it off the UI thread with
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads. Bulk encryption of a large file deserves the same treatment.

Unlike a database handle, nothing here is thread-affine: `Fernet` objects and loaded keys
are safe to share across threads. What is not reusable is a KDF or cipher *context* — each
one is single-use and raises `AlreadyFinalized` on a second `derive()` or `finalize()`, so
construct a fresh one per operation rather than caching it. Serialize the work anyway if
two taps in quick succession would race to write the same file, or would together allocate
twice scrypt's memory cost.

Note that `page.run_thread` never retrieves the worker's future, so an exception in a
background handler surfaces nowhere — catch what you expect (`InvalidToken`,
`UnsupportedAlgorithm`) and put it on screen.

## iOS notes

Shipping this package means your app uses non-exempt encryption as far as App Store Connect
is concerned, and every upload asks about it. Answer it deliberately —
`ITSAppUsesNonExemptEncryption` in `Info.plist` records the answer so the question stops
being asked per-build. Apple's
[export compliance documentation](https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations)
is the authority on which exemption, if any, applies to you.

## Things to know

- **OpenSSL 3.0.x is baked into the wheel, and it is old.** The extension links OpenSSL
  statically — no `libssl.so`, no `libcrypto.dylib`, nothing borrowed from the OS — so your
  app carries exactly one OpenSSL and it changes only when the wheel is rebuilt. Which
  3.0.x depends on the Python version *and* the platform: today's wheels span 3.0.15 to
  3.0.20. Print it on the device you care about rather than guessing —
  `from cryptography.hazmat.backends.openssl.backend import backend` then
  `backend.openssl_version_text()`. For comparison, upstream's current PyPI wheels ship
  OpenSSL 4.0.0, which is why so much of cryptography's documentation describes algorithms
  you cannot reach here.
- **Nothing needing OpenSSL 3.2 or newer works.** Concretely: Argon2 (`3.2+`) raises
  `UnsupportedAlgorithm: This version of OpenSSL does not support argon2`; ML-KEM and ML-DSA
  (`3.5+`) raise `... is not supported by this backend`; `ecdsa_deterministic=True` on the
  X.509 builders is rejected. Use
  [`Scrypt`](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/#scrypt)
  or `PBKDF2HMAC` for password hashing instead — both work here. Any build can be
  interrogated from inside the app: `backend.argon2_supported()`,
  `backend.mlkem_supported()`, or
  `cryptography.hazmat.bindings._rust.openssl.CRYPTOGRAPHY_OPENSSL_320_OR_GREATER`.
- **The OpenSSL legacy provider is not in the wheel, and Flet already works around that.**
  Flet's app bootstrap sets `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1` for you on both platforms —
  which is the only reason `import cryptography` succeeds, because on 43.0.1 a failed
  legacy-provider load is a *fatal* import error rather than a warning. Do not unset it.
  What you lose: RC4, Blowfish, CAST5, IDEA, SEED and RC2 all raise `UnsupportedAlgorithm`
  (AES and 3DES are unaffected). The practical bite is old key files — a PKCS#12
  bundle or PKCS#8 key encrypted with RC2-40-CBC or SHA1-RC4, which is what `openssl` itself
  produced for years, will not load. Re-encrypt those with AES before shipping them.
- **FIPS mode is unavailable.** `backend._fips_enabled` is `False` and `_enable_fips()`
  cannot work: it needs OpenSSL's FIPS provider installed as a separate module alongside a
  `fipsmodule.cnf`, and a wheel has nowhere to put one.
- **There is no trust store on the device.** cryptography deliberately never reads an OS
  certificate store, and on mobile there is no system PEM bundle to fall back to either — so
  [X.509 path validation](https://cryptography.io/en/latest/x509/verification/) needs you to
  supply the roots (ship `certifi`, or your own pinned PEM as an app asset). Parsing a
  certificate needs nothing extra; *trusting* one does.
- **On Python ≤ 3.13 the wheel installs four extra top-level directories.** The 43.0.1
  wheels put cryptography's own `tests/`, `_cffi_src/`, `docs/` and `rust/` next to the
  `cryptography` package, and the first two are real importable packages on device — a
  bare `import tests` resolves to cryptography's own test suite, so an app module of yours
  by that name can be shadowed depending on path order. They are also about 3.4 MB of
  unpacked dead weight (0.7 MB of the download). The 48.0.0 wheels ship the package and
  nothing else.
- **Size.** Roughly 3 MB downloaded per slice either way; unpacked on device about 10 MB for
  43.0.1 and 8 MB for 48.0.0, of which the single `_rust.abi3.so` is 6 MB and 7.5 MB
  respectively. That extension is per-ABI, so an Android build covering all three ABIs
  carries three copies unless you split by ABI.

## Build notes (maintainers)

`meta.yaml` selects the version with a Jinja switch on `py_version.minor`: 48.0.0 from 3.14
up, 43.0.1 below. The constraint is pyo3, recorded in each wheel's
`dist-info/sboms/cryptography-rust.cyclonedx.json` — 43.0.1 pins pyo3 0.22.2, which knows
nothing about 3.14; 48.0.0 is on pyo3 0.28.3. Both are built by maturin from the upstream
sdist with no patches.

`requirements.host: openssl ^3.0.12` plus `script_env: OPENSSL_DIR = {platlib}/opt` is what
points `openssl-sys` at the cross-compiled OpenSSL from the Python support tree, and
`_PYTHON_SYSCONFIGDATA_NAME` is the usual cross-build pin. Two consequences of taking
OpenSSL from that tree rather than building our own:

1. **The OpenSSL version tracks the support tree, not this recipe**, which is why it varies
   per Python version and per platform across published wheels, and why it lags 3.0.x while
   upstream cryptography has moved to 4.0.0.
2. **The legacy provider is a separate DSO there** (`lib/ossl-modules/legacy.so`), not
   compiled into `libcrypto.a` — the static archive contains only the base, default and null
   providers. A wheel cannot carry that DSO, and the `MODULESDIR` baked into the library
   points at a build-machine path, so `OSSL_PROVIDER_load(NULL, "legacy")` can never succeed
   on device. Upstream's own wheels build OpenSSL with the legacy provider static, which is
   the difference. Flet's app bootstrap papering over this with
   `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1` is load-bearing for 43.0.1, where cryptography treats
   the failure as fatal; from 45.0.0 upstream downgraded it to a warning, and added a
   build-time `CRYPTOGRAPHY_BUILD_OPENSSL_NO_LEGACY` that would let the 48.0.0 build declare
   this properly instead of relying on the runtime variable.

The stray top-level `tests/`, `docs/`, `rust/` and `_cffi_src/` directories in the 43.0.1
wheels come from its `[tool.maturin] include` list, whose entries are bare strings; 48.0.0
tags each one `format = "sdist"`. Built with maturin 1.13.3 (recorded in every wheel's
`WHEEL` file) the bare form lands in the wheel as well as the sdist — upstream's own 43.0.1
wheel, built in 2024 against an older maturin, does not contain them.
