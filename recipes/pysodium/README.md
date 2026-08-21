# pysodium

[`pysodium`](https://github.com/stef/pysodium) is a `ctypes` binding to
[libsodium](https://doc.libsodium.org/) — the same library [`pynacl`](../pynacl) binds, reached
a different way. PyNaCl compiles a cffi extension and puts an object model on top: key classes,
typed exceptions, methods. pysodium is one Python file that loads the shared library and calls
it, so the names, the argument order and the return values are libsodium's,
[its documentation](https://doc.libsodium.org/) is the reference, and every call takes and
returns `bytes`. Import the package as `pysodium`; the loaded library is reachable as
`pysodium.sodium`, which is how you call anything the module did not wrap.

It is the smaller and the wider of the two. The Android arm64 wheel is 14 KB against PyNaCl's
94 KB, and it binds C functions PyNaCl 1.6.2 does not expose at all —
[HKDF](https://doc.libsodium.org/key_derivation) and `crypto_kdf`, the `crypto_auth` HMAC
family, [Ristretto255](https://doc.libsodium.org/advanced/point-arithmetic/ristretto)
arithmetic, the raw [stream ciphers](https://doc.libsodium.org/advanced/stream_ciphers) and the
detached AEAD variants — while AES256-GCM, Ed25519 point arithmetic, SipHash, `sodium_pad` and
`sodium_memcmp` go the other way. The thinness is the cost as well as the point: it checks the
length of a key or a nonce but never its type, and every failure it reports is a `ValueError`,
which is most of what **[Things to know](#things-to-know)** is about.

## Install

Add pysodium to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pysodium",
]
```

**Pass `bytes`.** Most arguments go straight to `ctypes`, so what happens to anything else is
decided per function rather than by the package: `crypto_secretbox` takes `bytes`,
`bytearray` and `memoryview` and rejects `str` with `TypeError`, while `crypto_box_seal` is
the opposite — `ctypes.ArgumentError` for the buffers, and a `str` accepted and quietly
mangled. Encode text at the boundary and the question never arises.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`sodium-basics`](examples/sodium-basics) — seals a note to a device key, opens it, and
  flips every bit of the sealed bytes to show each forgery refused.

## Usage in a Flet app

Call `sodium_init()` once at startup, then work in raw bytes:

```python
import pysodium

pysodium.sodium_init()

public_key, secret_key = pysodium.crypto_box_keypair()
sealed = pysodium.crypto_box_seal(b"meet me at the old lighthouse", public_key)
note = pysodium.crypto_box_seal_open(sealed, public_key, secret_key)
```

[`crypto_box_seal`](https://doc.libsodium.org/public-key_cryptography/sealed_boxes) is the
one to reach for first on a device: it makes a throwaway key pair and discards its own secret
half, so the ciphertext names no sender and only the matching secret key opens it, for a fixed
`crypto_box_SEALBYTES` — 48 — over the plaintext. For data that never leaves the device,
[`crypto_secretbox`](https://doc.libsodium.org/secret-key_cryptography/secretbox) is symmetric
and far cheaper, at the price of a nonce you must not repeat under one key.

### Storage

A secret is just bytes: an X25519 secret key is 32 of them and a `crypto_kdf` master key is
32, so persisting an identity is one small file in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "master.key")
try:
    with open(path, "rb") as handle:
        master = handle.read(pysodium.crypto_kdf_KEYBYTES)
except OSError:
    master = pysodium.crypto_kdf_keygen()
    with open(path, "wb") as handle:
        handle.write(master)
    os.chmod(path, 0o600)
```

Store one secret rather than several: `crypto_kdf_derive_from_key(length, subkey_id,
context, master)` turns that master key into as many independent subkeys as the app needs,
with an 8-byte `context` separating one purpose from another.

The `"."` fallback is safe under Flet 0.86, which launches the app with its working directory
set to the same durable directory the environment variable names. What does ship a key is an
explicit path into the application directory: with `[tool.flet.app] path = "src"` everything
under `src/` is packaged into the build.

### Threading

**Call `pysodium.sodium_init()` yourself, before any worker thread exists.** The module binds
the function but never calls it, and [libsodium's rule](https://doc.libsodium.org/usage) is
that `sodium_init()` runs before any other function the library provides; only after it
returns are the rest documented as thread-safe. It is safe to call more than once, so the
first line of `main()` is a good home for it. It is also the raw C function rather than a
wrapper, so it returns libsodium's own code and never raises: `0` on success, `1` if the
library was already initialised, `-1` on failure — and nothing checks that `-1` for you.

After that, a key agreement or a large box belongs on a worker:

```python
def work():
    try:
        note = pysodium.crypto_box_seal_open(sealed, public_key, secret_key)
        status.value = note.decode()
    except ValueError:
        status.value = "refused"
    page.update()

page.run_thread(work)
```

[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) swallows
exceptions, so catch them in the worker and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Finding libsodium

This is the part specific to a `ctypes` binding, and it is already handled. The usual route
does not work on a phone:
[`ctypes.util.find_library`](https://docs.python.org/3/library/ctypes.html#finding-shared-libraries)
wants `ldconfig`, a compiler or a dyld search path and returns `None` on both platforms, which
is where the unpatched package gives up with `ValueError: Unable to find libsodium`. The wheel
instead loads the libsodium shipped with it by bare name, letting the platform's own dynamic
linker resolve it. On Android that is the soname `libsodium.so`, found in the APK's native
library directory, so Flet 0.86's zipped site-packages never enters into it. On iOS the library
is embedded and signed into the app as a framework. Either way the outcome is the same and it
is what a consumer needs: the library loads, and this recipe's device tests reported `2 passed`
under CPython 3.12 on an Android emulator and an iOS Simulator.

### App size

The wheel is 13.9 KB on every one of the eighteen published slices — CPython 3.12, 3.13 and
3.14 across three Android ABIs and three iOS slices — and unpacks to a single 99 KB
`__init__.py`. The library it loads is the real payload: 204–270 KB compressed per Android
ABI, unpacking to a `libsodium.so` of 240–485 KB. The iOS wheel looks far bigger at
819 KB–1.0 MB, but most of that is a static archive a `ctypes` consumer never touches; what
gets embedded in the app is a 447–562 KB shared library. On Android, use an app bundle, split
APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. These are package figures, not the amount added to
the final APK or IPA.

### Other considerations

**A desktop `flet run` is a different package.** PyPI publishes pysodium as an sdist only, so
a desktop install is upstream's loader with none of the mobile fallbacks: it needs a libsodium
already on the machine that `ctypes.util.find_library` can see. Under a uv-managed CPython 3.12
on macOS, with libsodium present under Homebrew, `import pysodium` still raised `ValueError:
Unable to find libsodium` — that prefix is not on dyld's search path;
`DYLD_LIBRARY_PATH=/opt/homebrew/lib` fixed it, and Homebrew's own CPython found it unaided. If
that message appears on your laptop but not on the phone, this is why. The libsodium version
can differ either side too; read `pysodium.sodium.sodium_version_string()` when that matters.

## Things to know

- **A forged ciphertext raises a bare `ValueError` with no message.** One `__check` helper
  turns every non-zero libsodium return code into `raise ValueError` with nothing attached, so
  a failed authentication and the wrong key arrive as the same exception with the same empty
  string. A malformed argument is the one case that does say something, and not usefully:
  a wrong-size key is caught by pysodium's own length check and reports `k incorrect size`,
  while a truncated sealed box reaches `ctypes` first and reports
  `Array length must be >= 0, not -38`. Catch `ValueError` around the smallest possible call
  and supply your own message:

  ```python
  try:
      note = pysodium.crypto_box_seal_open(sealed, public_key, secret_key)
  except ValueError:
      note = None  # refused: tampered, truncated, or the wrong key
  ```

  It does fail closed, which is the property that matters. Flipping every bit of a sealed
  box, a `crypto_secretbox` and an Ed25519 signature of one 29-byte note on a desktop — 1,488
  flips — produced 1,488 refusals and nothing decoded.

- **A `str` is sometimes encoded for you and sometimes corrupted, and the name does not tell
  you which.** Six wrappers UTF-8-encode their arguments first — `crypto_generichash` with its
  `_init`/`_update` pair, and `crypto_pwhash`, `crypto_pwhash_str`, `crypto_pwhash_str_verify`
  — so a `str` there gives the same answer as the encoded `bytes`. Everywhere else the string
  reaches `ctypes` as it is: `crypto_box_seal("héllo", pk)` returns a box that opens to
  `b'h\x00\x00\x00\xe9'`, the wide-character buffer having been passed with its length counted
  in characters. `crypto_sign_detached` and `crypto_auth` do the same, so a signature made over
  a `str` will not verify against that same text encoded. Encode before you call.

- **There is no constant-time comparison.** `sodium_memcmp` is not wrapped, so checking a
  computed tag against a received one with `==` leaks timing. Use
  [`hmac.compare_digest`](https://docs.python.org/3/library/hmac.html#hmac.compare_digest),
  or reach through `pysodium.sodium` for the C function.

- **`pysodium.randombytes` is libsodium's generator, not `os.urandom`.** It calls
  [`randombytes`](https://doc.libsodium.org/generating_random_data) directly — one more
  reason `sodium_init()` should have run first.

- **Python 3.14 warns at import, and 3.19 will fail.** Importing pysodium emits
  `DeprecationWarning: Due to '_pack_', the 'CryptoSignState' Structure will use memory
  layout compatible with MSVC (Windows)`, which CPython says is "slated to become an error in
  Python 3.19". It comes from a `ctypes.Structure` declaration inside pysodium: harmless
  today, fixable only upstream, and a reason not to let an app's `-W error` policy turn it
  into a crash. `flet run` sets `PYTHONWARNINGS=default::DeprecationWarning`, so a 3.14 desktop
  prints it where 3.13 and earlier print nothing.

## Build notes (maintainers)

### Recipe shape

pysodium is pure Python, so the recipe exists for two things: the loader patch, and the
`requirements.host` entry that makes `flet-libsodium` a `Requires-Dist` so a shared libsodium
reaches the app. That host dependency is also why the wheels are per-slice rather than one
`py3-none-any` file, and why the build number must move when the loader changes even though no
compiler runs.

`flet-libsodium` builds libsodium shared on Android and, on iOS, moves the dylib to the root of
site-packages so serious-python framework-izes it — deliberately unlike the `opt/lib` placement
[`pyzbar`](../pyzbar) and [`python-magic`](../python-magic) use, and the reason this loader
tries bare names where theirs derive a path from `__file__`. The iOS wheel also carries a
static `libsodium.a` for consumers that link instead of loading; this one ignores it.

### Upgrade hazards

- **The bare-name candidate list depends on serious-python's packaging.** If the Android
  jniLibs copy or the iOS framework-ization changes shape, this loader breaks at import with a
  `ValueError` that says nothing useful. Re-run the device tests after a serious-python bump,
  not only a pysodium or libsodium one.
- **The `libsodium.fwork` candidate is weaker than it looks, so iOS is not explained by it.**
  CPython dereferences a `.fwork` marker by `open()`ing the name it was handed
  (`Lib/ctypes/__init__.py`), so a bare `libsodium.fwork` resolves against the process working
  directory — under Flet 0.86 the app-storage data directory, not site-packages. That handling
  also arrived only in CPython 3.13, and the iOS run that passed was the cp312 slice — where
  `libsodium.fwork` is a filename `dlopen` can do nothing with, so that candidate is ruled out
  for the one configuration anyone has watched work.
  [`pyzbar`](../pyzbar)'s loader avoids both problems by building an absolute path from
  `__file__`. iOS import does succeed today, so something in the list works — establish *what*
  before trimming or reordering it, and prefer an absolute path if the answer is luck.
- **Version gates.** pysodium decorates some wrappers with `@sodium_version(...)`; the highest
  gate in the pinned version is 1.0.20, which the pinned `flet-libsodium` satisfies exactly. A
  bump that gates on newer libsodium needs the native recipe bumped with it.

### Re-verification checklist

- **Loader:** on both platforms, `import pysodium` succeeds and
  `pysodium.sodium.sodium_version_string()` reports the version `flet-libsodium` built. Log
  `pysodium.sodium._name` from the device while you are there — that is the missing evidence
  for the hazard above.
- **Packaging:** Android must still get an unversioned `libsodium.so` the Gradle step can
  place as `jniLibs`, loadable from zipped site-packages; iOS must still produce the framework
  from the site-packages-root `.so` — check the app bundle, not just the wheel.
- **Argument and error behavior:** the `str`, `bytearray` and bare-`ValueError` claims above
  are accidents of the wrapper rather than documented API. The `str` split follows the six
  `@encode_strings`-decorated functions in `pysodium/__init__.py`; re-derive that list from the
  built wheel rather than trusting the prose, and re-measure the sizes from the produced
  artifacts rather than scaling these figures.

### Coverage gaps

The device tests cover import, a `crypto_secretbox` round trip and a BLAKE2b vector. They do
not exercise the public-key side, key derivation, signatures, the tamper behavior, or any of
the primitives the consumer sections point at; those claims come from desktop runs and from
the example, and iOS has only ever been tested on the Simulator. Nor has any slice but cp312
run on a device: the 2026-07-14 pass was that pair, so the 3.13 and 3.14 wheels — the ones
whose CPython dereferences a `.fwork` marker — have never had their loader exercised.
