# apsw notes

A one-screen note list whose rows live in a real SQLite database file, written and read by
[apsw](https://rogerbinns.github.io/apsw/). Add a note, kill the app, reopen it — the notes
are still there.

What it demonstrates:

- **A database in app storage** — the file goes in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  the app-private directory that is never auto-deleted and is included in backups.
- **[`apsw.bestpractice`](https://rogerbinns.github.io/apsw/bestpractice.html) applied
  before the connection is opened**, which is the only order that works, plus a busy
  timeout raised from its thin 100 ms default.
- **Writes from [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)**
  — one `apsw.Connection` reused by the thread pool behind a `threading.Lock`, because apsw
  raises [`ThreadingViolationError`](https://rogerbinns.github.io/apsw/exceptions.html#apsw.ThreadingViolationError)
  if a connection is used from two threads at once, plus the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs.
- **Which SQLite you are actually talking to** — the header line prints the version apsw
  embeds next to the one the stdlib `sqlite3` module sees; today they differ on device.

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
