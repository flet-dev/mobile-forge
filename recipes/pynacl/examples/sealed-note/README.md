# pynacl sealed note

A note sealed two ways at once — under a passphrase, and under a public key — signed with the
device's own Ed25519 identity, reopened, and then attacked one bit at a time. Type a note and a
passphrase, pick how much memory Argon2id should burn, and the screen fills with the sizes, the
milliseconds and the count of forgeries that were refused.

What it demonstrates:

- **Both halves of NaCl on the same note.** The passphrase path stretches what you typed into a
  32-byte key with
  [Argon2id](https://pynacl.readthedocs.io/en/latest/password_hashing/#key-derivation)
  over a fresh 16-byte salt, then encrypts with
  [`SecretBox`](https://pynacl.readthedocs.io/en/latest/secret/) — XSalsa20-Poly1305, +24 bytes
  of nonce and +16 of authenticator. The public-key path hands the note to
  [`SealedBox`](https://pynacl.readthedocs.io/en/latest/public/#nacl.public.SealedBox), which
  generates a throwaway X25519 key pair, does the Diffie-Hellman against the recipient's public
  key and destroys its own secret — +32 bytes for the ephemeral public key and +16 for the tag,
  and nobody, the author included, can reopen it. One detached
  [Ed25519](https://pynacl.readthedocs.io/en/latest/signing/) signature covers the salt and both
  ciphertexts, so the reader can reject a forged envelope before spending 64 MiB on the KDF.
- **That tampering raises instead of decoding.** Every bit of a `SecretBox` message, a
  `SealedBox` message and a signed message is flipped in turn — 512, 576 and 704 flips over a
  fixed 24-byte payload, **1,792 in total** — and each result is counted as *rejected* (an
  exception) or *accepted* (a value handed back). The row to read is the verdict: it should say
  1,792 of 1,792 refused. A single `accepted` would mean the authenticator failed, and the row
  turns red. One extra flip is made against the real note on screen so the exception text is
  visible and not just a number.
- **That a wrong passphrase costs the attacker exactly what it costs you.** The app re-derives
  the key from a deliberately wrong passphrase and reports both the failure and the
  milliseconds it spent getting there. That symmetry is the whole point of a memory-hard KDF,
  and it is why the memory figure on the button matters: `64 MiB` is Argon2id's `INTERACTIVE`
  preset, `256 MiB` is `MODERATE`. Its third preset, `SENSITIVE`, asks for 1 GiB in a single
  allocation and is deliberately not offered — that is not a request to make of a phone.
- **A real identity, stored where identities belong.** On first run the app generates a 32-byte
  Ed25519 seed and writes it to `identity.key` under
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  mode `0600`; every later run loads it, so the fingerprints on screen stay the same across
  restarts. The X25519 key the sealed box uses is derived from that same seed with
  `to_curve25519_private_key()`, so one file covers signing and encryption both. `flet run`
  sets that variable too (`flet_cli/commands/run.py:416`), so a desktop run persists an identity
  the same way — measured here at `src/.flet/storage/data/identity.key`, because
  `[tool.flet.app] path = "src"` makes `src` the project directory for dev storage, and why
  `.flet/` is in the `.gitignore`. Only a bare `python src/main.py` falls through to the
  temp-directory fallback, which exists so a key is never written beside `main.py`, where it
  would ship inside the next build.
- **What each primitive costs on this device.** The bottom block times nine operations —
  Ed25519 keygen, sign, verify; X25519 keygen; the `Box` shared-key precompute; `SealedBox`
  seal and open; `SecretBox` seal and open over 1 KiB — as the best per-call time of three runs.
  These are the numbers a real design decision needs, and they are not the desktop's.
- **Whether this CPU has hardware AES.** The header calls
  `crypto_aead_aes256gcm_is_available()` on the raw cffi handle, because `nacl.bindings` exports
  no wrapper for it. Nothing this app does needs AES; the answer is there because it is the one
  capability libsodium settles at load time rather than at build time. Every 64-bit slice on
  this index carries an AES implementation — 1,418 `aese` instructions in the arm64 libraries,
  1,718 `vaesenc` in the x86_64 ones — so what prints is the CPU's answer and not the build's.
  `armeabi-v7a` carries none and can only say `no`. **No device has been asked yet**: the
  `universal2` wheel PyPI publishes for the desktop says `no`, but only because its own
  libsodium was built without AES at all.
- **The two `page.run_thread` rules, honoured explicitly.** The worker body is wrapped in
  `try/except` because
  [`run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) never retrieves the
  future and would swallow the exception entirely, and it ends with an explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) because auto-update
  does not reach a background thread. `start()` returns early while a pass is in flight, and that
  is what stops two of them running concurrently and writing the same controls; the greyed-out
  button is not the lock, because the passphrase field's `on_submit` starts a pass too and a
  disabled button does not gate it. Unlike most compiled packages on this index, PyNaCl's cffi
  bindings release the GIL for the duration of each libsodium call, so the worker genuinely steps
  aside for the UI.
- **A passphrase field the keyboard is not allowed to improve.** `autocorrect`,
  `enable_suggestions` and capitalisation are all off. A phone keyboard that "helps" produces a
  different passphrase, and the only symptom is a `CryptoError` that looks as though the note is
  damaged.
- **Honest behaviour where the package is absent.** The import is guarded, so a run without
  PyNaCl shows the exception and what to add to `pyproject.toml` instead of failing to start.

## What it should print

One complete pass on a desktop — macOS arm64, CPython 3.14.6, PyNaCl 1.6.2 — at the `64 MiB`
setting, with the default note and passphrase. **The sizes and the counts are the rows to
compare a device against; a difference there is a real difference.** The timings are not: the
same code on the same machine gave 374 ms and 363 ms for the two derivations and 249 / 336 ms
for the two slow sweeps when it was idle, so read the milliseconds as a working figure rather
than a specification.

| row | value |
| --- | --- |
| sealed | 46 B note → secretbox 86 B, sealedbox 94 B, signature 64 B |
| argon2id | 2 passes over 64 MiB · 536 ms to seal, 496 ms to open |
| opened | verify 0.49 ms · secretbox 29 µs · sealedbox 577 µs |
| wrong passphrase | `CryptoError` — after paying the same 534 ms |
| secretbox sweep | 512 flips → 512 rejected, 0 accepted · 3 ms |
| sealedbox sweep | 576 flips → 576 rejected, 0 accepted · 335 ms |
| ed25519 sweep | 704 flips → 704 rejected, 0 accepted · 380 ms |
| verdict | 1,792 of 1,792 tampered messages refused to decrypt |

Three Argon2id derivations and 1,792 forgeries came to 2,284 ms in that pass. The per-primitive
block, each row the best per-call time of three runs:

| operation | µs |
| --- | --- |
| ed25519 keygen | 147.1 |
| ed25519 sign 256 B | 157.1 |
| ed25519 verify | 497.8 |
| x25519 keygen | 144.0 |
| box shared key | 445.2 |
| sealedbox seal 256 B | 609.3 |
| sealedbox open | 453.6 |
| secretbox seal 1 KiB | 16.6 |
| secretbox open 1 KiB | 16.2 |

Switching to `256 MiB` multiplies the three KDF timings by roughly six on that machine (357 ms
→ 2,230 ms per derivation) and changes nothing else. The hardware-AES line in the header read
`no` there, on the `universal2` wheel PyPI publishes for macOS.

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
