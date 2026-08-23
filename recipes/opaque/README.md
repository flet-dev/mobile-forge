# opaque

[`opaque`](https://pypi.org/project/opaque/) is a `ctypes` binding to
[libopaque](https://github.com/stef/libopaque), an implementation of OPAQUE — the augmented
password-authenticated key exchange the IRTF CFRG specified and published as
[RFC 9807](https://www.rfc-editor.org/rfc/rfc9807.html). In an OPAQUE login the server
verifies a password it never receives, and what it stores is not a password hash: the record is
per-user random, so a stolen one matches no precomputed table and every guess against it costs
a full memory-hard derivation. What the exchange produces instead is a 64-byte session key both
sides compute independently, and that the client never arrives at with the wrong password.

On a phone that means a login that leaves the password on the device, finishes already holding a
key for the rest of the session, and yields a 64-byte *export key* to encrypt local data with.

## Install

Add opaque to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "opaque",
]
```

Passwords, identities and the context accept `str` or `bytes`; a `str` is UTF-8 encoded for
you at every entry point, including inside the `Ids` struct. Everything the protocol hands back
is `bytes`.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`password-exchange`](examples/password-exchange) — runs both halves of a registration and
  two logins in one process, and compares the session keys each side derived.

## Usage in a Flet app

A login is three calls and two messages:

```python
import opaque

ids = opaque.Ids(idu="alice", ids="example.com")
CTX = b"myapp-v1"

# on the device
ke1, client_secret = opaque.CreateCredentialRequest(password)

# on the server, against the record it stored when this user registered
ke2, server_key, server_auth = opaque.CreateCredentialResponse(ke1, record, ids, CTX)

# back on the device
session_key, client_auth, export_key = opaque.RecoverCredentials(ke2, client_secret, CTX, ids)
```

`ke1` is 96 bytes up, `ke2` is 320 bytes back, and `session_key` is the same 64 bytes on both
sides. Sending `client_auth` back so the server can call `opaque.UserAuth(server_auth,
client_auth)` is what tells it the login worked. Registration is a four-call sequence in the
same shape — `CreateRegistrationRequest`, `CreateRegistrationResponse`, `FinalizeRequest`,
`StoreUserRecord` — ending with the 256-byte record the server keeps.

### Storage

The client persists nothing: the password is typed, the export key comes back from every
successful login, and the client secret is dropped as soon as `RecoverCredentials` returns. The
256-byte record belongs to the server. When the app is both parties — a local vault a password
unlocks, with no network in it at all — that record is the one thing to keep, in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "record.bin")
with open(path, "wb") as handle:
    handle.write(record)
```

Flet 0.86 launches the app with its working directory set to that same durable directory, so
the `"."` fallback lands in the right place; naming the variable still makes the intent clear.
Encrypt whatever the record protects under the export key rather than storing it alongside: the
export key is re-derived at each login and never written down, so a stolen record and a stolen
ciphertext together are still no help.

### Threading

**Both client-side steps are memory-hard on purpose.** `FinalizeRequest` and
`RecoverCredentials` each run one
[`crypto_pwhash`](https://doc.libsodium.org/password_hashing) derivation — Argon2id at
libsodium's interactive parameters, two passes over 64 MiB — with the parameters compiled into
libopaque rather than chosen per call. On an Apple-silicon laptop that derivation dominates
everything else: a full registration and a full login each measured about 50 ms, every other
call in the protocol stayed under 0.2 ms, and a four-thousand-character password cost the same
as a three-character one. A phone will be slower, and the 64 MiB allocation is a real spike, so
run one exchange at a time and keep it off the UI thread:

```python
def work():
    try:
        session_key, _, export_key = opaque.RecoverCredentials(
            ke2, client_secret, CTX, ids
        )
        status.value = "signed in"
    except ValueError:
        status.value = "wrong password"
    page.update()

page.run_thread(work)
```

[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) swallows
exceptions, so catch them in the worker and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Failure, and who sees it

Every failure the library checks for is a `ValueError`, in two flavours that read very
differently. Bad arguments carry a message — `ValueError: invalid rec param` for a wrong-sized
record, `ValueError: invalid parameter` for an empty password or for `ids=None` where
`FinalizeRequest` expects one. A protocol failure carries nothing at all: `RecoverCredentials`
raises a bare `ValueError` with empty `args`, and a wrong password, wrong identities, a wrong
context and a tampered `ke2` all arrive as that same empty exception. The `except ValueError`
in the worker above is therefore the whole of the client's error handling, and the message the
user reads is one you choose rather than one the library gave you.

Not every argument is checked, though: `CreateCredentialResponse` passes `ids` and `ctx` straight
to `ctypes`, so `None` in either raises `TypeError` rather than `ValueError` — `_type_ must have
storage info` and `object of type 'NoneType' has no len()`. Build both once at startup.

**The server does not raise.** `CreateCredentialResponse` succeeds for any well-formed request
and returns a 64-byte session key even when the password is wrong, because the server holds
nothing it could test a guess against — the property the whole design exists for. It finds out
only from `UserAuth`, which raises the same bare `ValueError` when the client's proof does not
match, or from that proof never arriving. So the "wrong password" message comes from the
client's exception, and counting failed attempts server-side means counting `UserAuth` failures.

### App size

The Python wheel is 8.1 KB on every published slice; the native libraries under it are the
payload. Per Android ABI they come to roughly 310–600 KB unpacked, most of that libsodium. The
iOS arm64 device slice is heavier: a 340.9 KB `libopaque.so` with liboprf and libsodium linked
into it, a 458.6 KB `libsodium.so` beside it, and about 2.4 MB of static archives a `ctypes`
consumer never loads — the one thing here
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) could remove, if
you check the built app still launches.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These are package figures, not the amount added to the
final APK or IPA.

### Other considerations

**A desktop `flet run` will usually fail at import.** PyPI publishes opaque as an sdist only,
so a desktop install is upstream's loader with none of the mobile fallbacks: it calls
[`ctypes.util.find_library('opaque')`](https://docs.python.org/3/library/ctypes.html#finding-shared-libraries)
and raises `ValueError: Unable to find libopaque` when that comes back empty. Homebrew has a
formula for libsodium and none for libopaque or liboprf, so making `flet run` work means
building at least those two from source and putting them where the platform linker looks. The
device build needs none of that; [`pysodium`](../pysodium), which opaque imports, meets the same
wall one library earlier.

## Things to know

- **None of this is a wire format.** Every value is raw bytes of a fixed length — 32, 64, 192 and
  256 through registration, 96 and 320 for the two login messages, 64 each for the session key,
  the client's proof and the export key — and framing and transporting them is yours. The client
  secret is the exception: 226 bytes plus the length of the password.

- **`ids` and `ctx` are inputs to the key, not labels on it.** They are bound into the record at
  registration and mixed into the key at login, so changing either afterwards fails the client
  with exactly the bare `ValueError` a wrong password gives. Version the context; treat both as
  data you cannot alter once a user is enrolled.

- **The client secret contains the password.** `CreateCredentialRequest` copies it into the
  buffer it returns, because `RecoverCredentials` needs it again at the end, so the password's
  bytes are findable in it. Never log it, never persist it, and drop it once the login ends.

- **The export key belongs to the enrolment, not to the password.** Sixty-four bytes, the same
  at registration and at every later login against *that* record, unobtainable without the
  password. Registering the same password again produces a different export key, because the
  record carries a fresh OPRF key — so anything encrypted under it has to be re-encrypted on a
  password change *and* on any re-enrolment, and discarding a record discards the data.

- **`Register()` is the one-shot from the original paper, and it hands over the password.**
  `opaque.Register(pwd, ids)` returns a 256-byte record and an export key in one call, and the
  record is interchangeable with the one the four-message flow builds — fine when the device is
  both parties, wrong to expose to a real server, which would then see the plaintext.

- **`opaque.cli` is stale and will not import.** The module ships in the wheel, imports `click`,
  and calls an API this version no longer has. Without click, `import opaque.cli` raises
  `ModuleNotFoundError: No module named 'click'`; install click and it gets one line further, to
  `AttributeError: module 'opaque' has no attribute 'NotPackaged'`. Import `opaque` only.

- **There is one cipher suite and it is compiled in.** ristretto255, SHA-512 and Argon2id at
  libsodium's interactive parameters, which upstream states are hardcoded. A server built on a
  different OPAQUE library has to match both the suite and the password-hashing function;
  interoperability is not automatic.

- **Licensing:** [LGPL-3.0-or-later](https://spdx.org/licenses/LGPL-3.0-or-later.html), and the
  metadata disagrees with itself. The SPDX header in `opaque/__init__.py` says `LGPL-3.0-or-later`
  and the repository's `LICENSE` carries the LGPLv3 text; the PyPI metadata's `License` field says
  `GPLv3` and its classifier LGPLv3+. Read the header.

## Build notes (maintainers)

### Recipe shape

Four recipes in a chain: `flet-libsodium` and `flet-liboprf` build the two C dependencies,
`flet-libopaque` builds the library, and this recipe is the pure-Python wrapper. It compiles
nothing, and exists for the loader patch and for the `requirements.host` entry that makes
`flet-libopaque` a `Requires-Dist` — which is also why its wheels are per-slice rather than one
`py3-none-any` file.

The two platforms end up with different link shapes, which matters when reading a failure. On
Android `libopaque.so` names `liboprf.so` and `libsodium.so` in its `DT_NEEDED` entries, and
all four ship under unversioned `lib*.so` names for Gradle to place as `jniLibs`. On iOS
`libopaque.so` names only `libSystem`: liboprf and libsodium are absorbed statically, because
their iOS wheels ship archives where the Android ones ship shared objects. The app therefore
carries a second copy of libsodium inside `libopaque.so`, alongside the framework `pysodium`
loads.

Of `mobile.patch`'s two hunks only the loader rewrite earns its place: built with the setuptools
83.0.0 the shipped wheels name as their generator, the unpatched `setup.py` already emits
`Requires-Dist: pysodium`, so the `install_requires` hunk changes no metadata — which the patch
preamble and the `meta.yaml` comment both deny. Correct them at the next build-number bump.

### Upgrade hazards

- **The Python wrapper and the C library version separately and must move together.** They are
  one upstream repository — the wrapper is `python/` inside libopaque — but PyPI's `opaque`
  1.0.0 pairs with libopaque 1.0.1 here, and the wrapper hardcodes the struct sizes
  (`OPAQUE_USER_RECORD_LEN` and the rest) that size its `ctypes` buffers. A C-side struct
  change with no wrapper release silently mis-sizes those buffers. Bump both or neither.
- **A downgrade of the native recipe breaks registration and leaves login working.**
  `opaque_Register_core` and `opaque_FinalizeRequest_core` are exported by 1.0.1 and absent from
  0.99.8; `opaque_RecoverCredentials_extBeta`, which the wrapper also calls, is in both. `ctypes`
  resolves a name on first attribute access, so the symptom is `AttributeError: dlsym(...): symbol
  not found` from `Register()` or `FinalizeRequest()` — not at import, and nowhere near the login
  path that still works.
- **Changing the password-hashing parameters invalidates every stored record.** `opaque.c`
  derives the envelope key through `crypto_pwhash` at `OPSLIMIT_INTERACTIVE` /
  `MEMLIMIT_INTERACTIVE`, and the record does not say which parameters made it, so a retune
  locks every enrolled user out with no migration but re-enrolment. Breaking bump; say so here.
- **The iOS static absorption is an accident of how the dependency wheels are built.** If
  `flet-liboprf` or `flet-libsodium` starts shipping shared libraries on iOS, `libopaque.so`
  links dynamically instead and the framework-ization story changes with it.

### Re-verification checklist

- **Loader:** `import opaque` succeeds on both platforms, and `opaque.opaquelib._name` reports
  the name actually opened. That one value is what the patch is for; log it from the device
  rather than inferring it.
- **Symbols:** `opaque_Register_core`, `opaque_FinalizeRequest_core`,
  `opaque_RecoverCredentials_extBeta`, `opaque_StoreUserRecord` and `opaque_UserAuth` are still
  exported by the built library.
- **Constants against structs:** re-derive the message and record lengths from a live round
  trip and compare them with `opt/include/opaque.h`, trusting neither side alone.
- **Packaging:** Android must still surface `libopaque.so`, `liboprf.so`, `liboprf-noiseXK.so`
  and `libsodium.so` under unversioned names; iOS must still find an `MH_DYLIB` (not an
  `MH_BUNDLE`) `libopaque.so` at the site-packages root to framework-ize. Re-check the static
  absorption while you are there.
- **Cost:** re-measure `FinalizeRequest` and `RecoverCredentials` on a device, and the sizes
  from the produced wheels rather than scaling these figures.

### Coverage gaps

The device tests are two: an import, and one full round trip through the four-message
registration and the login, asserting that both sides derive the same session key and that the
export key is stable. The wrapper calls thirteen distinct libopaque entry points; the round trip
reaches seven of them — the four registration calls and the three login ones — plus, through the
import, pysodium and libsodium. `opaque_UserAuth` is one of the six it misses and the ordinary
login flow does use it, so a green suite says nothing about whether the server can verify the
client's proof on a device. Also unexercised: `Register()`, every failure path, the threshold
helpers (`CombineRegistrationResponses`, `CombineCredentialResponses`), the `_oprf`/`_ake` split
of `CreateCredentialRequest`, and `unlink_masking_key`. The example calls `UserAuth` on every
successful login and is the on-device check for it.

The sizes and link shapes above are read from the published wheels. Everything else — the
timings, the exception classes, the `Register()` and `opaque.cli` behaviour, the byte overlap
between two records for one password — was measured on an Apple M4 against a locally built
libopaque 1.0.1 and liboprf 0.5.0 over Homebrew's libsodium 1.0.22, while the device chain pins
libsodium 1.0.20. Treat those as desktop figures until the example confirms them.
