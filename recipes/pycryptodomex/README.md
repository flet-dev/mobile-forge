# pycryptodomex

[`pycryptodomex`](https://www.pycryptodome.org/) is a self-contained cryptography library:
AEAD ciphers, hashes and MACs, RSA and elliptic-curve signatures, and key-derivation
functions, all compiled into the wheel rather than borrowed from a system OpenSSL. It is the
same source as [`pycryptodome`](../pycryptodome), published a second time under the
`Cryptodome` namespace instead of `Crypto`.

Because the two are one library under two names, this page is about the name. Everything
else — which mode to pick, what a KDF costs on a phone — reads the same either way, with
`Crypto` read as `Cryptodome`.

## Install

Install exactly one of the two distributions:

| Distribution | Choose it when |
| --- | --- |
| `pycryptodomex` | The code you are porting imports `Cryptodome`. |
| [`pycryptodome`](../pycryptodome) | The code you are porting imports `Crypto`. |

```toml
dependencies = [
    "flet",
    "pycryptodomex",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`cipher-suite`](examples/cipher-suite) — seals a message through whichever of the two
  namespaces the import resolved to, and reports which are installed on the device.

## Usage in a Flet app

Import the library once, in one module, and let the rest of the app use the names that
module binds:

```python
try:
    from Cryptodome.Cipher import AES
    from Cryptodome.Random import get_random_bytes
except ImportError:
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes

cipher = AES.new(get_random_bytes(32), AES.MODE_GCM)
ciphertext, tag = cipher.encrypt_and_digest(message.encode())
nonce = cipher.nonce  # store it: reopening needs the same one back
```

That block is the whole portability story. Written this way the code runs unchanged against
either distribution — the same key and nonce produce the same ciphertext and tag under both
namespaces — and an app that later switches edits one file. Repeating the `try`/`except` in
several modules is harmless, since each resolves the same way; writing `Cryptodome.` in one
module and `Crypto.` in another is not.

### Storage

What needs a home is everything you produce: salts, nonces, ciphertext, serialized keys. Put
them in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups:

```python
vault = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "note.vault")
```

Never keep key material in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache),
which the OS may purge under storage pressure, or in
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp),
which may vanish between launches — losing the key loses the data. The data directory is
encrypted at rest and unreadable by other apps, but visible on a rooted or jailbroken device
and to anyone who restores a backup elsewhere, and nothing this wheel produces is
hardware-backed: it reaches neither the Android Keystore nor the iOS Keychain.

### Threading

**Cipher, hash and MAC objects are stateful, are not thread-safe, and do not fail with an
exception.** Eight threads calling `update()` on one shared `Cryptodome.Hash.SHA256` object
aborted the interpreter in ten desktop runs out of ten, under both native-call backends,
with `Assertion failed: (hs->curlen < BLOCK_SIZE), function SHA256_update` — a native abort
that `try`/`except` cannot see and that takes a phone app down with no crash screen. The
same assertion is compiled into the mobile binaries, so a device fails the same loud way.

A shared *cipher* object is worse again: it raises nothing at all and hands two threads the
same keystream — eight threads encrypting identical blocks through one AES-GCM object
produced 2400 ciphertext blocks and no exception in every one of ten desktop runs, and five
of those runs contained repeated blocks, up to four in a run. For a counter-mode cipher a
repeat means the same keystream came out twice.

Give each thread its own object and its own nonce, or hold a `threading.Lock` around the
whole use of a shared one — and note that
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) hands
work to a shared pool, so two taps in quick succession really can overlap. Background whole
jobs, a key derivation or a file encryption, rather than individual calls, and end every
worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Installing both

The two distributions do not overwrite each other: their wheels share no file path, so pip
installs both happily and both import in one process. What they do not share is *identity*.
A function that checks its argument with `isinstance` sees a class from the other namespace
and refuses it, while a function that duck-types accepts it — so mixing fails inconsistently
rather than loudly. Measured on desktop with both installed, passing a `Crypto` key into a
`Cryptodome` call:

| Call | Result |
| --- | --- |
| `Signature.pkcs1_15`, `Signature.pss`, `Cipher.PKCS1_OAEP` with an RSA key | accepted |
| `Signature.eddsa` with an Ed25519 key | `ValueError: EdDSA can only be used with EdDSA keys` |
| `Signature.DSS` with a P-256 key | `ValueError: Unsupported key type <class 'Crypto.PublicKey.ECC.EccKey'>` |
| `Protocol.DH.key_agreement` with an X25519 key | `TypeError: 'static_priv' must be an ECC key` |

Bytes cross freely, which is the way out when the situation is unavoidable: a key exported
to PEM under one namespace imports cleanly under the other, and digests, ciphertext and tags
are just bytes. Objects do not cross.

### App size

Each slice is approximately 1.6–1.7 MB compressed, unpacking to about 3.7 MB on Android
arm64-v8a and about 6.0 MB on iOS device arm64. The download is the same either way: the
extra iOS bytes are Mach-O segment padding across forty small binaries, not extra code.
Installing both distributions pays all of it twice.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. These figures describe the package payload, not the
exact amount added to the final APK or IPA.

### Other considerations

The library picks a cffi-based native-call layer when [`cffi`](https://cffi.readthedocs.io/)
can be imported and falls back to `ctypes` when it cannot, and the mobile wheel declares
cffi as a runtime dependency where PyPI's desktop wheel declares nothing — so a desktop
`flet run` can be exercising different code from the device. The readout is one line, and
adding or removing cffi from a desktop virtualenv flips it:

```python
from Cryptodome.Util import _raw_api
print(_raw_api.backend)
```

Both backends compute the same results, but a crash or a buffer-protocol edge case seen on
one is not evidence about the other. Read it on the device rather than assuming.

## Things to know

- **This is not a lighter or older variant.** Compared slice by slice at the same version
  and build number, both wheels hold 350 file entries and 40 compiled extensions per ARM and
  iOS-device slice, 352 and 42 on the x86_64 slices, which carry two extra x86-only modules;
  the same 148 module names outside the bundled test suite; and, across the library's own
  Python sources, three differing lines, each of them comment or docstring text where the
  rename also caught the library's own name. Past that only the `dist-info` metadata
  differs, as it must.

- **A dependency can make the choice for you.** A third-party package that imports `Crypto`
  drags `pycryptodome` in alongside your `pycryptodomex`, and the mixing table above then
  applies to any object crossing between your code and theirs. Probing for it at startup
  costs three lines:

  ```python
  import importlib

  for name in ("Crypto", "Cryptodome"):
      try:
          importlib.import_module(f"{name}.Cipher.AES")
      except ImportError:
          continue
      print(name, "is installed")
  ```

  An import rather than `importlib.util.find_spec`, because on Android the package lives
  inside `sitepackages.zip` and an import is the check that cannot be wrong about it.

- **An iOS build has an export-compliance question attached to it.** Shipping a
  cryptography library makes App Store Connect treat the app as using non-exempt
  encryption, and it asks at every upload until `ITSAppUsesNonExemptEncryption` in
  `Info.plist` records the answer. Apple's
  [export compliance documentation](https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations)
  is the authority on which exemption, if any, applies to you. Android asks nothing.

- **The clash this namespace exists to avoid cannot happen in a Flet mobile build.** The
  `Cryptodome` name was introduced so the library could coexist with `pycrypto`, which owns
  `Crypto` — and `pycrypto`'s last release is a 2014 source-only upload with no wheel on the
  mobile index, so a mobile app cannot install it. On mobile the namespace is worth choosing
  for one reason only: it is the one your existing code already types.

## Build notes (maintainers)

### Recipe shape

Upstream ships two separate sdists, so this is a second recipe rather than a rename applied
to `recipes/pycryptodome`. Both are the plain Python-package shape with one patch each, and
the two patches apply line-for-line equivalent hunks under the two namespaces. The patch preamble owns
what it changes; `meta.yaml` owns why the `cffi` dependency had to go through `setup.py`.
Do not repeat either here.

### Upgrade hazards

**Bump the two recipes together, to the same version and build number.** The sameness
bullet, the size figures and the mixing table all assume the pair are the same source at the
same revision, and `recipes/pycryptodome` carries the matching assumption. Nothing in CI
compares the two wheels, so a bump applied to one alone produces a divergence no job
reports.

`Requires-Dist: cffi` exists only because the patch edits `setup.py`; upstream declares no
dependencies at all. If a bump moves that call or the hunk stops applying cleanly, the wheel
still builds, still installs and still passes on any machine where
`dlsym(RTLD_DEFAULT, "PyObject_GetBuffer")` resolves — then fails at import on Android only.
Check `METADATA` in a built wheel, not the recipe.

### Re-verification checklist

- **Sameness:** Diff the two wheels' file lists per slice with `Cryptodome` normalised to
  `Crypto`, then diff the library's own sources with the same substitution applied to their
  text. Those two commands are the evidence behind the first *Things to know* bullet,
  including the per-slice module counts — which upstream decides at build time by probing
  the cross compiler for AES-NI and CLMUL support, so a toolchain change can move them.
- **Cross-namespace mixing:** The table under *Installing both* is a property of upstream's
  argument checks, which move between releases. Re-run it against the new version rather
  than carrying the rows forward.
- **Backend readout:** Confirm `Cryptodome.Util._raw_api.backend` still switches on whether
  cffi is importable, since the *Other considerations* advice depends on that being the
  observable signal.
- **Size:** Re-measure compressed and unpacked figures from the built wheels; the
  iOS/Android ratio is a linker artefact and moves independently of the source.

### Coverage gaps

The device tests cover an AES-GCM round trip and a SHA-256 known-answer under the
`Cryptodome` namespace. They do not exercise the asymmetric primitives, the KDFs, the
`.fwork`/`.soref` native-module resolution beyond the seven of forty native modules those
two tests load, or — since a test app installs one distribution — any cross-namespace
behaviour. The mixing table, the thread figures and the backend readout are desktop
measurements against the PyPI wheels of the same version; that the same abort is available
on device is a `strings` reading of the mobile binaries, not a device run.
