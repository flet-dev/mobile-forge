# duckdb

[`duckdb`](https://duckdb.org/docs/current/clients/python/overview.html) is an analytical SQL
database that runs inside your process — no server, no daemon, one file on disk. It is
columnar and vectorised, so the things a phone cannot afford to do in Python it does in C++
over whole columns at a time: grouped aggregates, window functions, percentiles, joins — and
where an operator can spill to disk, a query that outgrows the memory it is allowed may do
that rather than fail outright. On mobile that makes it the tool for data the app *owns* and
keeps — a million rows of readings, a log, a local cache of a server-side table — where the
alternative is a row store you hand-roll analytics on top of, or pulling everything into
Python objects.

It also reads and writes [Parquet](https://duckdb.org/docs/current/data/parquet/overview.html)
in every codec, which is worth knowing if you arrived here from [`pyarrow`](../pyarrow) —
whose mobile build has no Parquet at all.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "duckdb",
]
```

**Do not plan an iOS release on the wheels currently on the index.** `flet build ipa` and
`flet build ios-simulator` stop at `Error (Xcode): Unsupported mach-o filetype (only
MH_OBJECT and MH_DYLIB can be linked)`. Android builds and runs; [iOS](#ios) has the detail.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`readings-warehouse`](examples/readings-warehouse) — a million rows generated, queried
  three ways and exported to Parquet, all on device.

## Usage in a Flet app

Open the file, run SQL, put the tuples into controls:

```python
con = duckdb.connect(
    os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "readings.duckdb"),
    config={
        "memory_limit": "192MB",
        "threads": 2,
        "temp_directory": os.getenv("FLET_APP_STORAGE_TEMP", tempfile.gettempdir()),
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    },
)
rows = con.execute(
    "SELECT device_id, count(*), avg(celsius) FROM readings GROUP BY 1 ORDER BY 1"
).fetchall()

