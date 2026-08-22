# secret note

A single note you seal under a passphrase and reopen with it. Type a note, pick a
passphrase, tap **Lock** — the plaintext leaves the screen and a file of ciphertext appears
in app storage. Kill the app, reopen it, tap **Unlock**: the right passphrase brings the
note back, the wrong one says so.

What it demonstrates:

- **A passphrase turned into a key by
  [`Scrypt`](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/#scrypt)**,
  then used with [`Fernet`](https://cryptography.io/en/latest/fernet/) — the recipe layer that
  picks AES-128-CBC and HMAC-SHA256 for you so there is no mode or IV to get wrong. A random
  16-byte salt is stored next to the ciphertext, because the same passphrase must derive the
  same key on the next launch.
- **What the derivation costs on the device you are holding.** Each Lock and Unlock reports
  the milliseconds it spent, which is the honest way to pick scrypt's `n` — the interactive
  settings used here also hold about 17 MB (128·n·r bytes) while they run.
- **The derivation in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)**
  — scrypt is slow on purpose, so it does not belong on the UI thread. The handler ends with
  the explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a
  background thread needs, and a `threading.Lock` keeps two quick taps from each allocating
  that memory and racing to write the same file.
- **A wrong passphrase handled as an expected outcome** — Fernet authenticates the token
  before it decrypts, so a key that does not match raises `InvalidToken` rather than
  returning garbage. The app catches it and shows it as `TextField.error`; left uncaught in a
  worker thread it would vanish silently.
- **Ciphertext in app storage** — the file goes in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  the app-private directory that is never auto-deleted and is included in backups.
- **Which build you are actually running** — the header line prints the cryptography version
  and the OpenSSL it links, both of which change with the Python version you build for.

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
