# apsw

[`apsw`](https://rogerbinns.github.io/apsw/) (Another Python SQLite Wrapper) is a complete,
thin wrapper around SQLite that **statically embeds its own copy of the engine**. That is the
reason to reach for it on mobile: your app gets one SQLite — same version, same extensions,
same limits — on Android and on iOS, instead of the two different engines the stdlib `sqlite3`
module gives you.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "apsw",
]
```

**Android needs Flet 0.86.0 or newer.** Below that the wheel still installs and `import apsw`
still succeeds, but it hands you an empty module — the first attribute you touch, usually
`apsw.Connection`, raises `AttributeError`. A bare `flet` resolves to the latest release, so
this only bites when something in your project holds Flet back; add `flet>=0.86.0` if you pin
Flet at all.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`notes`](examples/notes) — a note list that survives restarts.

## Usage in a Flet app

Apply [`apsw.bestpractice`](https://rogerbinns.github.io/apsw/bestpractice.html) before opening
anything, put the database in app storage, raise the busy timeout, and pour the rows into a
[`ft.ListView`](https://flet.dev/docs/controls/listview/):

```python
import os

import apsw
import apsw.bestpractice
import flet as ft

apsw.bestpractice.apply(apsw.bestpractice.recommended)

db = apsw.Connection(os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "notes.db"))
db.set_busy_timeout(5000)
db.execute("CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, text TEXT)")

rows = list(db.execute("SELECT id, text FROM notes ORDER BY id DESC"))
listing = ft.ListView(
    controls=[ft.Text(f"{note_id}. {text}") for note_id, text in rows],
    expand=True,
)
```

### Storage

Put the database in [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From
Flet 0.86.0 it is also the process working directory on device, so a bare relative filename
lands there; spelling it out costs one line and behaves the same on desktop.

Never keep a database in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

In WAL mode — which `apsw.bestpractice` turns on — SQLite keeps `notes.db-wal` and
`notes.db-shm` next to the database while it is open, and removes them when the last connection
closes cleanly. A second open connection, or the OS killing a backgrounded app, leaves them in
place; that is harmless, SQLite recovers on the next open, but it means you cannot assume they
are gone. If you export, copy or back up a database, take all three files together — or
checkpoint first with `db.pragma("wal_checkpoint", "TRUNCATE")`, or use
[`Connection.backup`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.backup).

### Threading

A `Connection` can be used from **any** thread — unlike the stdlib, which refuses cross-thread
use outright unless you pass `check_same_thread=False`. What it cannot do is serve **two
threads at the same time**: apsw detects the overlap and raises
[`ThreadingViolationError`](https://rogerbinns.github.io/apsw/exceptions.html#apsw.ThreadingViolationError)
(`Cursor couldn't run because the Connection is busy in another thread`) instead of waiting.

That matters in Flet because
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) hands your
work to a thread pool — some worker thread, not the one your event handlers run on, and two
taps in quick succession really can overlap. So either guard a shared connection with a
`threading.Lock` (what the example does) or give each thread its own `Connection`. Take the
lock around the *whole* use, including consuming any `SELECT`: an unconsumed cursor is exactly
what leaves the connection busy.

Get this wrong and the failure is silent — `run_thread` never retrieves the worker's future, so
the exception surfaces nowhere and the write just goes missing.

Threads buy you no parallelism on a single connection; serialized mode mutexes every call on
it. In WAL mode a second `Connection` genuinely does read while another writes, so open one if
a long write must not block reads.

Auto-update also does not reach background threads — end a `run_thread` handler with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Which SQLite you are talking to