table = ft.Column([ft.Text(f"{d}   {n:,}   {mean:.2f} °C") for d, n, mean in rows])
```

That `config=` dict is the whole mobile story; the subsections below are what goes in it.

### Storage

The database is an ordinary file, so it belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From Flet
0.86.0 it is also the process working directory on device, so a bare relative filename lands
there; spelling it out costs one line and behaves the same on desktop.

Pass the settings to [`connect`](https://duckdb.org/docs/current/clients/python/overview.html)
rather than in a later `SET`: every default is computed while the database is being
constructed, so by the time a `SET` could run, `memory_limit` has already been derived from
the device's total RAM. They are ordinary
[settings](https://duckdb.org/docs/current/configuration/overview.html) and `SET` does change
every one of them afterwards, so use that for whatever the user adjusts at runtime.

`readings.duckdb.wal` appears beside the database and is not yours to manage — the write-ahead
log, present while the database is open and removed on a clean `close()`. A killed background
app leaves it behind and DuckDB recovers from it on the next open, so copy, export or back up
the two files together.

Never keep a database in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or in `FLET_APP_STORAGE_TEMP` (may vanish between
launches).

### Threading

**Give every thread its own `con.cursor()`. One connection object used from two threads at
once loses results and never says so.** The result slot belongs to the connection, so a second
`execute` on it discards whatever the first thread had not fetched yet. Six threads asking six
*different* questions on one shared connection raised **zero** exceptions and still came back
wrong: one run of 1,200 fetches produced 73 empty `fetchone()`s and 24 answers belonging to
another thread (`SELECT 42` returning `(200000,)`); a repeat of 6,000 fetches produced 5 empty
ones and none crossed. That spread is the point — the same code is wrong at a rate that
changes run to run, which is exactly the bug that survives testing. The identical queries
routed through a `con.cursor()` per thread were clean every time, so the engine underneath
parallelises fine; only the Python-side result slot is shared.

A query blocks the calling thread, so on the UI thread it freezes the UI. Push it to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does not
reach background threads. The binding releases the GIL around execution, so a long query does
not lock the rest of your Python out while it runs.

**A running query can be cancelled**, which is unusual enough to design a UI around:
`con.interrupt()` from any thread aborts it — the one call meant to cross threads — and the
thread that called `execute` raises `duckdb.InterruptException` (`INTERRUPT Error:
Interrupted!`). Catch it. `page.run_thread` never retrieves the worker's future, so an
uncaught exception there vanishes without a crash, a log line or a trace, and a cancelled
query is a *normal* outcome rather than a bug.

**A progress bar works, but only after one `SET`.** `con.query_progress()` answers `-1.0`
(progress unknown) until the progress bar is enabled, and duckdb's client enables it on its
own only for what it judges an interactive session — the test is whether `__main__` has a
`__file__`. Issue `SET enable_progress_bar = true` unconditionally rather than guessing what
Flet's launcher leaves in `__main__` on device; it is session-scoped, so `connect` rejects it
with `InvalidInputException: Could not set option "enable_progress_bar" as a global option`.

### Memory limits

**`memory_limit` defaults to 80% of the device's *total* RAM**, far more than the OS will let
one app hold: the figure comes from `sysconf(_SC_PHYS_PAGES) * sysconf(_SC_PAGESIZE)`, which
is installed RAM (on a 24 GiB machine it reads back as `19.1 GiB`). Nothing in DuckDB pulls it
back, so pass a real figure at connect. It rounds — `"192MB"` reads back as `183.1 MiB`. There
is no maximum-*database*-size setting to pair with it; `memory_limit` and
`max_temp_directory_size` are the whole story.

**Going over the limit is a catchable exception, not always a spill**, depending on the
operator and on how much slack the limit leaves. Measured on the desktop build at
`memory_limit='64MB'`: a sequential `CREATE TABLE` of four million rows spilled 12 MB and
finished, a 1.5-million-key grouped aggregate never spilled at all, and an `ORDER BY` over 1.2
million wide rows raised `duckdb.OutOfMemoryException` inside a second — `Out of Memory Error:
failed to pin block of size 256.0 KiB (61.1 MiB/61.0 MiB used)`, followed by upstream's own
suggestions to lower `threads` or `SET preserve_insertion_order=false`. The same sort spilled
256 MB and succeeded at `'192MB'`, so the ceiling is real but not a cliff you can predict from
a row count. Wrap the query worker in `try/except`, the more so because `page.run_thread`
discards what it raises — and remember the phone's second, uncatchable ceiling, the OS killing
the process. A `memory_limit` the device can honour is what keeps you on the side of the
failure you can report.

A spill lands in `readings.duckdb.tmp/`, which is what `temp_directory` defaults to for a
file-backed database (`.tmp`, relative to the working directory, for an in-memory one). It is
created only when a query exceeds `memory_limit`, and `close()` clears it — the files always,
the directory too when DuckDB created it — so a killed app leaves it full.
`max_temp_directory_size` defaults to *90% of available disk space*, which on a phone is no
limit at all: point `temp_directory` at
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
and add a real ceiling if the app can produce a query big enough to matter (it takes a value at
`connect` and rounds the way `memory_limit` does — `"32MB"` reads back as `30.5 MiB`). Volumes
move from run to run on the same statement: that 4-million-row build spilled 40–51 MB across
seven or eight files, so treat it as an order of magnitude rather than a figure. The example's
million rows under a 192 MB limit spill nothing and never create the directory.

### Extensions

**Four extensions are compiled in, and no fifth can be added on device:** `core_functions`,
`icu`, `json` and `parquet`. Ask the engine rather than this page —
`SELECT extension_name FROM duckdb_extensions() WHERE install_mode = 'STATICALLY_LINKED'`
lists exactly those four. What it leaves out is the rest of DuckDB's
[extension ecosystem](https://duckdb.org/docs/current/core_extensions/overview.html): `httpfs`
(so no `https://` or `s3://` paths, and no remote Parquet), `fts` full-text search, `excel`,
`spatial`, `sqlite_scanner`, `postgres_scanner`, `autocomplete`, `inet`, `tpch`/`tpcds`, and
every community extension.

