# Password exchange

A password is registered with a server that never learns it, then logged in with twice: once
correctly, once one character short. The panel lists every message that crossed between the two
sides and how many bytes it was, what the server ended up storing, and the first eight bytes of
the session key each side derived. It runs on launch, so a real exchange is on screen before you
touch anything. Both halves live in the one app because that is the only way to watch them
agree; in a deployment the server half runs on a server.

What it demonstrates:

- **A server that verifies a password it never receives.**
  [`CreateRegistrationRequest`](https://github.com/stef/libopaque/blob/master/python/README.md)
  blinds the password into a 32-byte
  [ristretto255](https://doc.libsodium.org/advanced/point-arithmetic/ristretto) point, and that
  point is the entire first message. The server answers it, folds its own secret in with
  `StoreUserRecord`, and keeps a 256-byte row. The protocol is
  [RFC 9807](https://www.rfc-editor.org/rfc/rfc9807.html).
- **That the stored row is not a password hash.** The app registers the same password a second
  time and compares the two records byte by byte. They agree on nothing, or a byte or two — the
  rate two random strings agree at, one byte in 256 — because each record is built from a fresh
  server key pair, a fresh OPRF key and a fresh envelope nonce. Nothing precomputed matches a
  stolen table of these, and every guess against one costs a full Argon2id derivation.
- **Both sides ending up with the same key.** `CreateCredentialResponse` gives the server 64
  bytes and `RecoverCredentials` gives the client 64 bytes, and the panel shows the same hex on
  both lines. `UserAuth` is the separate step that tells the server the client got there.
- **A wrong password failing on the client.** The server answers the second login exactly as it
  answered the first and derives a key it will never be able to use; the client cannot open the
  envelope that came back and raises a bare `ValueError` with no message at all. That asymmetry
  is the protocol working — the server has nothing to test a guess against.
- **The value that must not leak, on the device that holds it.** The client's own login secret
  is 226 bytes plus the password's own UTF-8 bytes — 254 for the default password — and the
  password sits inside it verbatim, which the app checks and reports.
- **Compute off the UI thread** — the run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button disabled and a spinner up, the worker body is wrapped so a raise cannot leave the
  controls locked, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs.

The timings are the part worth staring at: registration and each login cost about the same,
because the dominant term in both is a single
[`crypto_pwhash`](https://doc.libsodium.org/password_hashing) derivation — Argon2id over 64 MiB,
compiled into the library — paid on the client every time. Type a four-thousand-character
password and the numbers do not move; the memory-hard step runs over a fixed-size digest, not
over the password.

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