This recipe builds apsw with its `enable_all_extensions` setting, and the resulting set is
asserted by the recipe's on-device tests: FTS3/FTS4/FTS5, RTree, geopoly, session and
changesets, the preupdate hook, STAT4, dbstat, column metadata, carray, percentile and math
functions; JSON1/JSONB come with modern SQLite. `MAX_ATTACHED` is 125 and `MAX_FUNCTION_ARG`
1000, where both *mobile* stdlib builds ship SQLite's defaults of 10 and 127 (desktop CPython
builds vary, so don't check this one on your Mac). Read the full list off a device with
[`apsw.compile_options`](https://rogerbinns.github.io/apsw/apsw.html#apsw.compile_options).

The stdlib's engine, by contrast, moves under you. Android's Python bundles its own SQLite —
currently older than apsw's, and with a smaller extension set (no session, STAT4, dbstat,
column metadata, carray or percentile) — which changes whenever Flet's Python build is bumped.
On iOS the stdlib links whatever `/usr/lib/libsqlite3.dylib` the OS release happens to ship, so
it varies by device and moves under you on OS updates. Neither mobile stdlib build can load
extensions at all. The `notes` example prints all three versions, which is the quickest way to
see the spread on a device you care about.

Beyond one engine everywhere, switching also buys you a connection usable from any thread,
[transactions that happen only when you ask for them](https://rogerbinns.github.io/apsw/pysqlite.html)
and nest via savepoints, 40-odd
[specific exception classes](https://rogerbinns.github.io/apsw/exceptions.html) instead of a
handful of DBAPI ones, and virtual tables, VFS and FTS5 tokenizers written in Python. Do
**not** switch expecting blob I/O, the backup API, serialize/deserialize, authorizers or window
functions — the mobile stdlib already has all of those.

### App size

The wheel is approximately 2 MB compressed and 5.3 MB unpacked per architecture, roughly 80% of
which is the two native extensions.

About 0.8 MB of that unpacked total (0.2 MB compressed) is apsw's own `apsw/tests` package,
which upstream ships and no app imports, so Flet's
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) can drop it:

```toml
[tool.flet.cleanup]
package_files = ["**apsw/tests"]
```

The missing slash after the leading wildcard is not a typo: serious_python matches each glob
with Dart's `Glob` against the absolute entry path, so `**/apsw/tests` would insist on a
separator there and miss a top-level `apsw/`. **That glob has not been verified against a build
here** — check it by opening the artifact, and note that the globs run *after* serious_python
has compiled the package and deleted the `.py` files, so what is left to match is bytecode:

```bash
unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l /tmp/sp.zip | grep apsw
```

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These are package figures, not the amount added to the
final APK or IPA; packaging and compression determine that.

### Other considerations

A desktop `flet run` resolves PyPI's own apsw wheel, which is a different build from this one:
it bundles the prebuilt SQLite extensions and CLI tools, and it has the fork checker. So
[`apsw.sqlite_extra.load(...)`](https://rogerbinns.github.io/apsw/extra.html#apsw.sqlite_extra.load)
and [`apsw.fork_checker()`](https://rogerbinns.github.io/apsw/apsw.html#apsw.fork_checker)
succeed on your Mac and fail on device. The comparison against the stdlib is desktop-specific
in the same way: the SQLite your Mac's `sqlite3` module reports is neither of the two mobile
ones. Anything resting on either — an optional extension, a version check, a limit — has to be
validated on a device or emulator/simulator, not under `flet run`.

## Things to know

- **Apply [`apsw.bestpractice`](https://rogerbinns.github.io/apsw/bestpractice.html) before you
  open anything.** `apsw.bestpractice.apply(apsw.bestpractice.recommended)` installs connection
  hooks, so it only affects connections created *after* the call — put it at module import. It
  gives you WAL, `foreign_keys=ON`, `recursive_triggers=ON`, no double-quoted string literals,
  planner stats, SQLite's log forwarded to Python `logging`, and a 100 ms busy timeout. Raise
  that last one:
  [`db.set_busy_timeout(5000)`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.set_busy_timeout)
  after opening. (Wrapping the hook in `functools.partial` to change it does not work —
  `apply()` reads `func.__name__`.)
- **`import apsw.bestpractice` loads a second native extension.** So do `apsw.ext`, `apsw.fts5`
  and `apsw.unicode` — they all pull in `apsw/_unicode`. Plain `import apsw` does not. Both
  `.so` files ship in every wheel regardless; the point is just that these imports load two
  native extensions at runtime rather than one.
- **What this wheel does not carry.** Upstream's PyPI wheels bundle nearly 60 prebuilt binaries
  — 38 SQLite loadable extensions plus 19 CLI tools (`vec1`, `sqlar`, `regexp`, `spellfix`,
  `uuid`, `csv`, the `sqlite3` shell…). Those are host binaries, so the mobile wheels ship none
  of them and `apsw.sqlite_extra.load(...)` raises `NotAvailable`. There is no ICU either, so
  ICU collations are unavailable — FTS5's `unicode61` tokenizer with `remove_diacritics 2`
  still folds accents. `apsw.fork_checker()` is absent (a debugging aid that is meaningless in
  an app that never forks).
  [`Connection.load_extension`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.load_extension)
  itself *is* compiled in, so your own extension is loadable if you ship and sign it.

## Build notes (maintainers)

### Recipe shape

apsw's package `__init__` *is* the native extension rather than a Python file importing one,
and Android packaging has to handle that shape specially. That, not any apsw version, is where
the Flet 0.86.0 floor in **Install** comes from: 0.86.0 is the first release whose pinned
serious_python handles it. Should upstream ever move the extension out of the package
`__init__`, that paragraph stops applying and should go.

There is no `flet-libsqlite3` recipe underneath this one and nothing to relocate at runtime:
apsw fetches a version-matched SQLite amalgamation at build time and compiles it statically in.
One self-contained engine per wheel is the entire reason the package is worth having on mobile,
so do not turn it into a shared-library chain.

### Upgrade hazards

- A version bump moves SQLite underneath every consumer claim on this page at the same time,
  because the amalgamation is fetched to match. The version, the compiled-in extension set and
  the two limits all travel with `package.version`.
- The stdlib comparison rots without anyone touching this recipe. That Android's bundled SQLite
  is older than apsw's, that its extension set is smaller, and that both mobile stdlib builds
  cap attachments at 10 and function arguments at 127, all follow from Flet's Python build — so
  a Flet bump invalidates them as surely as an apsw bump does.

### Re-verification checklist

- The compiled-in extension set, `MAX_ATTACHED` and `MAX_FUNCTION_ARG` are asserted by
  `tests/test_apsw.py::test_extensions_compiled_in`, so losing any of them turns CI red on its
  own. Add to that set whenever this page starts promising something new.
- Nothing checks that the patch still *does* what it says, only that it applies. Unpack a built
  wheel and confirm `apsw/sqlite_extra_binaries/` holds nothing but upstream's README, and that
  `apsw.fork_checker` is gone. Both failures are silent: a wheel with host binaries baked into
  it installs and imports perfectly well.
- Re-read the stdlib numbers off a device, not off your Mac. The `notes` example prints the
  three versions on screen; it prints no limits, so the 10/127 claim needs a separate read —
  `sqlite3.connect(":memory:").execute("PRAGMA compile_options")`, where the *absence* of
  `MAX_ATTACHED`/`MAX_FUNCTION_ARG` entries is what "ships SQLite's defaults" means.
- The size figures, including the share that is apsw's own `tests` package, are measured.
  Re-measure them rather than adjusting them by eye, and quote decimal MB.

### Coverage gaps

The six device tests cover version consistency, an in-memory round-trip, the
`apsw.bestpractice` import that loads the second native extension plus the hooks it installs, a
file database in WAL mode with its sidecar lifecycle and a reopen, the locked-connection
pattern under a thread pool, and the compiled-in extension set. A green run does not cover:

- the stdlib comparison — nothing reads the platform's own SQLite version, extension set or
  limits, so every number in **Which SQLite you are talking to** is prose only;
- the patch's effect — that `apsw/sqlite_extra_binaries/` is empty and `fork_checker` is gone
  is checked by hand, per the item above;
- ICU collations and the FTS5 `unicode61` / `remove_diacritics 2` claim;
- the WAL claim that a second `Connection` reads while the first writes;
- anything iOS-specific. Every test is platform-neutral, so a green iOS leg proves the wheel
  imports and SQLite works there — not that any of the above holds.
