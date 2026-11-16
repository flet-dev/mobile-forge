# surrealdb-embedded

The native engine behind [SurrealDB](https://surrealdb.com/)'s Python SDK in embedded mode.
With it, a Flet app runs a full SurrealDB database inside itself, with SurrealQL, record
links, full-text and vector search, and keeps it in a file on the device, with no server
and no network.

This wheel compiles SurrealDB's Rust core for Android and iOS. The SDK itself,
[`surrealdb`](https://pypi.org/project/surrealdb/), is pure Python and installs from PyPI.

## Install

```toml
dependencies = [
    "flet",
    "surrealdb[embedded]==3.0.0",
]

[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

The `embedded` extra pulls in this package at the matching version. The `target_arch` line
is required: there is no 32-bit ARM (`armeabi-v7a`) build, and `flet build apk` targets
that ABI by default, so without the line the build fails resolving it. `x86_64` is only for
the emulator; a release for phones can use `["arm64-v8a"]` alone.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`notes`](examples/notes) — a notes list in a SurrealKV datastore that survives restarts.

## Usage in a Flet app

Open one connection when the app starts and share it. Keep the datastore in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables#flet_app_storage_data),
Flet's persistent, app-private storage:

```python
import os
from pathlib import Path

from surrealdb import AsyncSurreal, RecordID

path = Path(os.environ["FLET_APP_STORAGE_DATA"]) / "app.db"
db = AsyncSurreal(f"surrealkv://{path}")
await db.connect()
await db.use("app", "main")
await db.query("DEFINE TABLE IF NOT EXISTS notes SCHEMALESS;")

await db.create(RecordID("notes", "first"), {"text": "Saved on the device"})
(rows,) = await db.query("SELECT * FROM notes;")
```

`surrealkv://` stores data on disk; `mem://` gives an in-memory database that is gone when
the app closes.

### Threading

The async client, `AsyncSurreal`, can be awaited directly in Flet's async event handlers
without blocking the UI. The sync client, `Surreal`, blocks: call it from
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), and end
the worker with [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Storage

A SurrealKV datastore is a directory (`LOCK`, `manifest`, `sstables`, `vlog`, `wal`), not a
single file. The engine also creates a `surrealdb/` spill directory under the system temp
directory while it runs. Data written before the app is killed survives: in our runs a
force-stopped app reopened with every committed note intact.

### App size

The native library is large: about 26 MB on Android arm64-v8a and 20 MB on an iPhone,
uncompressed, and 32 MB and 27 MB on the x86_64 emulator and simulator. Shipping only the
ABIs you need, through `target_arch`, is the main lever on Android.

### Other considerations

Everything above runs offline. The same SDK can also connect to a SurrealDB server over
`ws://` or `http://`; that path does not use this package.

On a desktop, `flet run` installs PyPI's own `surrealdb-embedded` wheels, so desktop and
device run the same engine version.

## Things to know

- **Reading a table that was never defined raises `NotFoundError`,** even if you only
  expected an empty result. Define your tables (`DEFINE TABLE IF NOT EXISTS ...`) when you
  open the datastore.
- **A datastore can be opened once per process.** A second connection to the same
  `surrealkv://` path fails with `ConnectionUnavailableError` because the first holds the
  lock. Keep one connection for the life of the app instead of opening one per handler.
- **`query()` returns one result list per statement,** so a single `SELECT` comes back as
  `[[row, ...]]`.

## Build notes (maintainers)

### Recipe shape

A maturin (PyO3) package with no recipe-side source changes beyond its `Cargo.toml`. Two
patches:

- `no-abi3.patch` (both platforms) drops PyO3's `abi3-py39` feature. On iOS, abi3 links
  against `libpython3.9`, which no iOS Python tree has; dropping it on Android as well gives
  every Python its own wheel, like the other PyO3 recipes.
- `ios-libc.patch` (iOS only) pins `libc` to 0.2.189. The sdist's `Cargo.lock` has 0.2.190,
  which restricts Mach APIs that `sysinfo` 0.39.6 still uses on iOS to macOS.

`AWS_LC_SYS_CMAKE_BUILDER=1` builds AWS-LC with CMake (hence `cmake` in
`requirements.build`), which filters out the `-O3` that cc-rs otherwise appends after
jitterentropy's mandatory `-O0`. `ANDROID_NDK_ROOT` points that CMake build at the NDK.

`armeabi-v7a` is excluded: `surrealdb-cnf` uses `std::sync::atomic::AtomicU64`, which
32-bit ARM lacks. Upstream ships no 32-bit ARM wheels either.

### Upgrade hazards

- **The libc pin is tied to `sysinfo` 0.39.6.** On a bump, drop `ios-libc.patch` first and
  see whether the iOS build passes without it; a newer `sysinfo` may no longer need it.
- **The `surrealdb` SDK pins `surrealdb-embedded` exactly** through its `embedded` extra.
  Bump this recipe together with each SDK release, or apps cannot resolve both.
- **armeabi-v7a may become buildable** if SurrealDB's crates move to `portable-atomic`; the
  build error names the crate that still uses a raw `AtomicU64`.

### Re-verification checklist

- Every wheel is tagged for its own Python (`cp312-cp312`, ...), not `cp39-abi3`.
- iOS: `otool -hv` on `_ext.cpython-*.so` reports `DYLIB`.
- The device tests pass on every Python, including `test_persistent_database`, which
  reopens a SurrealKV datastore.
- The example's launch count increases across a full restart, on both platforms.

### Coverage gaps

The device tests cover loading the engine, sync CRUD and a query, a SurrealKV datastore
surviving a close and reopen, and the async client. CI runs them on the x86_64 Android
emulator and the iPhone simulator; the arm64-v8a slice ran only in the example on an
arm64 emulator, and the iPhone-device slice is built but never run. Full-text, vector and
geo search, live queries and transactions are compiled in but untested here.
