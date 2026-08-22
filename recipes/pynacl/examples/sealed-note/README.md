# pynacl sealed note

A note sealed two ways at once — under a passphrase, and under a public key — signed with the
device's own Ed25519 identity, reopened, and then attacked one bit at a time. Type a note and a
passphrase, pick how much memory Argon2id should burn, and the screen fills with the sizes, the
milliseconds and the count of forgeries that were refused.

What it demonstrates:

- **Both halves of NaCl on the same note.** The passphrase path stretches what you typed into a
  32-byte key with
  [Argon2id](https://pynacl.readthedocs.io/en/latest/password_hashing/#key-derivation) over a
  fresh 16-byte salt, then encrypts with
  [`SecretBox`](https://pynacl.readthedocs.io/en/latest/secret/) — XSalsa20-Poly1305, +24 bytes
  of nonce and +16 of authenticator. The public-key path hands the note to
  [`SealedBox`](https://pynacl.readthedocs.io/en/latest/public/#nacl.public.SealedBox), which
  generates a throwaway X25519 key pair, does the Diffie-Hellman against the recipient's public
  key and destroys its own secret — +32 bytes for the ephemeral public key and +16 for the tag,
  and nobody, the author included, can reopen it. One detached
  [Ed25519](https://pynacl.readthedocs.io/en/latest/signing/) signature covers the salt and both
  ciphertexts, so a reader can reject a forged envelope before spending 64 MiB on the KDF.
- **That tampering raises instead of decoding, counted three ways.** Every bit of a `SecretBox`
  message, a `SealedBox` message and a signed message is flipped in turn — 512, 576 and 704
  flips over a fixed 24-byte payload, **1,792 in total**. Each result is *refused* (the
  authenticator's own exception), *errored* (anything else raising) or *accepted* (a value
  handed back). Two counters would have been a lie: `nacl.exceptions.TypeError` and `ValueError`
  inherit from `CryptoError` too, so scoring every exception as a refusal would let a wrong type
  or a broken libsodium satisfy the headline. The verdict row should read 1,792 of 1,792
  refused; anything else turns it red. One extra flip is made against the note on screen so the
  exception text is visible and not only a number.
- **That a wrong passphrase costs the attacker exactly what it costs you.** The app re-derives
  the key from a deliberately wrong passphrase and reports both the failure and the milliseconds
  it spent getting there. That symmetry is the point of a memory-hard KDF, and it is why the
  memory figure on the button matters: `64 MiB` is Argon2id's `INTERACTIVE` preset, `256 MiB` is
  `MODERATE`. Its third preset, `SENSITIVE`, asks for 1 GiB in a single allocation and is
  deliberately not offered — that is not a request to make of a phone.
- **A real identity, stored where identities belong.** On first run the app generates a 32-byte
  Ed25519 seed and writes it to `identity.key` under
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  mode `0600`; every later run loads it, so the fingerprints on screen stay the same across
  restarts. The X25519 key the sealed box uses is derived from that same seed with
  `to_curve25519_private_key()`, so one file covers signing and encryption both. `flet run` sets
  that variable too, so a desktop run persists an identity the same way — under
  `src/.flet/storage/data/`, because `[tool.flet.app] path = "src"` makes `src` the project
  directory for dev storage, and why `.flet/` is in the `.gitignore`. Only a bare
  `python src/main.py` falls through to the temp-directory fallback, which exists so a key is
  never written beside `main.py`, where it would ship inside the next build.
- **What each primitive costs on this device.** The bottom block times nine operations — Ed25519
  keygen, sign, verify; X25519 keygen; the `Box` shared-key precompute; `SealedBox` seal and
  open; `SecretBox` seal and open over 1 KiB — as the best per-call time of three runs. The
  sizes and the counts are what two devices can be compared on; the milliseconds are this
  device's, and an emulator's are nobody's.
- **Whether this CPU has hardware AES.** The header calls
  `crypto_aead_aes256gcm_is_available()` on the raw cffi handle, because `nacl.bindings` exports
  no wrapper for it. Nothing here needs AES; the answer is on screen because it is the one
  capability libsodium settles at load time rather than at build time. Every 64-bit slice on
  this index carries an AES implementation and `armeabi-v7a` carries none, so on a 64-bit device
  what prints is the CPU's answer. A desktop `flet run` reads `no` whatever the CPU: PyPI's
  `universal2` wheel bundles a libsodium built without AES at all.
- **Honest behaviour where the package is absent.** The import is guarded, so a run without
  PyNaCl shows the exception and what to add to `pyproject.toml` instead of failing to start.

The pass runs in [`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
because Argon2id is seconds of deliberate work at the larger preset. The worker body is wrapped
in `try/except`, since `run_thread` never retrieves the future and would swallow the exception
entirely, and it ends with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), since auto-update does
not reach a background thread. `start()` returns early while a pass is in flight, and that — not
the greyed-out button — is what stops two passes running at once, because the passphrase field's
`on_submit` starts one too. That field also has `autocorrect`, `enable_suggestions` and
capitalisation off: a keyboard that "helps" produces a different passphrase, and the only symptom
is a `CryptoError` that looks as though the note itself is damaged.

`src/envelope.py` owns the identity, the KDF, both sealings, the bit-flip sweeps and the
timings, and returns plain rows; `src/main.py` is the screen and its wiring.

## Try it

Runs on the desktop as well as on a phone, because PyNaCl publishes `cp38-abi3` desktop wheels
for every host you would build from:

```bash
uv run flet run
```

[Build](https://flet.dev/docs/publish/) it for a device with:

```bash
uv run flet build apk
uv run flet build ios-simulator
```

It bundles no assets and makes no network requests. It writes one file — the 32-byte
`identity.key` described above — and deleting it simply gives the device a new identity on the
next run.