**Turn autoinstall and autoload off at connect.** Both default to `ON`, so a function name
DuckDB does not recognise makes it try to *download* a native extension in the middle of your
query — over the network, at whatever moment the user tapped something. With them off the same
query fails at parse time naming what you actually asked for: `CatalogException: Catalog
Error: Table Function with name "read_xlsx" is not in the catalog, but it exists in the excel
extension.` Left on, the message you get instead blames the wrong thing entirely, because the
install directory is `~/.duckdb/extensions/…` and `~` comes from the `home_directory` setting
or `$HOME`: with neither set, the attempt dies before the download starts with `Can't find the
home directory at ''`.

Neither platform can serve a usable download anyway, for opposite reasons:

- **Android** reports its platform as `linux_arm64_android`, `linux_amd64_android` or
  `linux_i686_android` — 32-bit ARM is labelled `i686` by the engine's own macro logic — and
  extensions.duckdb.org has no build for any of the three: all three are HTTP 404, where
  `linux_arm64` and `osx_arm64` are 200.
- **iOS** thinks it is macOS. `PRAGMA platform` returns `osx_arm64`, assembled from `__APPLE__`
  and `__aarch64__` with no iOS branch in it (the x86_64 simulator answers `osx_amd64`). That
  makes autoinstall *worse* here than on Android: the server happily serves 5.5 MB of Mach-O
  dylib whose `LC_BUILD_VERSION` says macOS 11.0, which iOS will not load. Android's 404 at
  least fails immediately.

### App size

Expect roughly 16–20 MB of compressed wheel and 47–63 MB unpacked per architecture, and the
engine is essentially all of it. Cleanup buys nothing: the largest removable item in the whole
wheel is `duckdb/experimental`, about 400 KB.

