# Sodium basics

The app derives a key pair from one 32-byte file in its own storage, seals a note to that
public key, opens it again, encrypts the same note symmetrically, and then attacks the
sealed bytes: every bit is flipped in turn and the result fed back to the opener. The panel
reports how many forgeries were tried, how many were refused, and how long each primitive
took on the device you are holding. It runs once on launch, so there is a real result before
you touch anything.

What it demonstrates:

- **A sealed box, which is the shape most apps actually want.**
  [`crypto_box_seal`](https://doc.libsodium.org/public-key_cryptography/sealed_boxes)
  makes a throwaway key pair, agrees a key with the recipient and discards its own secret,
  so the ciphertext names no sender and only the stored secret key opens it. The cost is a
  fixed 48 bytes over the plaintext — the panel prints both lengths.
- **That a forged box raises instead of decoding.** Every single-bit flip of the sealed note
  is refused; the 29-character default note is 616 flips, all of them `ValueError`, none of
  them plaintext. That is the difference between a cipher and an *authenticated* one, and it
  is worth seeing as a count rather than taking on trust.
- **One stored secret, several keys.**
  [`crypto_kdf_derive_from_key`](https://doc.libsodium.org/key_derivation) turns the master
  key into the X25519 secret used for sealing and, under a different subkey id, the
  [`crypto_secretbox`](https://doc.libsodium.org/secret-key_cryptography/secretbox) key used
  for the local copy. Only the master key is persisted, in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  because everything else is reproducible from it.
- **Initialising libsodium yourself.** `start()` calls
  [`sodium_init()`](https://doc.libsodium.org/usage) before anything else touches the
  library, then reads the version — pysodium exposes both but calls neither for you, and the
  rest of libsodium is only documented as thread-safe after that first call returns.
- **Compute off the UI thread** — the whole sequence runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, the worker body is wrapped so a raise cannot leave
  the controls locked, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs.

Type a longer note and the flip count grows with it while the refusals stay equal to it —
the guarantee does not weaken with message length. The timings are the more surprising half:
the symmetric box costs a few microseconds, and the sealed box costs close to an order of
magnitude more for the same bytes, because a fresh Curve25519 key agreement happens inside
every seal and every open.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
