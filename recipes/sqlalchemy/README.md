# sqlalchemy

[`SQLAlchemy`](https://docs.sqlalchemy.org/en/20/) is the Python SQL toolkit and ORM:
[mapped classes](https://docs.sqlalchemy.org/en/20/orm/quickstart.html) with relationships
and typed columns, a query builder that composes instead of concatenating, and a connection
pool underneath. On a phone the case for it is that the local database is the part of an app
that outlives the screen it was written for — the stdlib `sqlite3` module hands you SQL
strings and tuples, while SQLAlchemy hands you a schema you can evolve and objects you can
put straight into controls, over the very same engine.

**This wheel is a speed upgrade, not what makes SQLAlchemy work on mobile.** Upstream
publishes a pure-Python universal wheel (`sqlalchemy-<version>-py3-none-any.whl`), and that
is what pip selects for an Android or iOS target unless this index happens to be ahead of
PyPI — which is not the usual case, so read [Install](#install) before assuming a bare
`sqlalchemy` gets you the extensions. The mobile
wheels here are that same wheel — every one of its 269 entries byte-identical except
`RECORD` and `WHEEL`, `METADATA` included — plus the five compiled Cython extensions that
SQLAlchemy's hot paths prefer. So
[upstream's documentation](https://docs.sqlalchemy.org/en/20/) applies verbatim, nothing
about your code changes, and what you get is faster result loading. See
[Things to know](#things-to-know) for what "faster" measured out at.

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
`pip install --upgrade --only-binary :all: --extra-index-url https://pypi.flet.dev`
(serious_python's `package_command.dart`), so pip sees PyPI *and* this index and takes the highest
version it can use — and a `py3-none-any` wheel is usable on every mobile target, so upstream wins
on version alone from the moment it releases past the version here. Measured with this index at
2.0.50 and PyPI at 2.0.52: a bare `sqlalchemy` resolved to `sqlalchemy-2.0.52-py3-none-any.whl` on
every slice and Python minor tried — Android arm64-v8a and armeabi-v7a, iOS device and the x86_64
simulator, 3.12 and 3.14. Nothing breaks, which is what byte-for-byte parity buys — but you get
none of the speed this recipe exists for, and the only thing that will tell you is the
`has_compiled_ext()` probe in [Things to know](#things-to-know). Pin `sqlalchemy` to the version
in [`meta.yaml`](meta.yaml) to get the extensions on every slice; the
[`expense-ledger`](examples/expense-ledger) example does.

**Nothing to install for SQLite.** The default dialect is
[pysqlite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#module-sqlalchemy.dialects.sqlite.pysqlite),
whose `import_dbapi` is `from sqlite3 import dbapi2`, so
[`create_engine("sqlite:///…")`](https://docs.sqlalchemy.org/en/20/core/engines.html#sqlalchemy.create_engine)
needs nothing beyond this wheel and the standard library. Any other database needs a driver;
see the table in [Things to know](#things-to-know) for which ones exist for mobile at all.

**The SQLite engine underneath is not the same version on the two platforms**, because it does
not come from this wheel at all. Measured on 2026-08-17 with Python 3.14: **3.50.4 on Android**,
compiled into Flet's Python build, and **3.43.2 on the iPhone simulator**, where `sqlite3` links
the copy iOS ships. So the floor for any feature you depend on — a SQL function, a pragma, `RETURNING`
— is whichever of the two is older, and it moves when Apple or Flet updates rather than when you
bump a pin. The [`expense-ledger`](examples/expense-ledger) example prints the version in its
header line so you can read it off the device you actually target.

`typing-extensions` comes along unconditionally. It is pure Python and resolves from PyPI
proper — it is not on pypi.flet.dev and does not need to be.

`greenlet` may or may not come along, and it is not your project that decides: SQLAlchemy
declares it as a **base** requirement gated on `platform_machine`, and pip evaluates that
marker against the machine that ran `flet build`. If you want it, ask for it —
`sqlalchemy[asyncio]`, or `sqlalchemy[aiosqlite]` which adds an async SQLite driver too. Both
resolve on every mobile slice. The trap this creates is described in
[Things to know](#things-to-know); it is the one entry on this page that turns a working
project into a broken one without anybody changing a line.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Nothing in the package builds a path from `__file__`, reads a packaged data
file, or calls `inspect.getsource` — grepping the unpacked wheel for `__file__`,
`importlib.resources`, `pkgutil.get_data` and `pkg_resources` hits only
`sqlalchemy/testing/plugin/pytestplugin.py`, which no app imports, and for
`getsource`/`linecache` hits nothing at all. The only non-`.py`, non-`.so` payload files are
`py.typed` and `dialects/type_migration_guidelines.txt`, and no code in the wheel opens
either. Nor does anything need a real file path: with the wheel's 269 non-`.so` entries put
into a zip on `sys.path` and nothing unpacked, the package still imports and runs a mapped
`select` with a `GROUP BY`, a `relationship` load and `Decimal`/`datetime` conversion. The
five extensions all carry a CPython ABI tag — bare on the 3.12 wheels
(`collections.cpython-312.so`), with the platform triple on the 3.13 and 3.14 ones
(`collections.cpython-314-aarch64-linux-android.so`) — so Android's zipped site-packages
handles them as-is.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS
device and both simulator slices, on Python 3.12, 3.13 and 3.14 — no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. Every one of the wheels on the index carries 274 entries and all five
extensions; nothing is missing anywhere.

## Storage

The database is an ordinary file, so it belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. Never
keep one in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

Spell the URL with
[`URL.create`](https://docs.sqlalchemy.org/en/20/core/engines.html#sqlalchemy.engine.URL.create)
and let it count the slashes:

```python
engine = create_engine(
    URL.create("sqlite", database=os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "app.db")),
    pool_size=1,
    max_overflow=0,
)
```

**An absolute path needs four slashes, and "fixing" that writes somewhere else instead of
failing.** `sqlite:///` is the dialect plus an empty host; the path follows, so an absolute
one produces `sqlite:////data/user/0/com.x.y/files/app.db`. `f"sqlite:///{abs_path}"` gets
this right and so does `URL.create`. Strip the leading slash to make it look tidier and
pysqlite's `create_connect_args` — which runs `os.path.abspath` on any database that is not
`:memory:` — joins it onto the process working directory instead: measured, `"sqlite:///" +
p.lstrip("/")` for `p = "/data/user/0/com.x.y/files/app.db"` handed sqlite3 a path under the
*current directory*, with no error anywhere.

Three files make up one database once WAL is on (see [Threading](#threading)): `app.db`,
`app.db-wal` and `app.db-shm`. The `-wal` file holds committed data that has not been
checkpointed into the main file yet, so the `.db` alone can stay tiny while the ledger is
large — measured, 4 KB of `.db` beside 1.01 MB of `-wal` after writing 12,000 rows. Copy,
export or back up all three together, or checkpoint first: measured,
`PRAGMA wal_checkpoint(TRUNCATE)` on a database with 1.89 MB sitting in its WAL returned
`(0, 0, 0)`, left the `-wal` at zero bytes and the main file at 1.87 MB.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`expense-ledger`](examples/expense-ledger) — a mapped, related, restart-surviving expense
  ledger with a grouped aggregate over it and an ORM-versus-Core timing.

## Threading

**Use a file database and the defaults are already thread-safe.** For a file URL the pysqlite
dialect returns a
[`QueuePool`](https://docs.sqlalchemy.org/en/20/core/pooling.html#sqlalchemy.pool.QueuePool)
and sets `check_same_thread=False`, which is safe rather than reckless: the pool checks a
sqlite3 connection out to one thread at a time. Measured so that a swapped connection could
not hide behind a matching answer: eight threads, each selecting a *different* key and
expecting a different value, each also inserting rows tagged with its own name and reading
back only its own — 8 × 150 rounds on the default pool and 8 × 60 on `pool_size=1`,
zero wrong values, zero exceptions, and every thread's row count exactly what it wrote.

**`create_engine("sqlite:///:memory:")` plus `page.run_thread` gives the worker a different,
empty database, and you will not be told.** A memory URL gets a
`SingletonThreadPool` with `check_same_thread=True`, and a singleton-per-thread pool means a
second thread opens a second, blank in-memory database. Measured: the main thread created and
filled table `t`, the worker then raised `OperationalError: (sqlite3.OperationalError) no
such table: t` — and
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) never
retrieves the worker's future, so that exception surfaces nowhere. If an in-memory database
really is what you want, upstream's
[StaticPool recipe](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#using-staticpool-for-single-connection-memory-databases)
is the fix, and it works: `create_engine("sqlite:///:memory:", poolclass=StaticPool,
connect_args={"check_same_thread": False})` let the same worker read the three rows.

**Shrink the pool.** The defaults are `pool_size=5, max_overflow=10, pool_timeout=30` with no
recycle — up to fifteen sqlite3 connections and file handles for a single-process app with
one user. `pool_size=1, max_overflow=0` is the honest figure for a phone; just know that a
second worker then waits on the pool for its 30 s timeout, so keep the non-blocking guard
described below.

**Two overlapping writers block for exactly 5 s and then raise.** SQLAlchemy passes sqlite3's
`timeout` only when it appears in the URL query, so you inherit sqlite3's own default of
5.0 s, and it does not turn WAL on: measured on a fresh file engine, `pragma journal_mode` is
`delete`, `pragma synchronous` is `2` (FULL), `pragma busy_timeout` is `5000`, and
`pragma foreign_keys` is `0`. A second write transaction opened while the first was held
raised after 5.2 s with `OperationalError: (sqlite3.OperationalError) database is locked`.

Those are per-connection settings, so they cannot go in `create_engine` and a one-off `PRAGMA`
does not reach the next connection the pool opens. A
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

Measured to stick: `journal_mode` reads back `wal`, `foreign_keys` `1`, `busy_timeout`
`5000`, and the `-wal`/`-shm` files appear beside the database.

A query blocks the thread that issued it, so on the UI thread it freezes the UI. Push it to
`page.run_thread`, wrap the worker body in `try/except` — the framework discards what it
raises — and end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads. `run_thread` submits to a thread *pool*, so disabling a
control does not stop a tap already in flight; a non-blocking `threading.Lock` does.

Every measurement in this section is from the desktop build of the same version. The SQLite
underneath differs per platform (see the platform notes), so re-check the pragma defaults on
a device before designing around them.

## Android notes

The stdlib `sqlite3` module — the DBAPI SQLAlchemy actually drives — links the SQLite that
Flet's Python build bundles, so it moves whenever that build is bumped rather than with the
OS. That is [`apsw`](../apsw)'s finding rather than this recipe's, and the distinction is the
whole reason apsw exists; it matters here if you rely on a pragma or a SQL feature whose
availability is not guaranteed. Read the version off the device rather than off this page —
the [`expense-ledger`](examples/expense-ledger) example prints it.

The five extensions are plain CPython extension modules with nothing exotic in them:
`DT_NEEDED` is `libm.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` on every one — no
`libc++_shared`, and no `flet-lib*` wheel in the wheel's own `Requires-Dist`. All `PT_LOAD`
segments carry 16 KB alignment, which Android 15 requires. arm64-v8a is `ELF64`/`AArch64` and
armeabi-v7a is `ELF32`/`ARM`, with the 32-bit slice's extensions the smallest of the set
(0.32 MB against 0.49 MB).

If you ask for async — `sqlalchemy[asyncio]` or `sqlalchemy[aiosqlite]` — the resolution gains
`greenlet` **and** `flet-libcpp-shared`, which [greenlet's recipe](../greenlet) requires on
Android only. That is a 407 KB wheel holding one 1.29 MB `opt/lib/libc++_shared.so`, and it
needs no configuration of its own.

## iOS notes

The stdlib `sqlite3` module links whatever `/usr/lib/libsqlite3.dylib` the OS release ships,
so the engine under identical SQLAlchemy code varies by device and moves under you on OS
updates — again [`apsw`](../apsw)'s finding, not measured here. Print it, do not assume it.

The extensions are `MH_DYLIB` — which is the filetype Flet 0.86's iOS packaging needs, since
it turns every site-packages `.so` into a framework binary that gets *linked* — two-level
namespace, `NOUNDEFS`, linking `@rpath/Python.framework/Python` and
`/usr/lib/libSystem.B.dylib` and nothing else; `LC_BUILD_VERSION` is platform 2, minos 13.0
on the device slice, platform 7, minos 14.0 on the arm64 simulator slice and platform 7,
minos 13.0 on the x86_64 simulator slice.
They are roughly 1.8× the size of the Android ones for the same five
modules — 0.87 MB against 0.49 MB, 308 KB against 200 KB for `collections` alone — which is
the whole of the 9.04 MB versus 8.66 MB difference in unpacked payload.

**iOS has no `pwd` module and leaves `LOGNAME`/`USER` unset.** Nothing in SQLAlchemy or the
SQLite dialects touches that, but `sqlalchemy[aiomysql]` does: aiomysql's module-level
`DEFAULT_USER = getpass.getuser()` is guarded only by `except KeyError`, which is not what
`getuser()` raises without `pwd`, so the import dies on iOS alone. **Which exception you see
depends on the Python**, because `getuser()` changed in 3.13: on 3.12 the bare
`import pwd` propagates as `ModuleNotFoundError: No module named 'pwd'`, while on 3.13 and
3.14 `getuser()` catches the `ImportError` itself and re-raises
`OSError: No username set in the environment`. Measured all three, with `pwd` blocked and
the four username variables cleared. The fix is the same either way, since `getuser()` reads
the environment first — set the variable before the import,
`os.environ.setdefault("LOGNAME", os.environ.get("USER") or "fletuser")`, harmless on
Android.

## Things to know

- **What the five extensions replace is the per-row path of every query.** Grepping the
  wheel for `HAS_CYEXTENSION` finds it in eight modules. Six are import switches shaped
  `if TYPE_CHECKING or not HAS_CYEXTENSION: from ._py_… else: from sqlalchemy.cyextension…`:
  `engine/row.py` (`BaseRow`, which `Row` derives from), `engine/result.py` (`tuplegetter`),
  `engine/processors.py` (the date/time/`Decimal`/`float`/`str` result processors),
  `engine/util.py` (parameter distillation on every `execute`), `sql/visitors.py` (the
  SQL-compilation anon maps) and `util/_collections.py` (`immutabledict`, `OrderedSet`,
  `IdentitySet` and friends, which hold metadata and ORM internals). The other two import
  nothing from `cyextension`: `util/_has_cy.py` sets the flag, and `util/langhelpers.py`
  reads it for the `has_compiled_ext()` probe below. Nothing on those paths changes an
  answer: a dump of 61 canonical results — `Decimal` exponents from the result processor,
  `OrderedSet` iteration order, `immutabledict` merges, `IdentitySet` membership, `Row`
  `repr`/`_asdict`/slicing, the processors on malformed and non-string input, compiled SQL
  and a statement cache key — came out byte-identical with the extensions on and off.
- **"Faster" is modest, and worth measuring on your own device rather than believing this
  bullet.** Desktop CPython 3.14 on an arm64 Mac, a 20,000-row table, best of nine runs,
  toggled with `DISABLE_SQLALCHEMY_CEXT_RUNTIME=1`: loading every row as ORM objects took
  45 ms with the extensions against 50–65 ms without, and reading the same rows through Core
  11.4 ms against 12.3–13.4 ms. Compiling 2,000 statements (119 ms against 124 ms) and a
  20,000-row bulk insert (23 ms against 20 ms) were inside run-to-run noise in both
  directions. **How much you get scales with how many columns per row need a processor**, so
  that pair of figures is a floor rather than a range: on the same table with a `DateTime`
  column added — so every row runs `str_to_datetime` as well as the `Decimal` conversion —
  the same measurement gave 61–69 ms with against 75–103 ms without for the ORM load and
  17.0–17.4 ms against 24.6–25.2 ms for Core, about 30% on both, while 2,000 compiles stayed
  noise (128–139 ms against 129–131 ms). So: high single digits to roughly a third on result
  loading depending on the column types, nothing measurable on compilation or inserts, and no
  device figure at all.
- **Ask the library whether the accelerators loaded; never infer it from a module path.**
  `from sqlalchemy.util import has_compiled_ext; has_compiled_ext()` is the probe. When it is
  `False`, `sqlalchemy.util._has_cy._CYEXTENSION_MSG` carries the reason — either the actual
  `ImportError` text or `DISABLE_SQLALCHEMY_CEXT_RUNTIME is set`. Two traps here. First,
  `sqlalchemy.util.HAS_CYEXTENSION` is *not* re-exported and raises `AttributeError`; the name
  lives at `sqlalchemy.util._has_cy.HAS_CYEXTENSION`. Second, `_has_cy` imports all five
  extensions in one `try`/`except ImportError`, so one `.so` failing to load silently demotes
  the whole library to pure Python — and probing
  `sqlalchemy.cyextension.util.__file__` will not tell you, because Flet relocates every
  native extension: on Android that attribute is absent altogether and on iOS it reports a
  `.fwork` path (established in [`pydantic-core`](../pydantic-core)).
- **Async engines fail at the first `await`, not at import, and whether they fail is decided
  by the build machine.** `sqlalchemy/util/concurrency.py` wraps `import greenlet` in a
  `try`/`except` and installs stubs on failure. Measured with `aiosqlite` present and
  `greenlet` absent: `from sqlalchemy.ext.asyncio import create_async_engine` imports fine,
  `create_async_engine(...)` constructs fine (`AsyncAdaptedQueuePool`), and the first
  `async with engine.begin()` raises `ValueError: the greenlet library is required to use this
  function. No module named 'greenlet'`. Install greenlet and the identical script prints
  `42`. The reason this is a build-machine question is that SQLAlchemy's base `greenlet`
  requirement is gated on `platform_machine` being one of `aarch64`, `ppc64le`, `x86_64`,
  `amd64`, `AMD64`, `win32`, `WIN32` — and serious_python's shim patches `platform.system`,
  `sysconfig.get_platform`, `platform.mac_ver`, `platform.ios_ver`, `platform.android_ver` and
  `platform.version`, but **not** `platform.machine`, so pip reads the host's. Measured: with
  `platform.machine() == "arm64"` (Apple Silicon), resolving a bare `sqlalchemy` pin for
  android_24_arm64_v8a cp314 installs sqlalchemy and typing-extensions only; adding one line
  faking `x86_64` to the same shim additionally installs greenlet 3.5.1 and
  flet-libcpp-shared. A project that works when built on an Intel Mac, Linux or Windows runner
  and breaks on Apple Silicon is this marker. Declare `sqlalchemy[asyncio]` and the question
  goes away — verified to resolve on both Android arm64 and iOS arm64 device.
- **Which drivers exist for mobile at all.** From `pip install --dry-run --only-binary :all:`
  against this index plus PyPI, for android_24_arm64_v8a cp314:

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

  Eleven of the twenty-three extras do not resolve for mobile at all. Nine fail with
  `Could not find a version that satisfies the requirement`, every one because the driver has
  no wheel for the platform: `mysql` (mysqlclient), `mssql` and `mssql_pyodbc` (pyodbc),
  `oracle` (cx_oracle), `postgresql_asyncpg`, `postgresql_psycopg2binary`,
  `postgresql_psycopg2cffi`, `asyncmy`, `sqlcipher` (sqlcipher3-binary). The other two fail as
  a `ResolutionImpossible` instead, because pip walks the whole version history looking for a
  release whose extra can be satisfied and runs out: `aioodbc` (`Cannot install sqlalchemy
  because these package versions have conflicting dependencies`) and
  `postgresql_psycopgbinary` (the same message listing all 52 `psycopg[binary]` releases).
  The remaining twelve resolve — the seven extras in the table above plus `asyncio`,
  `postgresql_psycopg`, `mariadb_connector`, `aiomysql` and `mypy`.
- **"pip resolved it" is not evidence a driver can connect.** `sqlalchemy[postgresql_psycopg]`
  and `sqlalchemy[mariadb_connector]` both resolve cleanly, from PyPI, as pure-Python
  wheels — and psycopg v3's pure-Python path is `psycopg/pq/_pq_ctypes.py`, which does
  `ctypes.cdll.LoadLibrary` on a libpq it has to *find on the device*, raising
  `ImportError: libpq library not found` (re-raised as `ImportError: no pq wrapper available`)
  when it cannot. There is no `psycopg` or `mariadb` on pypi.flet.dev to supply that half. For
  Postgres use the extra that pulls a driver with real mobile wheels, `sqlalchemy[postgresql]`.
  Neither failure was reproduced on a device here; the expected symptom is a ctypes error at
  import, not a resolution error.
- **There is no `sqlite+apsw` dialect** — `create_engine("sqlite+apsw:///x.db")` raises
  `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:sqlite.apsw`, and the wheel's
  `dialects/sqlite/` holds only `base`, `dml`, `json`, `provision`, `pysqlcipher`, `pysqlite`
  and `aiosqlite`. So SQLAlchemy and [`apsw`](../apsw) are alternatives, not a toolkit and its
  driver: pick SQLAlchemy over the stdlib `sqlite3` module for the ORM and the schema, or apsw
  for one identical SQLite engine on both platforms and its own API. `sqlite+pysqlcipher` does
  ship and is dead on both platforms — it raises
  `ModuleNotFoundError: No module named 'pysqlcipher3'`, and `sqlcipher3-binary` is a 404 on
  this index.
- **`create_all` creates missing tables and nothing else, so version 2 of your app cannot add a
  column with it.**
  [`MetaData.create_all`](https://docs.sqlalchemy.org/en/20/core/metadata.html#sqlalchemy.schema.MetaData.create_all)
  is `CREATE TABLE` per missing table; it never issues an `ALTER`. Measured: a table created with
  two columns, then `create_all` run again from a `MetaData` that declares a third, still has two
  columns — no error and no warning — and the first query touching the new one raises
  `OperationalError: (sqlite3.OperationalError) no such column: t.b`. It only bites on *upgrade*,
  which is what makes it nasty: a fresh install builds the new schema correctly, so this passes
  every test on your desk and breaks for everyone who already had the app.
  [Alembic](https://alembic.sqlalchemy.org/) is the answer, and it resolves for mobile as pure
  Python (measured for Android arm64 / 3.14: `alembic` 1.19.1, `mako`, and a compiled `markupsafe`
  from this index) — but it requires `SQLAlchemy>=1.4` unpinned, so adding it re-triggers exactly
  the resolution described in [Install](#install). Whether its migration scripts run *on a device*
  has not been tested here: they are ordinary `.py` files that Alembic loads by path, and Flet's
  default `compile.packages` replaces them with `.pyc`.
- **`func.avg` comes back as a `float` where `func.sum` comes back as a `Decimal`.** `sum`,
  `max` and `min` inherit the column's type, so over a
  [`Numeric`](https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Numeric)
  column they get the `Decimal` result processor; `func.avg(col).type` is `NullType()`, so no
  processor runs and the driver's raw float arrives. Mixing the two in a money total is how
  cents go missing. `func.avg(col, type_=Numeric(10, 2))` names the type explicitly.
- **`Numeric` survives the round trip exactly, but SQLite stores it as `REAL`.** Measured on a
  `Numeric(12, 2)` column: `select typeof(v), v` answers `('real', 0.1)` while SQLAlchemy reads
  back `Decimal('0.10')`, and `func.sum` returns a `Decimal` equal to the Python sum to the
  cent. `engine.dialect.supports_native_decimal` is `False`, so the conversion is
  SQLAlchemy's, not SQLite's — anything reading the file *outside* SQLAlchemy sees floats, and
  no warning is emitted either way. Identical with the C extensions disabled.
- **Flet's default `compile.packages = true` makes SQLAlchemy about 1.8 MB *bigger* in the
  app, not smaller.** serious_python runs `compileall -b` at optimisation level 0, and
  SQLAlchemy's docstrings are enormous, so the bytecode is larger than the source: measured
  after Flet's own junk-file cleanup, the `sqlalchemy/` tree zips to 2.11 MB as shipped `.py`
  and 3.91 MB as `.pyc` with the sources deleted (256 `.pyc` totalling 10.08 MB against
  8.10 MB of `.py`; unpacked, 8.60 MB becomes 10.57 MB). It is a real trade-off rather than a
  bug, though — `packages = false` under
  [`[tool.flet.compile]`](https://flet.dev/docs/publish/#compilation-and-cleanup) saves
  the 1.8 MB and the device then recompiles from source on every launch with no writable
  cache, and a warm `import sqlalchemy` alone already pulls 79 modules on a fast desktop.
  Measure both on the target device; do not switch it off reflexively for size.
- **Flet's cleanup strips the Cython sources for you, but not the dialects a phone cannot
  reach.** `cleanup.packages` defaults to on and removes `**.pyx`, `**.pxd`, `**.typed`,
  `**.pyi` and `__pycache__`, which covers all six Cython source files and `py.typed` (there
  are no `.pyi` files in the wheel at all, so there is no stripped-stub hazard here). What
  stays is 1.24 MB of remote-database dialects you will not reach without one of the drivers
  above — `postgresql` 0.47 MB, `mysql` 0.29 MB, `oracle` 0.28 MB, `mssql` 0.19 MB — plus
  SQLAlchemy's own `testing` package at 0.67 MB across 38 files, which exists for its pytest
  suite.
- **Size: 2.1 MB to download, 8.5–9.0 MB unpacked, and only ~4–10% of it is native.** 274
  files per wheel: 256 `.py` at 8.10 MB, the five extensions at 0.32 MB (armeabi-v7a),
  0.49 MB (Android arm64), 0.79 MB (arm64 simulator) or 0.87 MB (iOS device), and six Cython
  sources at 0.02 MB that Flet deletes. A typical ORM app imports about half the modules:
  `import sqlalchemy` pulls 79 of the 256, and adding a `create_engine`, a `Session` and one
  ORM `select` brings it to 130.
- **The dialect loader never scans entry points for a built-in dialect**, so zipped
  site-packages metadata is not on the path for any `sqlite` URL. Instrumenting
  `importlib.metadata.entry_points` recorded **0** calls across `create_engine("sqlite:///…")`
  plus a connect and a `CREATE TABLE`; the first call happens only for an unknown scheme, which
  then raises `NoSuchModuleError`.

## Build notes (maintainers)

`meta.yaml` is three settings — name, version, build number — there are no patches, and no
`build.sh`. That is the fact worth recording: SQLAlchemy is a plain setuptools sdist with five
independent Cython modules and no external library, so it cross-compiles to all six slices on
forge's stock support alone. The day this recipe needs a patch, suspect the toolchain or an
upstream restructuring before reaching for one.

**The recipe's whole reason for existing is currently unasserted, and a bump can silently
remove it.** `setup.py` builds each extension with `optional=not REQUIRE_EXTENSION`, where
`REQUIRE_EXTENSION = bool(os.environ.get("REQUIRE_SQLALCHEMY_CEXT"))`, and `meta.yaml` sets no
`build.script_env` — so a compile failure on any of the five is skipped, the build stays green,
and the wheel ships as pure Python that installs and imports perfectly. `tests/` does not
catch it either: both tests pass identically against an install with the extensions disabled
(`DISABLE_SQLALCHEMY_CEXT_RUNTIME=1 pytest -q` → 2 passed), despite the first one's docstring
claiming the wheel ships them. Two cheap fixes, both worth doing before the next bump:
`REQUIRE_SQLALCHEMY_CEXT: "1"` in `build.script_env` so a failed compile turns CI red, and a
test asserting `sqlalchemy.util.has_compiled_ext()` plus the five
`sqlalchemy.cyextension.*` imports.

Everything the sections above claim was read off the wheels or measured on a desktop install
of the same version. **No on-device run backs any of it**, and there is no CI run for this
recipe to point at — its last commit is a repo-wide normalisation, and the wheels on the index
were built on 2026-06-11. An Android and an iOS run of the
[`expense-ledger`](examples/expense-ledger) example is the missing evidence, and its header is
built to be the thing you read off the screen.

On a bump, in rough order of what a green build fails to tell you:

- **That five extensions were built, on all six slices.** `unzip -l` and count
  `cyextension/*.so`; the sdist should still hold exactly five `.pyx` plus
  `immutabledict.pxd`. A missing one is invisible: `_has_cy` imports all five in one
  `try`/`except`, so the library demotes itself to pure Python rather than failing.
- **The byte-for-byte parity with upstream's universal wheel**, which is what licences the
  claim that upstream's documentation applies verbatim. Every entry of
  `sqlalchemy-<version>-py3-none-any.whl` hashed identical to the mobile wheels' except
  `RECORD` and `WHEEL` — `METADATA` included, and the Android and iOS wheels differ from each
  other only in those two files and the extensions. A divergence means both the
  no-`extract_packages` claim and the upstream-docs claim need revisiting.
- **The linkage lists.** Android `DT_NEEDED` is `libm`/`libpython3.<minor>`/`libdl`/`libc` and
  nothing else; iOS is `@rpath/Python.framework/Python` plus `/usr/lib/libSystem.B.dylib` as
  `MH_DYLIB`. Anything new is a runtime dependency [Install](#install) does not mention. Also
  re-check the 16 KB `PT_LOAD` alignment, which comes from forge rather than from this recipe.
- **`Requires-Dist`, and specifically the `platform_machine` marker on `greenlet`.** The whole
  build-host paragraph in [Things to know](#things-to-know) is a claim about that one marker;
  if upstream ever drops it, or serious_python starts patching `platform.machine`, the
  paragraph becomes unnecessary rather than wrong. Re-run the driver-extra resolves too — that
  table is as much a statement about what else is on this index as about SQLAlchemy, so it
  rots when psycopg2, oracledb or pymssql move, and it gains a row the day `psycopg`,
  `asyncpg` or `sqlcipher3-binary` get recipes.
- **Whether a bare `sqlalchemy` still loses to upstream's universal wheel**, which is the first
  thing [Install](#install) tells an app author and the one claim on this page that flips the
  moment a bump lands: for however long this index is the newer of the two, a bare requirement
  resolves *here* and that paragraph over-warns. Re-run
  `pip download --only-binary :all: --platform android_24_arm64_v8a --python-version 3.14
  --implementation cp --abi cp314 --extra-index-url https://pypi.flet.dev sqlalchemy`
  and say which wheel came back, rather than reasoning from the version numbers.
- **The names the consumer sections lean on.** `sqlalchemy.util.has_compiled_ext`,
  `sqlalchemy.util._has_cy._CYEXTENSION_MSG`, `sqlalchemy.util.concurrency.have_greenlet` and
  the `DISABLE_SQLALCHEMY_CEXT_RUNTIME` variable are all read by the example's header, so a
  rename breaks the example rather than only the prose — but only when somebody runs it. The
  private ones are the ones to check.
- **The pool and pragma defaults**, which are pysqlite's and sqlite3's rather than this
  recipe's: `QueuePool`/5/10/30 s and `check_same_thread=False` for a file URL,
  `SingletonThreadPool`/`check_same_thread=True` for `:memory:`, and
  `journal_mode=delete`, `synchronous=2`, `busy_timeout=5000`, `foreign_keys=0`. All of
  [Threading](#threading) hangs off them, and the SQLite half moves with Flet's Python build
  on Android and with the OS on iOS, not with SQLAlchemy.
- **The measurements**: the extension/`.py`/wheel sizes per slice, the `compileall` figures,
  the module counts, the dialect and `testing` directory sizes, and the with/without timing
  spread. Re-measure rather than scaling — and the timings especially, since that bullet is
  the recipe's whole justification and it is workload-shaped: benchmark a table with a
  `Numeric` *and* a `DateTime` column, because a two-integer-column table understates the
  gain by a factor of three and a release that shrank it would make the recipe harder to
  justify.
