# SurrealDB offline notes

A notes list stored in an embedded SurrealDB datastore on the device. There is no server and
no network: the database engine runs inside the app and keeps its files in the app's
private storage.

What it demonstrates:

- **Opening the datastore once.** `open_notebook()` in [`src/notebook.py`](src/notebook.py)
  connects to `surrealkv://<app storage>/notes.db` when the app starts, and every handler
  shares that one connection. A second connection to the same path fails on the datastore's
  lock.
- **Data that survives restarts.** The status line counts launches in a record of its own.
  Close the app completely, open it again, and both the count and your notes are still there.
- **Defining tables before reading them.** SurrealDB raises `NotFoundError` when you select
  from a table that was never defined, even an empty one, so the app defines both of its
  tables on open.
- **The async API in Flet handlers.** `AsyncSurreal` calls are awaited directly in Flet's
  async event handlers, so nothing blocks the UI.

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