On Android that lands once per ABI, and
[`flet build apk` targets all three](https://flet.dev/docs/publish/android/#supported-target-architectures)
by default. Restricting `target_arch` to the two 64-bit ABIs, or turning on
[`split_per_abi`](https://flet.dev/docs/publish/android/#split-apk-per-abi), is the only real
lever — and dropping armeabi-v7a costs nothing else, since 64-bit has been mandatory for Play
Store uploads since 2019:

```toml
[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

armeabi-v7a is the least-tested slice here in any case: build-verified only, its platform label
is wrong, and a memory limit derived from total RAM inside a 32-bit address space is the shape
of an out-of-memory kill. If you ship it, set `memory_limit` low.

### iOS

**`flet build ipa` and `flet build ios-simulator` fail at link time with the iOS wheels
currently on the index.** Observed, not predicted: building this recipe's own example on
2026-08-17 ended in `Error (Xcode): Unsupported mach-o filetype (only MH_OBJECT and MH_DYLIB
can be linked)` and `Linker command failed with exit code 1`. The published extension is a
Mach-O **bundle** on all three slices, and Flet 0.86's iOS packaging turns every site-packages
`.so` into a framework binary that SwiftPM *links*, where `ld` rejects a bundle. `dlopen`
accepts either filetype, which is why this surfaces in the build rather than at
`import duckdb`. No app-side setting works around it, and the recipe itself needs no change:
the fix is a rebuild and republish of the iOS slices, which is a maintainer task. Until that
happens, treat iOS as unsupported here.

Android is unaffected, because nothing there *links* the extension — `lib_duckdb.so` goes into
`jniLibs` and is `dlopen`ed. The example runs there: verified on an arm64 emulator on
2026-08-17, 1,000,000 rows stored and all three queries answered. Everything else on this page
is about the engine rather than the packaging, and survives the rebuild.

### Other considerations

The measurements on this page were made on the desktop build of the same version — the same
engine sources, no patches on either side — and none has been re-run on a device. The Python
layer of the mobile wheel is upstream's own, so `flet run` gives you the identical API and
upstream's documentation applies verbatim. What a device changes is the platform string DuckDB
reports, what its extension repository answers, and above all how much memory one process may
hold. Validate a real `memory_limit`, and any query you expect to spill, on a device rather
than under `flet run`.

## Things to know

- **`pytz` is undeclared and the engine needs it for time-zone-aware values.** Not in
  `Requires-Dist`, not even in the `all` extra — but `SELECT now()` or any `TIMESTAMPTZ`
  column raises `InvalidInputException: Invalid Input Error: Required module 'pytz' failed to
  import`. It bites exactly the app that logs timestamps. Either add `pytz` to your
  dependencies (pure Python, one universal wheel), or keep the values inside the engine: cast
  to plain `TIMESTAMP`, or format with
  [`strftime`](https://duckdb.org/docs/current/sql/functions/dateformat.html) so a string
  crosses the boundary. `strftime(now(), '%Y-%m-%d %H:%M')` works with no `pytz` installed.

- **Without `numpy`/`pandas`/`pyarrow` you lose the dataframe bridges and nothing else.** All
  three are declared only under duckdb's `all` extra, which nothing pulls in, so unless you ask
  for them they are not there: `.df()`, `.fetchnumpy()`, `.fetch_df_chunk()` and `.torch()`
  raise `ModuleNotFoundError: No module named 'numpy'`, and `.arrow()` *and* `.pl()` raise it
  for `'pyarrow'` — polars conversion routes through Arrow, so the error names the wrong
  library. `fetchall()`, `fetchone()`, `executemany()`, `duckdb.sql(...)` and `str(relation)`
  (a pre-rendered box-drawing table) all work, which is enough to build a UI out of tuples. If
  you do want Arrow, note the pairing that falls out of the two recipes: duckdb becomes
  pyarrow's Parquet reader, via `con.execute("SELECT … FROM read_parquet(…)").arrow()`.

- **Parquet works completely — read and write, in every codec.** `snappy` (the default),
  `zstd`, `gzip`, `brotli` and `lz4` all round-tripped, and the implementations are vendored in
  DuckDB's own tree, so nothing optional decides this.
  `COPY … TO 'x.parquet' (FORMAT PARQUET, COMPRESSION zstd)` and `read_parquet('x.parquet')`
  are the two calls. [`polars`](../polars) on this index reads and writes Parquet too;
  [`pyarrow`](../pyarrow) cannot.

- **Time zones and Unicode collation need no `tzdata` package.** The statically linked
  [`icu`](https://duckdb.org/docs/current/core_extensions/icu.html) extension carries its own
  ICU data blob, so `pg_timezone_names()` returns 638 rows, `COLLATE de` and `COLLATE NOACCENT`
  work, and the session zone follows the `TZ` environment variable. This is where duckdb
  differs from [`pandas`](../pandas) and [`polars`](../polars), which both want `tzdata` on
  Android.

- **You cannot hand DuckDB a Python list.** Replacement scans want a pandas DataFrame or an
  Arrow object, so `con.register("rows", my_list)` fails at query time with
  `InvalidInputException: Python Object "rows" of type "list" not suitable for replacement
  scans`. Use `executemany("INSERT INTO t VALUES (?, ?)", rows)`, a `VALUES` list, or write a
  CSV/Parquet file and let the engine read it — which is faster anyway.

- **Two modules in the package are unusable here, and neither is reached by `import duckdb`.**
  `duckdb/polars_io.py` imports `polars` at module top, and `adbc_driver_duckdb` needs
  `adbc_driver_manager`. Everything else upstream documents is present, including the
  `duckdb.experimental` Spark-compatible API.

## Build notes (maintainers)

### Recipe shape

The plain scikit-build-core/CMake path, and the whole recipe is `meta.yaml` plus two tests:
the sdist vendors all of DuckDB and ICU, so there is no native-library recipe underneath it,
and no forge change was needed to build it. Not one of DuckDB's own feature switches is
touched, which is what makes the consumer claims above stable — the four statically linked
extensions, the autoinstall/autoload defaults and the Parquet codec set are upstream defaults
inherited from `cmake/duckdb_loader.cmake` and the sdist's `pyproject.toml`, not decisions
made here.

The C++ runtime resolves differently per platform. On Android the extension links
`libc++_shared.so` and the `flet-libcpp-shared` dependency supplies it, adding 1.29 MB
unpacked. On iOS it links the OS's own `/usr/lib/libc++.1.dylib`, so that wheel declares no
runtime dependencies at all.

### Upgrade hazards

**Before iOS is claimed at all:** rebuild and republish the iOS slices from current `main`.
The wheels on the index date from 2026-06-20 and forge's MH_BUNDLE→MH_DYLIB conversion landed
on 2026-07-14 (`b7ce737`, part of the Flet 0.86 compatibility work), so the published
extension is still a bundle and no app can link it. A rerun is all it takes — the recipe needs
no edit — after which [iOS](#ios) and the Install warning both need rewriting, and an on-device
run under a current Flet is needed before either claims success. The only iOS evidence this
recipe has is the simulator run recorded in `8ef8c36`, from before the packaging changed.

Should a version ever need a fifth extension on mobile, `BUILD_EXTENSIONS` is the only route —
the download path is a 404 on Android and serves an unloadable macOS binary on iOS — and it is
a size decision on top of an extension already 47–63 MB unpacked. It also has *two* defaults in
the sdist (`pyproject.toml` and `cmake/duckdb_loader.cmake`, which currently disagree in
ordering only), so a bump can change the set without anyone touching this recipe.

### Re-verification checklist

Everything above this section is a claim about one build that a bump can falsify without the
build failing.

- **The statically linked extension set**, on which most of [Extensions](#extensions) hangs:
  `duckdb_extensions()` is the cheap check. The shipped binaries were also fingerprinted
  against the same-version PyPI desktop wheel — `HTTPFileSystem` and `S3FileSystem` in neither
  mobile wheel; `parquet_scan`, `read_json`, `make_timestamptz` present as implementations;
  `create_fts_index`, `read_xlsx`, `st_area`, `sqlite_scan`, `postgres_scan` only as names.
- **The autoinstall/autoload defaults**, `ENABLE_EXTENSION_AUTOINSTALL` and
  `ENABLE_EXTENSION_AUTOLOADING`, both `ON` upstream today. If they ever default off, the
  loudest recommendation on this page becomes unnecessary.
- **The platform strings**, from `duckdb/common/platform.hpp`: derived at runtime from
  preprocessor macros, so they never appear in `strings` output and only a device settles them.
  Recheck the 404-vs-200 asymmetry too — that one is a claim about someone else's server.
- **The progress-bar gate**, `SetDefaultConfigArguments` in `src/duckdb_py/pyconnection.cpp`.
  Enabled unconditionally upstream, the `SET` instruction becomes unnecessary rather than wrong.
- **The `pytz` gap:** read `Requires-Dist` from the built wheel rather than assuming.
- **The ICU data blob** behind the `tzdata`-free claim: `icudt` appears ~200 times in each
  wheel's strings today, and `pg_timezone_names()` returning rows is the runtime check.
- **The exception and error strings quoted above** are upstream's wording, and upstream rewords
  them. Which operators spill and which raise moves between releases too, so re-run the
  over-the-limit measurement rather than trusting the shapes in [Memory limits](#memory-limits).
- **The sizes:** re-measure from the wheels the bump produces. Last time it was 551 KB of
  Python and metadata against a 46.7–62.1 MB extension, with 49 non-extension,
  non-`.dist-info` files hashing identical to the same-version desktop wheel.
- **Android package layout:** no `extract_packages` entry is needed today, because the Python
  layer contains no `__file__` reference at all and the extension already carries a CPython ABI
  tag. Re-grep for `__file__`; a new data-file read changes that guidance.
- **iOS Mach-O filetype:** `otool -hv` reporting `DYLIB` on all three slices is the check, and
  the *only* one — `codesign -dv` cannot tell a converted extension from an unconverted one,
  since the arm64 simulator slice on the index already reports an ad-hoc, linker-signed
  signature while still being a `BUNDLE`.

### Coverage gaps

The recipe's own tests cover only `import duckdb` and an in-memory round trip, so a green CI
run confirms almost none of the above — not the extension set, not the platform string, not one
memory or spill figure, and nothing about Parquet. Worth adding, in rough order of value: the
`duckdb_extensions()` set, a Parquet `COPY` + `read_parquet` round trip through
`FLET_APP_STORAGE_DATA`, `PRAGMA platform`, and a `config={"memory_limit": …}` connect — after
which the promises above would turn CI red on their own instead of rotting quietly.
