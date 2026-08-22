# sqlalchemy

[`SQLAlchemy`](https://docs.sqlalchemy.org/en/20/) is the Python SQL toolkit and ORM:
[mapped classes](https://docs.sqlalchemy.org/en/20/orm/quickstart.html) with relationships and
typed columns, a query builder that composes instead of concatenating, and a connection pool
underneath. On a phone the case for it is that the local database is the part of an app that
outlives the screen it was written for — the stdlib `sqlite3` module hands you SQL strings and
tuples, while SQLAlchemy hands you a schema you can evolve and objects you can put straight into
controls, over the very same engine.

**This wheel is a speed upgrade, not what makes SQLAlchemy work on mobile.** Upstream publishes
a pure-Python universal wheel that installs on every mobile target already; these wheels are
that same wheel plus the five compiled Cython extensions SQLAlchemy's hot paths prefer. Upstream's
documentation applies verbatim and nothing about your code changes.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "sqlalchemy",
]
```

**A bare `sqlalchemy` gets you the pure-Python wheel, not this one, whenever PyPI is ahead of this
index.** `flet build` installs with
`pip install --upgrade --only-binary :all: --extra-index-url https://pypi.flet.dev`, so pip sees
PyPI *and* this index and takes the highest version it can use — and a `py3-none-any` wheel is
usable on every mobile target, so upstream wins on version alone the moment it releases past the
version here. Measured with this index at 2.0.50 and PyPI at 2.0.52, a bare `sqlalchemy` resolved
to `sqlalchemy-2.0.52-py3-none-any.whl` on every slice and Python minor tried. Nothing breaks and
no error appears anywhere; what you lose is the speed this recipe exists for, and the only thing
that will tell you is the `has_compiled_ext()` probe in [Things to know](#things-to-know). Pin
`sqlalchemy` to the version in [`meta.yaml`](meta.yaml) to get the extensions on every slice; the
[`expense-ledger`](examples/expense-ledger) example does.

**Ask for async explicitly: `sqlalchemy[asyncio]`, or `sqlalchemy[aiosqlite]` for an async SQLite
driver as well.** Both resolve on every mobile slice. Left to a bare `sqlalchemy`, an async engine
imports and constructs fine and then raises `ValueError: the greenlet library is required to use
this function` at the first `await` — and whether it does is decided by the CPU of the machine that
ran `flet build` rather than by your project. That trap is in
[Things to know](#things-to-know); it is the one entry on this page that turns a working project
into a broken one without anybody changing a line.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`expense-ledger`](examples/expense-ledger) — a mapped, related, restart-surviving expense
  ledger with a grouped aggregate over it and an ORM-versus-Core timing.

## Usage in a Flet app

Open a file database in app storage, run a grouped query, and put the rows into controls:

```python
engine = create_engine(
    URL.create("sqlite", database=os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "ledger.db")),
    pool_size=1,
    max_overflow=0,
)
Base.metadata.create_all(engine)

with Session(engine) as session:
    rows = session.execute(
        select(Category.name, func.sum(Expense.amount))
        .join(Category.expenses)
        .group_by(Category.name)
    ).all()

table = ft.Column([ft.Text(f"{name}  {total:,.2f}") for name, total in rows])
```

`total` arrives as a `Decimal` rather than a float because the column is
[`Numeric`](https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Numeric), and
the category name comes off a mapped class rather than out of a string — that pair is the reason
to reach for the ORM over the stdlib module on a device.

### Storage

The database is an ordinary file, so it belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. Never keep one
in [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

Spell the URL with
[`URL.create`](https://docs.sqlalchemy.org/en/20/core/engines.html#sqlalchemy.engine.URL.create),
as above, and let it count the slashes. **An absolute path needs four, and "fixing" that writes
somewhere else instead of failing.** `sqlite:///` is the dialect plus an empty host and the path
follows, so an absolute one produces `sqlite:////data/user/0/com.x.y/files/app.db`.
`f"sqlite:///{abs_path}"` gets this right and so does `URL.create`; strip the leading slash to make
it look tidier and pysqlite's `create_connect_args` runs `os.path.abspath` on it, joining it onto
the process working directory with no error anywhere.

Three files make up one database once WAL is on (see [Threading](#threading)): `app.db`,
`app.db-wal` and `app.db-shm`. The `-wal` file holds committed data not yet checkpointed into the
main file, so the `.db` alone can stay tiny while the ledger is large — measured, 4 KB of `.db`
beside 1.01 MB of `-wal` after writing 12,000 rows. Copy, export or back up all three together, or
checkpoint first: `PRAGMA wal_checkpoint(TRUNCATE)` on a database with 1.89 MB in its WAL left the
`-wal` at zero bytes and the main file at 1.87 MB.

### Threading

**Use a file database and the defaults are already thread-safe.** For a file URL the pysqlite
dialect returns a
[`QueuePool`](https://docs.sqlalchemy.org/en/20/core/pooling.html#sqlalchemy.pool.QueuePool) and
sets `check_same_thread=False`, which is safe rather than reckless: the pool checks a sqlite3
connection out to one thread at a time. Eight threads, each expecting a *different* value and
reading back only its own rows, gave zero wrong values and zero exceptions.

**`create_engine("sqlite:///:memory:")` plus `page.run_thread` gives the worker a different, empty
database, and you will not be told.** A memory URL gets a `SingletonThreadPool` with
`check_same_thread=True`, so a second thread opens a second, blank in-memory database: the main
thread filled table `t`, the worker raised `OperationalError: (sqlite3.OperationalError) no such
table: t`, and [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
never retrieves the worker's future, so that exception surfaced nowhere. Upstream's
[StaticPool recipe](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#using-staticpool-for-single-connection-memory-databases)
is the fix and it works: `create_engine("sqlite:///:memory:", poolclass=StaticPool,
connect_args={"check_same_thread": False})` let the same worker read the rows.

**Shrink the pool.** The defaults are `pool_size=5, max_overflow=10, pool_timeout=30` with no
recycle — up to fifteen sqlite3 connections and file handles for a single-process app with one
user. `pool_size=1, max_overflow=0` is the honest figure for a phone; just know that a second
worker then waits on the pool for its 30 s timeout, so keep the non-blocking guard below.

**Two overlapping writers block for exactly 5 s and then raise.** `create_engine` turns nothing on:
on a fresh file engine `journal_mode` is `delete`, `synchronous` is `2` (FULL), `busy_timeout` is
sqlite3's own default `5000` and `foreign_keys` is `0`. A second write transaction opened while the
first was held raised after 5.2 s with `OperationalError: (sqlite3.OperationalError) database is
locked`.

Those are per-connection settings, so they cannot go in `create_engine` and a one-off `PRAGMA` does
not reach the next connection the pool opens. A
[`connect`](https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.connect)
listener is the mechanism — the same one upstream documents for
[foreign keys](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#foreign-key-support):

```python
@event.listens_for(engine, "connect")
def configure_connection(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

Measured to stick: `journal_mode` reads back `wal`, `foreign_keys` `1`, `busy_timeout` `5000`, and
the `-wal`/`-shm` files appear beside the database.

A query blocks the thread that issued it, so on the UI thread it freezes the UI. Push it to
`page.run_thread`, wrap the worker body in `try/except` — the framework discards what it raises —
and end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update does
not reach background threads. `run_thread` submits to a thread *pool*, so disabling a control does
not stop a tap already in flight; a non-blocking `threading.Lock` does.

### The SQLite underneath

The engine is not in this wheel. The default
[pysqlite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#module-sqlalchemy.dialects.sqlite.pysqlite)
dialect drives the stdlib `sqlite3` module, and that module links a different SQLite on each
platform: on Android the copy compiled into Flet's Python build, on iOS whatever
`/usr/lib/libsqlite3.dylib` the OS release ships. Measured on 2026-08-17 with Python 3.14,
**3.50.4 on Android** and **3.43.2 on the iPhone simulator**.

So the floor for any feature you depend on — a SQL function, a pragma, `RETURNING` — is whichever
of the two is older, and it moves when Flet bumps its Python build or Apple ships an OS update,
not when you bump a pin. Read `sqlite3.sqlite_version` off the device you actually target rather
than off this page; the [`expense-ledger`](examples/expense-ledger) example prints it in its
header. If one identical engine on both platforms is what you need, [`apsw`](../apsw) statically
embeds its own copy and has a recipe here.

### Drivers and dialects

SQLite needs nothing beyond this wheel and the standard library. Any other database needs a
driver, and most drivers have no mobile wheel anywhere. From `pip install --dry-run --only-binary
:all:` against this index plus PyPI, for android_24_arm64_v8a cp314:

| you want | add | what resolves |
| --- | --- | --- |
| SQLite | nothing | stdlib `sqlite3`, via the default `pysqlite` dialect |
| async SQLite | `sqlalchemy[aiosqlite]` | `aiosqlite` 0.22.1 (PyPI, pure Python) + `greenlet` 3.5.1 from this index |
| PostgreSQL | `sqlalchemy[postgresql]` | [`psycopg2`](../psycopg2) 2.9.12 from this index |
| Oracle | `sqlalchemy[oracle_oracledb]` | [`oracledb`](../oracledb) 4.0.1 + `cryptography` + `cffi` from this index |
| SQL Server | `sqlalchemy[mssql_pymssql]` | [`pymssql`](../pymssql) 2.3.13 + `flet-libfreetds` from this index |
| MySQL / MariaDB | `sqlalchemy[pymysql]` | `PyMySQL` 1.2.0 (PyPI, pure Python) |
| MySQL | `sqlalchemy[mysql_connector]` | `mysql-connector-python` 26.7.0 (PyPI, pure Python) |
| PostgreSQL, no C | `sqlalchemy[postgresql_pg8000]` | `pg8000` 1.31.5 + `scramp` + `asn1crypto` + `python-dateutil` + `six` (all PyPI, pure Python) |

Eleven of the twenty-three extras do not resolve for mobile at all, every one for want of a driver
wheel — whether pip says `Could not find a version that satisfies the requirement` or walks the
whole version history and gives up with a `ResolutionImpossible`: `mysql`, `mssql`,
`mssql_pyodbc`, `oracle`, `postgresql_asyncpg`, `postgresql_psycopg2binary`,
`postgresql_psycopg2cffi`, `asyncmy`, `sqlcipher`, `aioodbc` and `postgresql_psycopgbinary`. The
remaining twelve resolve: the seven above plus `asyncio`, `postgresql_psycopg`,
`mariadb_connector`, `aiomysql` and `mypy`.

### App size

About **2.1 MB to download and 8.5–9.0 MB unpacked** per wheel, of which only 4–10% is native: 274
files, 256 of them `.py` at 8.10 MB, the five extensions at 0.32 MB (armeabi-v7a), 0.49 MB (Android
arm64), 0.79 MB (arm64 simulator) or 0.87 MB (iOS device), and six Cython sources at 0.02 MB that
Flet's cleanup step deletes for you along with `py.typed` and `__pycache__`.

The lever that does not work here is compilation. Flet's default `compile.packages = true` makes
SQLAlchemy about **1.8 MB bigger** in the app, not smaller: serious_python runs `compileall -b` at
optimisation level 0 and SQLAlchemy's docstrings are enormous, so the bytecode is larger than the
source. Measured after Flet's own junk-file cleanup, the `sqlalchemy/` tree zips to 2.11 MB as
shipped `.py` and 3.91 MB as `.pyc` with the sources deleted (10.08 MB of `.pyc` against 8.10 MB
of `.py`); unpacked, 8.60 MB becomes 10.57 MB. Setting `packages = false` under
[`[tool.flet.compile]`](https://flet.dev/docs/publish/#compilation-and-cleanup) saves that 1.8 MB,
and the device then recompiles from source on every launch with no writable cache — a warm
`import sqlalchemy` alone already pulls 79 modules. Measure both on the target device; do not
switch it off reflexively for size. What cleanup leaves behind is 1.24 MB of remote-database
dialects you cannot reach without one of the drivers above (`postgresql` 0.47 MB, `mysql`
0.29 MB, `oracle` 0.28 MB, `mssql` 0.19 MB), plus SQLAlchemy's own `testing` package at 0.67 MB.

Every Android ABI Flet targets has a wheel here, on Python 3.12, 3.13 and 3.14, so
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) is a size
lever rather than a compatibility one: narrow it, or ship an app bundle or split APKs, when the app
does not need every ABI. These figures describe the package payload, not the exact amount added to
the final APK or IPA.

### Other considerations

A desktop `flet run` resolves from PyPI, which serves its own compiled wheel for the desktop
platform and links whatever SQLite that Python was built against — so both halves of what this
page describes differ there: the extensions come from a different build, and the engine is a third
version alongside the two above.

**Every timing and pool measurement in this section is from a desktop build of the same version.** Re-check the pragma
defaults, the pool behaviour and the timings on a device before designing around them.

## Things to know

- **Ask the library whether the accelerators loaded; never infer it from a module path.**
  `from sqlalchemy.util import has_compiled_ext; has_compiled_ext()` is the probe, and when it is
  `False`, `sqlalchemy.util._has_cy._CYEXTENSION_MSG` carries the reason — either the `ImportError`
  text or `DISABLE_SQLALCHEMY_CEXT_RUNTIME is set`. Two traps. First,
  `sqlalchemy.util.HAS_CYEXTENSION` is *not* re-exported and raises `AttributeError`; the name
  lives at `sqlalchemy.util._has_cy.HAS_CYEXTENSION`. Second, `_has_cy` imports all five extensions
  in one `try`/`except ImportError`, so one `.so` failing to load silently demotes the whole library
  to pure Python — and probing `sqlalchemy.cyextension.util.__file__` will not tell you, because
  Flet relocates every native extension: on Android that attribute is absent altogether and on iOS
  it reports a `.fwork` path (established in [`pydantic-core`](../pydantic-core)).

- **"Faster" is modest, and worth measuring on your own device rather than believing this bullet.**
  What the extensions replace is the per-row path — the `Row` base class, the tuplegetter, the
  date/`Decimal`/`float`/`str` result processors, parameter distillation, the SQL-compilation anon
  maps and the internal collection types — and a dump of 61 canonical results across all of them
  came out byte-identical with the extensions on and off, so this is a speed change and never a
  behaviour change. Desktop CPython 3.14 on an arm64 Mac, a 20,000-row table, best of nine runs,
  toggled with `DISABLE_SQLALCHEMY_CEXT_RUNTIME=1`: loading every row as ORM objects took 45 ms
  with against 50–65 ms without, and Core 11.4 ms against 12.3–13.4 ms, while compiling 2,000
  statements (119 ms against 124 ms) and a 20,000-row bulk insert (23 ms against 20 ms) stayed
  inside run-to-run noise in both directions. **How much you get scales with how many columns per
  row need a processor**: adding a `DateTime` column, so every row runs `str_to_datetime` as well
  as the `Decimal` conversion, gave 61–69 ms against 75–103 ms for the ORM load and 17.0–17.4 ms
  against 24.6–25.2 ms for Core, about 30% on both. So: high single digits to roughly a third on
  result loading depending on the column types, nothing measurable on compilation or inserts, and
  no device figure at all.

- **Async engines fail at the first `await`, not at import, and whether they fail is decided by the
  build machine.** `sqlalchemy/util/concurrency.py` wraps `import greenlet` in a `try`/`except` and
  installs stubs on failure, so with `aiosqlite` present and `greenlet` absent
  `create_async_engine(...)` constructs an `AsyncAdaptedQueuePool` happily and the first
  `async with engine.begin()` raises `ValueError: the greenlet library is required to use this
  function. No module named 'greenlet'`. It is a build-machine question because SQLAlchemy's base
  `greenlet` requirement is gated on `platform_machine` being one of `aarch64`, `ppc64le`, `x86_64`,
  `amd64`, `AMD64`, `win32`, `WIN32`, and serious_python's shim patches `platform.system`,
  `sysconfig.get_platform` and the `*_ver` functions but **not** `platform.machine`, so pip reads
  the host's. Measured: with `platform.machine() == "arm64"` (Apple Silicon), a bare `sqlalchemy`
  for android_24_arm64_v8a cp314 installs no greenlet at all; faking `x86_64` in the same shim
  installs greenlet 3.5.1. A project that works when built on an Intel Mac, Linux or Windows runner
  and breaks on Apple Silicon is this marker. Declaring `sqlalchemy[asyncio]` makes the question go
  away — verified to resolve on both Android arm64 and iOS arm64 device.

- **`sqlalchemy[aiomysql]` kills the app at import on iOS only.** iOS has no `pwd` module and leaves
  `LOGNAME`/`USER` unset, and aiomysql's module-level `DEFAULT_USER = getpass.getuser()` is guarded
  only by `except KeyError`, which is not what `getuser()` raises without `pwd`. On 3.12 you get
  `ModuleNotFoundError: No module named 'pwd'`; on 3.13 and 3.14 `getuser()` catches that itself and
  re-raises `OSError: No username set in the environment`. The fix is the same either way, since
  `getuser()` reads the environment first — set the variable before the import,
  `os.environ.setdefault("LOGNAME", os.environ.get("USER") or "fletuser")`, harmless on Android.

- **"pip resolved it" is not evidence a driver can connect.** `sqlalchemy[postgresql_psycopg]` and
  `sqlalchemy[mariadb_connector]` both resolve cleanly, from PyPI, as pure-Python wheels — and
  psycopg v3's pure-Python path does `ctypes.cdll.LoadLibrary` on a libpq it has to *find on the
  device*, raising `ImportError: libpq library not found` (re-raised as `ImportError: no pq wrapper
  available`) when it cannot, and there is no `psycopg` or `mariadb` on pypi.flet.dev to supply
  that half. For Postgres use the extra that pulls a driver with real mobile wheels,
  `sqlalchemy[postgresql]`. Neither failure was reproduced on a device here; the expected symptom
  is a ctypes error at import, not a resolution error.

- **There is no `sqlite+apsw` dialect** — `create_engine("sqlite+apsw:///x.db")` raises
  `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:sqlite.apsw`. SQLAlchemy and
  [`apsw`](../apsw) are alternatives, not a toolkit and its driver. `sqlite+pysqlcipher` does ship
  and is dead on both platforms — it raises `ModuleNotFoundError: No module named 'pysqlcipher3'`,
  and `sqlcipher3-binary` is a 404 on this index.

- **`create_all` creates missing tables and nothing else, so version 2 of your app cannot add a
  column with it.**
  [`MetaData.create_all`](https://docs.sqlalchemy.org/en/20/core/metadata.html#sqlalchemy.schema.MetaData.create_all)
  is `CREATE TABLE` per missing table and never issues an `ALTER`. Measured: a table created with
  two columns, then `create_all` run again from a `MetaData` declaring a third, still has two
  columns — no error, no warning — and the first query touching the new one raises
  `OperationalError: (sqlite3.OperationalError) no such column: t.b`. It only bites on *upgrade*,
  which is what makes it nasty: a fresh install builds the new schema correctly, so it passes every
  test on your desk and breaks for everyone who already had the app.
  [Alembic](https://alembic.sqlalchemy.org/) is the answer and resolves for mobile as pure Python
  (Android arm64 / 3.14: `alembic` 1.19.1, `mako`, and a compiled `markupsafe` from this index) —
  but it requires `SQLAlchemy>=1.4` unpinned, so adding it re-triggers exactly the resolution
  described in [Install](#install). Whether its migration scripts run *on a device* has not been
  tested here: they are ordinary `.py` files Alembic loads by path, and Flet's default
  `compile.packages` replaces them with `.pyc`.

- **`func.avg` comes back as a `float` where `func.sum` comes back as a `Decimal`.** `sum`, `max`
  and `min` inherit the column's type, so over a `Numeric` column they get the `Decimal` result
  processor; `func.avg(col).type` is `NullType()`, so no processor runs and the driver's raw float
  arrives. Mixing the two in a money total is how cents go missing.
  `func.avg(col, type_=Numeric(10, 2))` names the type explicitly.

- **`Numeric` survives the round trip exactly, but SQLite stores it as `REAL`.** Measured on a
  `Numeric(12, 2)` column: `select typeof(v), v` answers `('real', 0.1)` while SQLAlchemy reads back
  `Decimal('0.10')`, and `func.sum` returns a `Decimal` equal to the Python sum to the cent.
  `engine.dialect.supports_native_decimal` is `False`, so the conversion is SQLAlchemy's, not
  SQLite's — anything reading the file *outside* SQLAlchemy sees floats, and no warning is emitted
  either way. Identical with the C extensions disabled.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is three settings — name, version, build number — there are no patches, and no
`build.sh`. That is the fact worth recording: SQLAlchemy is a plain setuptools sdist with five
independent Cython modules and no external library, so it cross-compiles to all six slices on
forge's stock support alone. The day this recipe needs a patch, suspect the toolchain or an upstream
restructuring before reaching for one.

The wheels are upstream's universal wheel plus the extensions, byte for byte: all 269 non-`.so`
entries hash identical to `sqlalchemy-<version>-py3-none-any.whl` except `RECORD` and `WHEEL`,
`METADATA` included, and the Android and iOS wheels differ from each other only in those two files
and the extensions. That parity licenses the consumer claim that upstream's documentation applies
verbatim. It is also why no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is needed. That was measured, not assumed: instrumenting `importlib.metadata.entry_points` recorded **zero** calls across `create_engine("sqlite:///…")`, a connect and a `CREATE TABLE`. Re-run that probe on a bump — a dialect registry that started consulting entry points would break Android's zipimport with nothing else on this page to warn you:
nothing builds a path from `__file__`, reads a packaged data file or calls `inspect.getsource`, and
the package runs a mapped `select` with a `GROUP BY`, a `relationship` load and `Decimal`/`datetime`
conversion from a zip on `sys.path` with nothing unpacked.

### Upgrade hazards

**The recipe's whole reason for existing is currently unasserted, and a bump can silently remove
it.** `setup.py` builds each extension with `optional=not REQUIRE_EXTENSION`, where
`REQUIRE_EXTENSION = bool(os.environ.get("REQUIRE_SQLALCHEMY_CEXT"))`, and `meta.yaml` sets no
`build.script_env` — so a compile failure on any of the five is skipped, the build stays green, and
the wheel ships as pure Python that installs and imports perfectly. `tests/` does not catch it
either: both tests pass identically against an install with the extensions disabled
(`DISABLE_SQLALCHEMY_CEXT_RUNTIME=1 pytest -q` → 2 passed), despite the first one's docstring
claiming the wheel ships them. Two cheap fixes, both worth doing before the next bump:
`REQUIRE_SQLALCHEMY_CEXT: "1"` in `build.script_env` so a failed compile turns CI red, and a test
asserting `sqlalchemy.util.has_compiled_ext()` plus the five `sqlalchemy.cyextension.*` imports.

### Re-verification checklist

- **That five extensions were built, on all six slices.** `unzip -l` and count `cyextension/*.so`;
  the sdist should still hold exactly five `.pyx` plus `immutabledict.pxd`. A missing one is
  invisible, per *Upgrade hazards*.
- **The byte-for-byte parity with upstream's universal wheel.** A divergence means both the
  upstream-docs claim and the no-`extract_packages` claim in *Recipe shape* need revisiting.
- **The linkage lists.** Android `DT_NEEDED` is `libm`, `libpython3.<minor>`, `libdl` and `libc` and
  nothing else — no `libc++_shared`; iOS is `@rpath/Python.framework/Python` plus
  `/usr/lib/libSystem.B.dylib`, `MH_DYLIB`, two-level namespace, `NOUNDEFS`, with `LC_BUILD_VERSION`
  platform 2 / minos 13.0 on device, platform 7 / minos 14.0 on the arm64 simulator and platform 7 /
  minos 13.0 on the x86_64 one. Anything new is a runtime dependency **Install** does not mention.
  Re-check the 16 KB `PT_LOAD` alignment Android 15 requires too; that comes from forge, not here.
- **`Requires-Dist`, and specifically the `platform_machine` marker on `greenlet`.** The
  build-machine bullet in *Things to know* is a claim about that one marker; if upstream drops it,
  or serious_python starts patching `platform.machine`, the bullet becomes unnecessary rather than
  wrong. The async extras also pull [`greenlet`](../greenlet), which on Android pulls
  `flet-libcpp-shared` — a 407 KB wheel holding one 1.29 MB `opt/lib/libc++_shared.so` needing no
  configuration. Re-run the driver-extra resolves as well: that table is as much a statement about
  what else is on this index as about SQLAlchemy, so it rots when psycopg2, oracledb or pymssql
  move, and gains a row the day `psycopg`, `asyncpg` or `sqlcipher3-binary` get recipes.
- **Whether a bare `sqlalchemy` still loses to upstream's universal wheel** — the first thing
  **Install** tells an app author, and the one claim here that flips the moment a bump lands, since
  for however long this index is the newer of the two a bare requirement resolves *here* and that
  paragraph over-warns. Re-run `pip download --only-binary :all: --platform android_24_arm64_v8a
  --python-version 3.14 --implementation cp --abi cp314 --extra-index-url https://pypi.flet.dev
  sqlalchemy` and say which wheel came back rather than reasoning from version numbers. The pip
  flags quoted in **Install** are serious_python's `package_command.dart`.
- **The names the consumer sections lean on**: `sqlalchemy.util.has_compiled_ext`,
  `sqlalchemy.util._has_cy._CYEXTENSION_MSG`, `sqlalchemy.util.concurrency.have_greenlet` and
  `DISABLE_SQLALCHEMY_CEXT_RUNTIME`. The example's header reads all four, so a rename breaks the
  example rather than only the prose — but only when somebody runs it.
- **The pool and pragma defaults**, which are pysqlite's and sqlite3's rather than this recipe's:
  `QueuePool`/5/10/30 s and `check_same_thread=False` for a file URL,
  `SingletonThreadPool`/`check_same_thread=True` for `:memory:`, and `journal_mode=delete`,
  `synchronous=2`, `busy_timeout=5000`, `foreign_keys=0`. All of *Threading* hangs off them.
- **The measurements**: the extension, `.py` and wheel sizes per slice, the `compileall` figures, the
  module counts, the dialect and `testing` directory sizes, and the with/without timing spread.
  Re-measure rather than scaling — the timings especially, since they are the recipe's whole
  justification and are workload-shaped: benchmark a table with a `Numeric` *and* a `DateTime`
  column, because a two-integer-column table understates the gain by a factor of three.

### Coverage gaps

**No on-device run backs the timings, the pool behaviour or the pragma defaults.** Everything above was read off the wheels or
measured on a desktop install of the same version, and there is no CI run for this recipe to point
at — its last commit is a repo-wide normalisation, and the wheels on the index were built on
2026-06-11. The two tests in `tests/` cover an in-memory CRUD round trip and a statement compile,
both of which pass with the extensions disabled; nothing exercises a file database, the pragma
listener, the pool under threads, `Numeric` round-tripping, or the per-platform SQLite. An Android
and an iOS run of the [`expense-ledger`](examples/expense-ledger) example is the missing evidence,
and its header is built to be the thing you read off the screen.
