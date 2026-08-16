# apsw

[`apsw`](https://rogerbinns.github.io/apsw/) (Another Python SQLite Wrapper) is a
complete, thin wrapper around SQLite that **statically embeds its own copy of the
engine**. That is the reason to reach for it on
mobile: your app gets one SQLite — same version, same extensions, same limits — on Android
and on iOS, instead of the two different engines the stdlib `sqlite3` module gives you.
It has no runtime dependencies and never touches the network.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "apsw",
]
```

Nothing else to configure: apsw pulls in no other packages, and needs no
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry. It builds for all three Android ABIs Flet
targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS, on Python 3.12, 3.13 and 3.14 —
every version Flet's mobile runtime currently supports.

**Android needs Flet 0.86.0 or newer:** apsw's package `__init__` *is* the native
extension — a shape Android packaging has to handle specially — and 0.86.0 is the first
release whose pinned serious_python does. A bare `flet` resolves to the latest release, so
this only bites if something in your project holds Flet back; below 0.86.0 the wheel still
installs and `import apsw` gives you an empty module, so add `flet>=0.86.0` if you pin
Flet at all.

## Storage

Put the database in [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From
Flet 0.86.0 it is also the process working directory on device, so a bare relative
filename lands there; spelling it out costs one line and behaves the same on desktop:

```python
db = apsw.Connection(os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "notes.db"))
```

Never keep a database in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

In WAL mode — which `apsw.bestpractice` turns on — SQLite keeps `notes.db-wal` and
`notes.db-shm` next to the database while it is open, and removes them when the last
connection closes cleanly. A second open connection, or the OS killing a backgrounded
app, leaves them in place; that is harmless, SQLite recovers on the next open, but it
means you cannot assume they are gone. If you export, copy or back up a database, take
all three files together — or checkpoint first with
`db.pragma("wal_checkpoint", "TRUNCATE")`, or use
[`Connection.backup`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.backup).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`notes`](examples/notes) — a note list that survives restarts.

## Threading

A `Connection` can be used from **any** thread — unlike the stdlib, which refuses
cross-thread use outright unless you pass `check_same_thread=False`. What it cannot do is
serve **two threads at the same time**: apsw detects the overlap and raises
[`ThreadingViolationError`](https://rogerbinns.github.io/apsw/exceptions.html#apsw.ThreadingViolationError)
(`Cursor couldn't run because the Connection is busy in another thread`) instead of
waiting.

That matters in Flet because
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) hands
your work to a thread pool — some worker thread, not the one your event handlers run on,
and two taps in quick succession really can overlap. So either guard a shared connection
with a `threading.Lock` (what the example does) or give each thread its own `Connection`.
Take the lock around the *whole* use, including consuming any `SELECT`: an unconsumed
cursor is exactly what leaves the connection busy.

Get this wrong and the failure is silent — `run_thread` never retrieves the worker's
future, so the exception surfaces nowhere and the write just goes missing.

Threads buy you no parallelism on a single connection; serialized mode mutexes every call
on it. In WAL mode a second `Connection` genuinely does read while another writes, so
open one if a long write must not block reads.

Auto-update also does not reach background threads — end a `run_thread` handler with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Things to know

