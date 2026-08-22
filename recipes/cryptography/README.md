# cryptography

[`cryptography`](https://cryptography.io/) is the Python ecosystem's default answer for
encryption, signatures, key derivation and X.509. It is a Rust extension wrapped around
**its own statically linked copy of OpenSSL**, which is the reason it works at all on
mobile: neither Android nor iOS gives an app a usable system OpenSSL, and this wheel does
not need one. The stdlib's `hashlib` and `hmac` already cover digests; everything past that
— AES-GCM, RSA, ECDSA, Ed25519, PBKDF2/scrypt, Fernet, certificate parsing and path
validation — is what this package is for.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "cryptography",
]
```

**Which release you get depends on the Python you build for**, and the two are five majors
apart:

| `flet build --python-version` | you get |
| --- | --- |
| 3.12, 3.13 | cryptography 43.0.1 (September 2024) |
| 3.14 — Flet's default today | cryptography 48.0.0 (May 2026) |

`--python-version` is not the only way to pick it: `flet build` also derives the version
from `project.requires-python`, so a `requires-python = "==3.12.*"` quietly puts you on
43.0.1. Getting it wrong surfaces as an `ImportError` or `AttributeError` for an API you
read about in the current documentation, on the device rather than on your machine. There
is no build that gives you the newer release on the older Python.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`secret-note`](examples/secret-note) — a note sealed under a passphrase.

## Usage in a Flet app

Turn something the user knows into a key, seal bytes with it, and put the result into a
control:

```python
salt = os.urandom(16)
key = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(passphrase.encode())
token = Fernet(base64.urlsafe_b64encode(key)).encrypt(b"a note worth keeping")
status = ft.Text(f"sealed {len(token)} bytes")
```

[`Fernet`](https://cryptography.io/en/latest/fernet/) is the recipe layer: it picks
AES-128-CBC with HMAC-SHA256, so there is no mode, IV or padding to choose, and `decrypt`
authenticates the token before returning anything — a wrong key raises `InvalidToken`
rather than yielding garbage. Store the salt next to the ciphertext; the same passphrase
has to derive the same key on the next launch.

### Storage

The library never touches the filesystem itself, but what you produce with it — salts,
ciphertext, serialized keys, certificate bundles — has to live somewhere. Put it in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups. From Flet
0.86.0 that directory is also the process working directory on device, so a bare relative
filename lands there; spelling it out costs one line and behaves the same on desktop:

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
This wheel reaches neither the Android Keystore nor the iOS Keychain, so nothing it
produces is hardware-backed. If a key must survive that, derive it from something the user
knows — what the example does — or reach for a Flet package that wraps the platform
keystore.

### Threading

Key derivation is *deliberately* slow; that is the entire point of
[PBKDF2, scrypt and friends](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/).
One scrypt derivation at the interactive settings (`n=2**14, r=8, p=1`) allocates
128·n·r bytes — about 17 MB — and both the memory and the time rise linearly with `n`.
Measure it rather than guessing: the example prints the milliseconds each derivation took
on the device it is running on. Run the work off the UI thread with
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach background threads. Bulk encryption of a large file deserves the
same treatment.

Unlike a database handle, nothing here is thread-affine: `Fernet` objects and loaded keys
are safe to share across threads. What is not reusable is a KDF or cipher *context* — each
is single-use and raises `AlreadyFinalized` on a second `derive()` or `finalize()`, so
construct a fresh one per operation instead of caching it. Serialize the work anyway if two
taps in quick succession would race to write the same file, or would together hold twice
scrypt's memory. And `page.run_thread` never retrieves the worker's future, so an exception
in a background handler surfaces nowhere at all: catch what you expect — `InvalidToken`,
`UnsupportedAlgorithm` — and put it on screen.

### Which release you are on

Print the pair rather than inferring them from the build settings; both change with the
Python version the app was built for:

```python
import cryptography
from cryptography.hazmat.backends.openssl.backend import backend

