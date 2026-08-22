# sqlalchemy expense ledger

An expense ledger held in a real SQLite file on the phone by two mapped classes and a
relationship, with a slider that decides how many expenses to write and a grouped aggregate
over them computed by
[SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/quickstart.html) rather than by Python.
Nothing is bundled and nothing is downloaded: the rows come out of a fixed seed, so every
install holds the same data and two devices can be compared number for number. Kill the app
and reopen it — the ledger is still there and the same totals come back.

What it demonstrates:

- **A database in app storage that survives a restart** — the file goes in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  built from
  [`URL.create`](https://docs.sqlalchemy.org/en/20/core/engines.html#sqlalchemy.engine.URL.create)
  rather than a hand-assembled `sqlite:///` string, with a one-connection pool and a
  [`connect`](https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.connect)
  listener that puts WAL, a busy timeout and foreign keys on every connection. The header reads
  the journal mode back off the connection, so you can see they took.
- **A grouped aggregate whose numbers check out** — the rollup is a join with `GROUP BY`,
  `count`, `sum` and `avg`, and the per-category totals on screen add up to the row underneath
  them, which comes from a separate query rather than the same figure printed twice.
- **Typed columns and a relationship, which is the reason to reach for the ORM at all** —
  `Numeric(10, 2)` money, a `DateTime`, an indexed foreign key, and a
  [`relationship`](https://docs.sqlalchemy.org/en/20/orm/relationship_api.html) used in both
  directions: the rollup joins through `Category.expenses`, and the line under the table loads
  the single biggest expense as an *object* and reaches its category through `Expense.category`.
  That line is where the type layer becomes visible — SQLite has neither a decimal nor a date
  type, so the file holds `real` and `text` while the object holds a `Decimal` and a `datetime`.
- **Writes off the UI thread** — the reseed runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  slider disabled, a non-blocking lock catching the tap already in flight, a `try/except` around
  the worker and the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs.
- **ORM versus Core over the same rows** — one button loads every expense as an object and sums
  an attribute, then reads the same amounts as Core rows, and prints both timings with both
  totals. That is where the five compiled Cython extensions are visible at work, and printing
  the two totals side by side is what shows they are a speed change and not a behaviour change.
- **What is actually underneath** — the header prints the SQLAlchemy version, whether the
  compiled extensions loaded (and the reason if they did not), the SQLite version the stdlib
  `sqlite3` module reports, the pool class and size, the journal mode, and whether `greenlet`
  came along. Every one of those can differ from what a desktop run shows.
- **Where the bytes are** — a storage line with the database file's size next to its `-wal` and
  `-shm` sidecars, which is how you find out that a fresh write is still sitting in the WAL and
  that all three files are one database.

`src/ledger.py` owns the engine, the mapped classes and the queries; `src/main.py` is the
screen and the thread plumbing.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

`flet run` works too — the same pins resolve on desktop, and the app makes no mobile-only
assumptions. What differs there is exactly what the header prints: a desktop wheel has its own
compiled extensions and its own SQLite.

To see the app with the accelerators off — which is what a slice whose `.so` files failed to
load would look like — run it with `DISABLE_SQLALCHEMY_CEXT_RUNTIME=1` set. The numbers come out
identical and the header says `C ext OFF`.
