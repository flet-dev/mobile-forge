# pycryptodomex cipher suite

Type a message and a passphrase, choose an AEAD, and the app derives a key with
[scrypt](https://www.pycryptodome.org/src/protocol/kdf#scrypt), seals the message, opens it
again, then flips one bit of the authentication tag so you can watch the open fail. The two
lines above the form are what the example is really for: which namespace the import resolved
to, and which namespaces are installed on this device.

What it demonstrates:

- **One `try`/`except` decides the whole app.** `src/suite.py` opens with an import block
  that reaches for `Cryptodome` and falls back to `Crypto`, and sets `NAMESPACE` to whichever
  won. Upstream publishes the
  [same library twice](https://www.pycryptodome.org/src/introduction) under those two names,
  so that block is the only place in the app that has to know which one was installed.
- **The sealing path never names a namespace.** `seal()` and `_cipher()` are written purely
  against the names that block bound, and the row labelled *cipher came from* prints
  `type(cipher).__module__`: `Cryptodome.Cipher._mode_gcm` under AES-GCM,
  `Cryptodome.Cipher.ChaCha20_Poly1305` under the other segment, and those same two strings
  led by `Crypto.` on the sister distribution. That is how you can see, rather than be told,
  that the same function body ran either way.
- **Catching the both-installed mistake at runtime.** `namespaces_present()` tries to import
  `Crypto.Cipher.AES` and `Cryptodome.Cipher.AES` in turn and reports what it found. Two
  entries turn the line red: that is the same compiled library shipped twice, and the state
  in which a key object made under one name meets a function that lives under the other.
- **The library chooses the nonce, and the two choices differ** — 16 bytes for
  [AES-GCM](https://www.pycryptodome.org/src/cipher/modern#gcm-mode), 12 for
  [ChaCha20-Poly1305](https://www.pycryptodome.org/src/cipher/chacha20_poly1305). The app
  reads `cipher.nonce` back rather than picking one, and stores it beside the ciphertext,
  which is what makes the reopen work.
- **Compute off the UI thread** — scrypt is deliberately slow, so the whole job runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a
  [`ft.ProgressRing`](https://flet.dev/docs/controls/progressring/) up, and the worker ends
  with the explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
  that a background thread needs. Exceptions are caught and rendered into the table, because
  `run_thread` never retrieves the worker's result.

Swap `pycryptodomex` for `pycryptodome` in `pyproject.toml` and rebuild: every value on
screen keeps its meaning, and the only thing that changes is the namespace name in the three
places the app prints it. That is the argument for keeping the decision in one import block
instead of spreading `Cryptodome.` across a codebase.

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