- **Apply [`apsw.bestpractice`](https://rogerbinns.github.io/apsw/bestpractice.html) before
  you open anything.** `apsw.bestpractice.apply(apsw.bestpractice.recommended)`
  installs connection hooks, so it only affects connections created *after* the call — put
  it at module import. It gives you WAL, `foreign_keys=ON`, `recursive_triggers=ON`, no
  double-quoted string literals, planner stats, SQLite's log forwarded to Python `logging`,
  and a 100 ms busy timeout. Raise that last one: `db.set_busy_timeout(5000)` after opening.
  (Wrapping the hook in `functools.partial` to change it does not work — `apply()` reads
  `func.__name__`.)
- **`import apsw.bestpractice` loads a second native extension.** So do `apsw.ext`,
  `apsw.fts5` and `apsw.unicode` — they all pull in `apsw/_unicode`. Plain `import apsw`
  does not. Both `.so` files ship in every wheel regardless; the point is just that these
  imports load two native extensions at runtime rather than one.
- **What this wheel does not carry.** Upstream's PyPI wheels bundle nearly 60 prebuilt
  binaries — 38 SQLite loadable extensions plus 19 CLI tools (`vec1`, `sqlar`, `regexp`,
  `spellfix`, `uuid`, `csv`, the `sqlite3` shell…). Those are host binaries, so the mobile
  wheels ship none of them and `apsw.sqlite_extra.load(...)` raises `NotAvailable`. There
  is no ICU either, so ICU collations are unavailable — FTS5's `unicode61` tokenizer with
  `remove_diacritics 2` still folds accents. `apsw.fork_checker()` is absent (a debugging
  aid that is meaningless in an app that never forks).
  [`Connection.load_extension`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.load_extension)
  itself *is* compiled in, so your own extension is loadable if you ship and sign it.
- **Compiled in, and asserted by this recipe's tests:** FTS3/FTS4/FTS5, RTree, geopoly,
  session and changesets, the preupdate hook, STAT4, dbstat, column metadata, carray,
  percentile and math functions; JSON1/JSONB come with modern SQLite. `MAX_ATTACHED` is 125
  and `MAX_FUNCTION_ARG` 1000, where both *mobile* stdlib builds ship SQLite's defaults of
  10 and 127 (desktop CPython builds vary, so don't check this one on your Mac).
- **What you actually gain over the stdlib `sqlite3` module.** One engine on both platforms
  is the big one. Android's stdlib bundles its own SQLite — currently older than apsw's,
  and with a smaller extension set (no session, STAT4, dbstat, column metadata, carray or
  percentile) — which moves whenever Flet's Python build is bumped. On iOS the stdlib links
  whatever `/usr/lib/libsqlite3.dylib` the OS release happens to ship, so it varies by
  device and moves under you on OS updates. The example prints all three numbers, which is
  the quickest way to see the spread on a device you care about. Neither mobile stdlib build can
  load extensions at all. Add to that: a connection usable from any thread,
  [transactions that happen only when you ask for them](https://rogerbinns.github.io/apsw/pysqlite.html)
  and nest via savepoints, 40-odd
  [specific exception classes](https://rogerbinns.github.io/apsw/exceptions.html) instead
  of a handful of DBAPI ones, and virtual tables, VFS and FTS5 tokenizers written in
  Python. Do **not** switch expecting blob I/O, the backup API,
  serialize/deserialize, authorizers or window functions — the mobile stdlib already has
  all of those.
- **Size.** The wheel is about 2 MB, roughly 80% of which is the two extensions; unpacked
  on device it is about 5.3 MB. Some 0.8 MB of that (0.2 MB compressed) is apsw's own
  `apsw/tests` package, which upstream ships and your app will never import.

## Build notes (maintainers)

`mobile.patch` neutralises three host-tainted behaviours in apsw's sdist build, all of
which would otherwise bake the *build* machine into a *target* wheel:

1. **`./configure` inside `sqlite3/`** is dropped. What it generates is
   `sqlite3/sqlite_cfg.h` (consumed via `_HAVE_SQLITE_CONFIG_H=1`) — libc `HAVE_*` probes
   measured on the build host rather than the target. The `SQLITE_ENABLE_*` features we
   depend on come from apsw's own `-D` flags (`enable_all_extensions`), which is why
   dropping configure costs no functionality — confirmed by the compile options in the
   shipped wheels.
2. **`fc.all = False`** limits the download to the SQLite amalgamation instead of also
   pulling sqlite-src, vec1, sqlar and zlib. Observable effect: the shipped wheels'
   `apsw/sqlite_extra_binaries/` contains nothing but upstream's README, i.e. no host
   binaries leak into a mobile wheel. (Mechanism: with the full source absent, apsw's
   `tools/vend.py` extension build never runs — it compiles via `customize_compiler()` and
   would target the build host.)
3. **`APSW_FORK_CHECKER`** is removed; it is compiled in whenever the *build* Python has
   `os.fork`, and relies on `pthread_atfork`.

The amalgamation is compiled straight into the extension
(`APSW_USE_SQLITE_AMALGAMATION`), so there is no external `libsqlite3` to link and no
`flet-lib*` dependency.