ft.Text(f"cryptography {cryptography.__version__} — {backend.openssl_version_text()}")
```

The differences between the two releases an app author actually trips over:

- **Each release predates a fix the other has.** 43.0.1 predates CVE-2026-26007 (a
  malicious public key revealing part of your private key on binary curves), CVE-2026-34073
  (name constraints skipped when the leaf certificate carries a wildcard DNS SAN) and
  CVE-2026-39892 (buffer overflow on non-contiguous buffers), all three of which 48.0.0
  has. Read the
  [changelog](https://cryptography.io/en/latest/changelog/) rather than this list; it grows
  without anything in this repo changing.
- **What 48.0.0 removed or moved:** binary elliptic curves (the `SECT*` classes) are gone;
  `Camellia`, `CFB`, `OFB` and `CFB8` moved into
  [`hazmat.decrepit`](https://cryptography.io/en/latest/hazmat/decrepit/index.html) and are
  deprecated where they were; loading a key with an unsupported algorithm raises
  `UnsupportedAlgorithm` rather than `ValueError`; and `public_bytes`/`private_bytes` raise
  `TypeError` rather than `ValueError` on a bad encoding.
- **What you gain by moving up:** `Hash.hash()` one-shot digests,
  `derive_into`/`encrypt_into`/`decrypt_into` for pre-allocated buffers, `HKDF.extract`,
  `ssh_key_fingerprint()`, PKCS#7 decryption, the `PrivateKeyUsagePeriod` extension, and
  the declarative [`hazmat.asn1`](https://cryptography.io/en/latest/hazmat/asn1/) module.
- **What moving up does not bring:** Argon2, ML-KEM, ML-DSA, HPKE and deterministic ECDSA.
  Those are gated on the OpenSSL version rather than the cryptography version, and both
  wheels carry OpenSSL 3.0.x.

### App size

Around 3.0–3.5 MB compressed per slice on either release. Unpacked it is about 10 MB for
43.0.1 and about 8.5 MB for 48.0.0, of which the single `_rust.abi3.so` — cryptography's
Rust code and the whole of OpenSSL — is roughly 6.3 MB and 8 MB respectively. Those are
decimal figures summed from each wheel's zip directory; a built app compiles the Python
sources to `.pyc`, so what lands on the device differs a little. About 3.4 MB of the 43.0.1
figure is directories the package never imports, which
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) can drop;
on 48.0.0 there is nothing worth removing that way.

The extension is per-ABI, so an Android build covering all three carries three copies of
it. Use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI. Wheel size is not the amount added directly to the final
APK or IPA; packaging and compression determine that.

### Other considerations

**A desktop `flet run` proves nothing about what the device can do.** It resolves
cryptography from PyPI, and that wheel differs from this one in three ways at once: it is
whatever release pip currently offers rather than 43.0.1 or 48.0.0; it is built against a
4.x OpenSSL rather than 3.0.x; and it carries the legacy provider, with nothing setting
`CRYPTOGRAPHY_OPENSSL_NO_LEGACY`. So Argon2, ML-KEM, ML-DSA, HPKE, deterministic ECDSA,
RC4 and an RC2-encrypted PKCS#12 file can all work on your machine and raise
`UnsupportedAlgorithm` on the phone, and an API added after 43.0.1 can exist under
`flet run` and be missing from a 3.12 or 3.13 build.

Print the version and OpenSSL line at startup while developing, and validate anything
beyond AES, RSA, EC and Fernet on a device or emulator/simulator.

## Things to know

- **OpenSSL 3.0.x is baked into the wheel, and it is old.** The extension links OpenSSL
  statically — no `libssl.so`, no `libcrypto.dylib`, nothing borrowed from the OS — so your
  app carries exactly one OpenSSL and it changes only when the wheel is rebuilt. Which
  3.0.x depends on the Python version *and* the platform: today's wheels span 3.0.15 to
  3.0.20. Print `backend.openssl_version_text()` on the device you care about rather than
  guessing.

- **Nothing needing OpenSSL 3.2 or newer works.** On 48.0.0 the APIs are importable and
  fail at the call: Argon2 raises
  `UnsupportedAlgorithm: This version of OpenSSL does not support argon2`, ML-KEM and
  ML-DSA (OpenSSL 3.5+) raise `... is not supported by this backend`, and HPKE and
  `ecdsa_deterministic=True` on the X.509 builders are rejected the same way. On 43.0.1
  none of them are there at all — Argon2 arrived in 44.0.0 — so the same code fails at
  import instead. Any
  build can be interrogated from inside the app with `backend.argon2_supported()`,
  `backend.mlkem_supported()` or
  `cryptography.hazmat.bindings._rust.openssl.CRYPTOGRAPHY_OPENSSL_320_OR_GREATER`. For
  password hashing,
  [`Scrypt`](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/#scrypt)
  and `PBKDF2HMAC` work here; if you specifically need Argon2 or bcrypt, this repo ships
  [`argon2-cffi-bindings`](../argon2-cffi-bindings) and [`bcrypt`](../bcrypt), and
  [`pycryptodome`](../pycryptodome), [`pynacl`](../pynacl) and [`pysodium`](../pysodium)
  bring their own primitives without OpenSSL at all.

- **The OpenSSL legacy provider is not in the wheel, and Flet already works around that.**
  Flet's app bootstrap sets `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1` for you on both platforms,
  which is the only reason `import cryptography` succeeds: on 43.0.1 a failed
  legacy-provider load is a *fatal* import error rather than a warning. Do not unset it.
  What you lose is RC4, Blowfish, CAST5, IDEA, SEED and RC2, all of which raise
  `UnsupportedAlgorithm`; AES and 3DES are in the default provider and unaffected. The
  practical bite is old key files — a PKCS#12 bundle or PKCS#8 key encrypted with
  RC2-40-CBC or SHA1-RC4, which is what `openssl` itself produced for years, will not load.
  Re-encrypt those with AES before shipping them.

- **FIPS mode is unavailable.** `backend._fips_enabled` is `False` and `_enable_fips()`
  cannot work: it needs OpenSSL's FIPS provider installed as a separate module alongside a
  `fipsmodule.cnf`, and a wheel has nowhere to put one.

- **There is no trust store on the device.** cryptography deliberately never reads an OS
  certificate store, and on mobile there is no system PEM bundle to fall back on either, so
  [X.509 path validation](https://cryptography.io/en/latest/x509/verification/) needs you
  to supply the roots — ship `certifi`, or your own pinned PEM as an app asset. Parsing a
  certificate needs nothing extra; *trusting* one does.

- **On Python 3.12 and 3.13 the wheel installs four extra top-level directories.** The
  43.0.1 wheels put cryptography's own `tests/`, `_cffi_src/`, `docs/` and `rust/` beside
  the `cryptography` package, and the first two are real importable packages on device: a
  bare `import tests` can resolve to cryptography's test suite instead of a module of your
  own by that name, depending on path order. Together they are about 3.4 MB unpacked
  (0.7 MB of the download) that nothing imports. Drop them, and the shadowing with them:

  ```toml
  [tool.flet.cleanup]
  package_files = ["tests", "docs", "rust", "_cffi_src"]
  ```

  Check the result in the built app rather than assuming the patterns matched. The 48.0.0
  wheels ship the package and its `.dist-info` and nothing else.

- **Shipping this package makes your app "uses non-exempt encryption" on iOS.** Every App
  Store Connect upload asks about it. Answer deliberately and record the answer in
  `Info.plist` as `ITSAppUsesNonExemptEncryption` so the question stops being asked
  per-build. Apple's
  [export compliance documentation](https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations)
  is the authority on which exemption, if any, applies to you.

## Build notes (maintainers)

### Recipe shape

The recipe is one decision with a long shadow: **OpenSSL comes from the Python support
tree** rather than from an OpenSSL recipe of our own. Two consumer-visible consequences
follow from that and not from cryptography itself. The OpenSSL version tracks the support
tree — 3.0.x, where upstream's own wheels are on 4.x. And the legacy provider is a separate
DSO (`lib/ossl-modules/legacy.so`) that a statically linked wheel has no path to: the
archive holds only the base, default and null providers, and the baked-in `MODULESDIR`
points at a build-machine path. Upstream compiles the legacy provider *into* their static
OpenSSL, which is the whole of the difference. Building our own would fix both and is a far
larger recipe; that trade is the thing to revisit.

One improvement is available and deliberately not taken. From 45.0.0 upstream offers a
build-time `CRYPTOGRAPHY_BUILD_OPENSSL_NO_LEGACY`, which the newer branch could set instead
of leaning on Flet's runtime `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1`. The older branch cannot —
there a failed legacy load is fatal rather than a warning, so the runtime variable stays
load-bearing, and setting the build flag on one branch only would make the two diverge for
no consumer-visible gain.

### Upgrade hazards

The two branches move independently, so a bump changes the consumer claims on one leg only
and the page has to say which leg. Three specific traps:

- **Bumping the older branch is the direct fix for its three predated CVEs**, and would
  also pick up the build-time no-legacy flag and drop the stray top-level directories. What
  caps it is the pyo3 version each release pins against Python 3.12 and 3.13; every wheel
  records the pyo3 it was built with in `dist-info/sboms/cryptography-rust.cyclonedx.json`.

### Re-verification checklist

- **The release table and everything downstream of it.** The security list is written
  against two specific releases and grows on upstream's schedule; re-read the changelog and
  the security advisories rather than the diff between the two versions.
- **The unavailable-algorithm list.** `tests/test_cryptography.py` pins OpenSSL at 3.0.x
  precisely so it goes red the day the support tree moves. When it does, Argon2 becomes
  available at 3.2 and ML-KEM/ML-DSA at 3.5, and every claim on this page about an
  algorithm raising has to shrink to match.
- **The stray top-level directories.** They come from bare strings in 43.0.1's
  `[tool.maturin] include` list, which maturin 1.13.3 puts in the wheel as well as the
  sdist; 48.0.0 tags each entry `format = "sdist"`. Nothing to fix in this recipe, but the
  claim is per-release and per-maturin — check a built wheel rather than assuming either
  way.
- **The legacy-provider bullet** assumes Flet's app bootstrap still exports
  `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1`.
- **The sizes**, `_rust.abi3.so` included, are per-slice. Re-measure from the built wheels
  (`unzip -l`, or the zip directory) and quote decimal MB.

### Coverage gaps

The device tests cover a Fernet round-trip, PEM certificate parsing, the OpenSSL 3.0.x pin,
the legacy ciphers raising while AES keeps working, and a scrypt-plus-Fernet cycle. They do
not pin Argon2, ML-KEM, ML-DSA or HPKE failing — on either branch, and the two branches
fail differently — nor that Flet still exports `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1` (only its
symptom is pinned), nor the stray top-level directories and the `import tests` shadow, nor
FIPS, the missing trust store, or the storage guidance. Nothing is timed, so no on-device
performance claim is backed by a test; the example is the only thing that measures a
derivation.
