# duckdb

[`duckdb`](https://duckdb.org/docs/current/clients/python/overview.html) is an analytical
SQL database that runs inside your process — no server, no daemon, one file on disk. It is
columnar and vectorised, so the things a phone cannot afford to do in Python it does in C++
over whole columns at a time: grouped aggregates, window functions, percentiles, joins — and
where an operator can spill to disk, a query that outgrows the memory it is allowed does that
instead of dying. On
mobile that makes it the tool for data the app *owns* and keeps — a million rows of readings,
a log, a local cache of a server-side table — where the alternative is a row store you
hand-roll analytics on top of, or pulling everything into Python objects.

It also reads and writes [Parquet](https://duckdb.org/docs/current/data/parquet/overview.html)
in every codec, which is worth knowing if you arrived here from
[`pyarrow`](../pyarrow) — whose mobile build has no Parquet at all.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "duckdb",
]
```

Nothing else to configure. On Android one extra wheel comes along and needs no entry of its
own: `flet-libcpp-shared`, the NDK C++ runtime the extension links (`libc++_shared.so` is in
its `DT_NEEDED`). On iOS the wheel declares no runtime dependencies at all — it links the
OS's own `/usr/lib/libc++.1.dylib`.

**`numpy`, `pandas` and `pyarrow` are not installed for you.** They are declared only under
duckdb's `all` extra, which nothing pulls in — and `pytz`, which the engine needs the moment a
value crosses into Python as a `TIMESTAMP WITH TIME ZONE`, is not declared anywhere at all.
The whole SQL surface works without any of them; the dataframe conversions and time-zone-aware
fetches do not. See [Things to know](#things-to-know).

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed: nothing in the Python layer builds a path from `__file__` or reads a
packaged data file, and the single extension already carries a CPython ABI tag
(`_duckdb.cpython-314-…so`), so Android's zipped site-packages handles it as-is.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS
device and both simulator slices, on Python 3.12, 3.13 and 3.14. **Read
[iOS notes](#ios-notes) before you plan an iOS release** — the iOS wheels currently on the
index are not linkable into an app.

## Storage

The database is an ordinary file, so it belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From Flet
0.86.0 it is also the process working directory on device, so a bare relative filename lands
there; spelling it out costs one line and behaves the same on desktop:

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
```

That `config=` dict is the whole mobile story, and it belongs at
[`connect`](https://duckdb.org/docs/current/clients/python/overview.html) rather than in a
later `SET`: every default is computed while the database is being constructed, so by the time
a `SET` could run, `memory_limit` has already been derived from the device's total RAM. All
five are ordinary [settings](https://duckdb.org/docs/current/configuration/overview.html) and
`SET` does change every one of them afterwards, so use it for anything the user adjusts at
runtime. Each is explained in [Things to know](#things-to-know).

Two more things appear beside the database, and neither is yours to manage:

- `readings.duckdb.wal` — the write-ahead log, present while the database is open and
  removed on a clean `close()`. A killed background app leaves it behind; DuckDB recovers
  from it on the next open. Copy, export or back up the two files together.
- `readings.duckdb.tmp/` — the spill directory, which is what `temp_directory` defaults to
  for a file-backed database (`.tmp`, relative to the working directory, for an in-memory
  one). It is created only when a query exceeds `memory_limit`, and `close()` clears it — the
  files always, and the directory too when DuckDB was the one that created it — so a killed
  app leaves it full. `max_temp_directory_size` defaults to *90% of available disk space*,
  which on a phone is no limit at all; point `temp_directory` at
  [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp),
  and add a real ceiling if the app can produce a query big enough to matter —
  `max_temp_directory_size` takes a value at `connect` and rounds the way `memory_limit` does
  (`"32MB"` reads back as `30.5 MiB`). Measured: an in-memory database with
  `memory_limit='64MB'` building a 4-million-row table of an integer, a timestamp and a double
  spilled 40–51 MB across seven or eight files — the volume moves from run to run on the same
  statement, so treat it as an order of magnitude rather than a figure. The example's own
  million rows under a 192 MB limit spill nothing and never create the directory.

Never keep a database in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or in `FLET_APP_STORAGE_TEMP` (may vanish
between launches).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`readings-warehouse`](examples/readings-warehouse) — a million rows generated, queried
  three ways and exported to Parquet, all on device.

## Threading

**Give every thread its own `con.cursor()`. One connection object used from two threads at
once loses results and never says so.** The result slot belongs to the connection, so a second
`execute` on it discards whatever the first thread had not fetched yet. Six threads asking six
*different* questions on one shared connection raised **zero** exceptions and still came back
wrong: one run of 1,200 fetches produced 73 empty `fetchone()`s and 24 answers that belonged
to another thread (`SELECT 42` returning `(200000,)`), and a repeat of 6,000 fetches produced
5 empty ones and none crossed. That spread is the point — the same code is wrong at a rate
that changes run to run, which is exactly the bug that survives testing. Routing the identical
queries through a `con.cursor()` per thread was clean every time, so the engine underneath
parallelises fine; it is only the Python-side result slot that is shared. This is the mirror
image of [`apsw`](../apsw), where an overlap raises `ThreadingViolationError`: there the bug
announces itself, here it is a missing or wrong number on screen.

`con.interrupt()` is the one call meant to cross threads. The binding also releases the GIL
around execution (`gil_scoped_release` appears 13 times in `pyconnection.cpp` alone), so a long
query in one thread does not lock the rest of your Python out — a loop in another thread
sampled it 146 times while it ran.

None of that makes a query asynchronous: it blocks the calling thread, so on the UI thread it
freezes the UI. Push it to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads.

**A running query can be cancelled**, which is unusual enough to design a UI around:
`con.interrupt()` from any thread aborts it, and the thread that called `execute` raises
`duckdb.InterruptException` (`INTERRUPT Error: Interrupted!`). Catch it — `page.run_thread`
never retrieves the worker's future, so an uncaught exception there vanishes without a crash,
a log line or a trace, and a cancelled query is a *normal* outcome rather than a bug.

**A progress bar works, but only after one `SET`.** `con.query_progress()` answers `-1.0`
(progress unknown) on every call until the progress bar is enabled, and duckdb's Python client
only enables it on its own when it decides the session is interactive — the test is whether
`__main__` has a `__file__`, which a script does and a REPL does not.
`SET enable_progress_bar = true` is the whole fix, and it is worth issuing unconditionally
rather than guessing what Flet's launcher leaves in `__main__` on device. It is session-scoped,
so it cannot go in the `config=` dict, which answers
`InvalidInputException: Could not set option "enable_progress_bar" as a global option`.
Measured on a 40-million-row grouped aggregate sampled every 50 ms: `-1.0` for all 21 samples
with the setting off, and 8.6 → 16.3 → 25.5 → 38.4 → 50.7 → 59.3 → 74.0 → 89.7 → 100.0 with
it on.

The measurements in this section come from the desktop build of the same version — the same
engine sources, with no patches on either side — and none of them has been re-run on a device.

## Android notes

**DuckDB reports its platform as `linux_arm64_android` on arm64-v8a, `linux_amd64_android` on
x86_64 and `linux_i686_android` on armeabi-v7a** — 32-bit ARM is labelled `i686` by the
engine's own macro logic — and extensions.duckdb.org has **no build for any of the three**:
all three are HTTP 404, where `linux_arm64` and `osx_arm64` are 200. So an extension the wheel
does not already contain cannot be installed on Android at all, and an autoinstall attempt is a
failed download. Turn
autoinstall and autoload off and you get a clean catalog error at parse time instead; see
[Things to know](#things-to-know).

`flet-libcpp-shared` rides along automatically and adds 1.29 MB unpacked — a single
`opt/lib/libc++_shared.so`, which needs no configuration of its own.

**The engine is the biggest thing in your APK, once per ABI.** `flet build apk`
[targets all three](https://flet.dev/docs/publish/android/#supported-target-architectures) by
default, and there is nothing to trim: 551 KB of the wheel is Python and metadata, and all the
rest is the one extension.

| slice | wheel | unpacked | the `.so` alone |
| --- | --- | --- | --- |
| arm64-v8a | 18.1 MB | 58.8 MB | 58.2 MB |
| x86_64 | 19.6 MB | 62.7 MB | 62.1 MB |
| armeabi-v7a | 18.1 MB | 47.2 MB | 46.7 MB |

Restricting `target_arch` to the two 64-bit ABIs, or turning on
[`split_per_abi`](https://flet.dev/docs/publish/android/#split-apk-per-abi), is the only real
lever — and dropping armeabi-v7a costs you nothing else, since 64-bit has been mandatory for
Play Store uploads since 2019:

```toml
[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

armeabi-v7a is the least-tested slice here in any case: it is build-verified only, its
platform label is wrong, and a memory limit derived from total RAM inside a 32-bit address
space is the shape of an out-of-memory kill. If you ship it, set `memory_limit` low.

## iOS notes

**`flet build ipa` and `flet build ios-simulator` fail at link time with the iOS wheels
currently on the index.** Observed, not predicted: building this recipe's own example on
2026-08-17 ended in `Error (Xcode): Unsupported mach-o filetype (only MH_OBJECT and MH_DYLIB
can be linked)` followed by `Linker command failed with exit code 1`. Their extension is a
Mach-O **bundle** on all three slices —
`otool -hv` reports filetype `BUNDLE` for the device, the arm64 simulator and the x86_64
simulator alike — and Flet 0.86's iOS packaging turns every site-packages `.so` into a
framework binary that SwiftPM *links*, where `ld` rejects a bundle with
`Unsupported mach-o filetype (only MH_OBJECT and MH_DYLIB can be linked)`. The wheels
predate that requirement — they were built on 2026-06-20 and a simulator run passed at the
time — and forge grew a bundle→dylib converter for this exact failure on 2026-07-14, since
when duckdb has not been rebuilt, so the conversion has never run on these files. `dlopen`
accepts either filetype, which is why the problem shows up in the build rather than at
`import duckdb`. The recipe itself needs no change — the iOS slices
need republishing, which is the first item in [Build notes](#build-notes-maintainers). Until
then, treat iOS as unsupported here.

The Android wheels were built the same day and are equally unconverted, but nothing on Android
links them — `lib_duckdb.so` goes into `jniLibs` and is `dlopen`ed. The example runs there:
verified on an arm64 emulator on 2026-08-17, 1,000,000 rows stored and all three queries
answered.

Everything below is about the engine rather than the packaging, and survives the rebuild.

**On iOS, DuckDB thinks it is macOS: `PRAGMA platform` returns `osx_arm64`** — the string is
assembled from `__APPLE__` and `__aarch64__`, with no iOS branch anywhere in it, so the x86_64
simulator answers `osx_amd64` for the same reason.
That makes an extension autoinstall *worse* on iOS than on Android rather than better:
extensions.duckdb.org happily serves `<version>/osx_arm64/httpfs.duckdb_extension.gz` — 5.5 MB
of Mach-O dylib whose `LC_BUILD_VERSION` says platform macOS, minimum 11.0, which iOS will not
load. Android's 404 at least fails immediately. Switch autoinstall and autoload off.

## Things to know

- **Turn extension autoinstall and autoload off at connect.** Both default to `ON`, so a
  function name DuckDB does not recognise makes it try to *download* a native extension in
  the middle of your query — over the network, at whatever moment the user tapped something.
  With `config={"autoinstall_known_extensions": False, "autoload_known_extensions": False}`
  the same query fails at parse time with a message that names what you actually asked for:
  `CatalogException: Catalog Error: Table Function with name "read_xlsx" is not in the
  catalog, but it exists in the excel extension.` It also sidesteps a second trap: the install
  directory is `~/.duckdb/extensions/<version>/<platform>`, and `~` comes from the
  `home_directory` setting when one is set and from `$HOME` otherwise, so with neither the
  attempt fails before the download even starts — `An error occurred while trying to
  automatically install the required extension 'excel': Can't find the home directory at ''`,
  which blames the wrong thing entirely. The message's own next line names the escape hatch,
  `SET home_directory='/path/to/dir'`, which on device means app storage. (Whether Flet sets
  `HOME` on device was not checked here.)
- **Four extensions are compiled in, and no fifth can be added on device:**
  `core_functions`, `icu`, `json` and `parquet`. Ask the engine, not this page —
  `SELECT extension_name FROM duckdb_extensions() WHERE install_mode = 'STATICALLY_LINKED'`
  is one line of SQL and lists exactly those four. What that leaves out is everything else in
  DuckDB's [extension ecosystem](https://duckdb.org/docs/current/core_extensions/overview.html):
  `httpfs` (so no `https://` or `s3://` paths, and no remote Parquet), `fts` full-text
  search, `excel`, `spatial`, `sqlite_scanner`, `postgres_scanner`, `autocomplete`, `inet`,
  `tpch`/`tpcds`, and every community extension. Verified in the shipped binaries, not just
  in the build flags: `HTTPFileSystem` and `S3FileSystem` appear nowhere in either wheel, and
  both mobile extensions carry the same symbol fingerprint as the same-version PyPI desktop
  wheel that list was read off — `parquet_scan`, `read_json` and `make_timestamptz` present as
  implementations, `create_fts_index`, `read_xlsx`, `st_area`, `sqlite_scan` and
  `postgres_scan` only as the names of extensions that are not there.
- **`memory_limit` defaults to 80% of the device's *total* RAM**, which is far more than the
  OS will let one app hold — `GetAvailableMemory()` is `sysconf(_SC_PHYS_PAGES) *
  sysconf(_SC_PAGESIZE)`, i.e. installed RAM, and the default is 80% of it (measured on a
  24 GiB machine: `19.1 GiB`, DuckDB's truncated rendering of 80% of 25,769,803,776 bytes).
  Nothing in DuckDB pulls it back, so pass a real figure at connect. DuckDB rounds it —
  `"192MB"` reads back as `183.1 MiB`. What you
  do *not* have to declare is a maximum database size: none of the 160 rows of
  `duckdb_settings()` is a `max_db_size`-style knob, and a file-backed database opened with no
  arguments at all works, so `memory_limit` and `max_temp_directory_size` are the whole story.
- **Going over `memory_limit` is a catchable exception, not always a spill.** Which of the two
  you get depends on the operator and on how much slack the limit leaves. All three of these
  were measured at `memory_limit='64MB'`: a sequential `CREATE TABLE` of four million rows
  spilled 12 MB and finished, a 1.5-million-key grouped aggregate finished without spilling at
  all, and an `ORDER BY` over 1.2 million wide rows raised `duckdb.OutOfMemoryException` inside
  a second — `Out of Memory Error: failed to pin block of size 256.0 KiB (61.1 MiB/61.0 MiB
  used)`, followed by upstream's own suggestions to lower `threads` or
  `SET preserve_insertion_order=false`. The same sort spilled 256 MB and succeeded at
  `'192MB'`, so the ceiling is real but not a cliff you can predict from the row count. Wrap a
  query worker in `try/except` — the more so because `page.run_thread` discards what it raises.
  On a phone you also have the second, uncatchable ceiling: the OS killing the process. Passing
  a `memory_limit` the device can actually honour is what keeps you on the side of the failure
  you can report.
- **Parquet works completely — read and write, in every codec.** `snappy` (the default),
  `zstd`, `gzip`, `brotli` and `lz4` all round-tripped, and all five codec names are present
  in both mobile binaries; the implementations are vendored in DuckDB's own tree, so nothing
  optional decides this. `COPY … TO 'x.parquet' (FORMAT PARQUET, COMPRESSION zstd)` and
  `read_parquet('x.parquet')` are the two calls. [`polars`](../polars) on this index reads and
  writes Parquet too; [`pyarrow`](../pyarrow) cannot.
- **Without `numpy`/`pandas`/`pyarrow` you lose the dataframe bridges and nothing else.**
  `.df()`, `.fetchnumpy()`, `.fetch_df_chunk()` and `.torch()` raise
  `ModuleNotFoundError: No module named 'numpy'`; `.arrow()` *and* `.pl()` raise it for
  `'pyarrow'` — polars conversion routes through Arrow, so the error names the wrong library.
  `fetchall()`, `fetchone()`, `executemany()`, `duckdb.sql(...)` and `str(relation)` (a
  pre-rendered box-drawing table) all work, which is enough to build a UI out of tuples. If
  you do want Arrow, note the pairing that falls out of the two recipes: duckdb becomes
  pyarrow's Parquet reader, via `con.execute("SELECT … FROM read_parquet(…)").arrow()`.
- **`pytz` is undeclared and the engine needs it for time-zone-aware values.** Not in
  `Requires-Dist`, not even in the `all` extra — but `SELECT now()` or any `TIMESTAMPTZ`
  column raises `InvalidInputException: Invalid Input Error: Required module 'pytz' failed to
  import`. It bites exactly the app that logs timestamps. Either add `pytz` to your
  dependencies (pure Python, one universal wheel), or keep the values inside the engine: cast
  to plain `TIMESTAMP`, or format with
  [`strftime`](https://duckdb.org/docs/current/sql/functions/dateformat.html) so a string
  crosses the boundary. `strftime(now(), '%Y-%m-%d %H:%M')` works with no `pytz` installed.
- **Time zones and Unicode collation need no `tzdata` package.** The statically linked
  [`icu`](https://duckdb.org/docs/current/core_extensions/icu.html) extension carries its own
  ICU data blob — `icudt` appears ~200 times in each wheel's strings — so
  `pg_timezone_names()` returns 638 rows, `COLLATE de` and `COLLATE NOACCENT` work, and the
  session zone follows the `TZ` environment variable. This is where duckdb differs from
  [`pandas`](../pandas) and [`polars`](../polars), which both want `tzdata` on Android.
- **You cannot hand DuckDB a Python list.** Replacement scans want a pandas DataFrame or an
  Arrow object, so `con.register("rows", my_list)` fails at query time with
  `InvalidInputException: Python Object "rows" of type "list" not suitable for replacement
  scans`. Use `executemany("INSERT INTO t VALUES (?, ?)", rows)`, a `VALUES` list, or write a
  CSV/Parquet file and let the engine read it — which is faster anyway.
- **The Python half of the wheel is upstream's, byte for byte.** Set the extension aside and
  the remaining 49 files outside `.dist-info` hash identical between the Android wheel, the iOS
  wheel and the PyPI macOS wheel of the same version — only `METADATA`, `RECORD` and `WHEEL`
  differ, and the recipe carries no
  patches — so upstream's documentation applies verbatim,
  including the `duckdb.experimental` Spark-compatible API. Two things in there are unusable
  and neither is reached by `import duckdb`: `duckdb/polars_io.py` imports `polars` at module
  top, and `adbc_driver_duckdb` needs `adbc_driver_manager`.
- **Size.** 15.6–19.6 MB to download, 47–63 MB unpacked, and the engine is essentially all
  of it (see [Android notes](#android-notes) for the per-ABI table; iOS device is 15.6 MB →
  47.2 MB, simulator arm64 16.4 MB → 49.5 MB). Cleanup buys nothing: the largest removable
  item in the whole wheel is `duckdb/experimental` at 397 KB.

## Build notes (maintainers)

`meta.yaml` comments its own non-obvious settings — the Unix Makefiles generator on iOS, the
Android C++ runtime requirement — and there are no patches, so what is left here is shape and
the bump checklist.

The shape is the plain scikit-build-core/CMake path, and the whole recipe is `meta.yaml` plus
two tests: the sdist vendors all of DuckDB and ICU, so there is no native-library recipe
underneath it, and no forge change was needed to build it. Nor is a single one of DuckDB's own
feature switches touched, and that is what makes the consumer claims above stable — the four
statically linked extensions, the autoinstall/autoload defaults and the Parquet codec set are
upstream defaults inherited from `cmake/duckdb_loader.cmake` and the sdist's `pyproject.toml`,
not decisions made here. If a future version ever needs a fifth extension on mobile,
`BUILD_EXTENSIONS` is the only route to it — the download path is a 404 on Android and serves
an unloadable macOS binary on iOS — and it is a size decision taken on top of an extension
that is already 47–63 MB unpacked.

**The one thing that must happen before iOS is claimed at all:** rebuild and republish the
iOS slices from current `main`. The wheels on the index date from 2026-06-20 and forge's
MH_BUNDLE→MH_DYLIB conversion landed on 2026-07-14 (`b7ce737`, part of the Flet 0.86
compatibility work), so the published extension is still a bundle. A rerun is all it takes —
the recipe needs no edit. `otool -hv` reporting filetype `DYLIB` on all three slices is the
check, and it is the *only* one: `codesign -dv` cannot tell a converted extension from an
unconverted one, because the arm64 simulator slice on the index today already reports an
ad-hoc, linker-signed signature while still being a `BUNDLE` (the device and x86_64 simulator
slices are unsigned). Then get an on-device run under a current Flet before touching
[iOS notes](#ios-notes): the only iOS evidence this recipe has is the simulator run recorded in
`8ef8c36`, from before the packaging changed.

Then, on a version bump — and everything above this section is a claim about one build that a
bump can falsify without the build failing:

- **The statically linked extension set.** `duckdb_extensions()` is the check, and it is
  cheap. `BUILD_EXTENSIONS` has *two* defaults in the sdist (`pyproject.toml` and
  `cmake/duckdb_loader.cmake`, which currently disagree in ordering only), and either could
  gain or lose a name. The whole of [Things to know](#things-to-know) hangs off the answer.
- **The autoinstall/autoload defaults**, `ENABLE_EXTENSION_AUTOINSTALL` and
  `ENABLE_EXTENSION_AUTOLOADING`, both currently `ON` upstream. If they ever default off, the
  loudest recommendation on this page becomes unnecessary.
- **The platform strings**, from `duckdb/common/platform.hpp`. `linux_arm64_android`,
  `linux_amd64_android`, `linux_i686_android` and `osx_arm64` are derived at runtime from
  preprocessor macros, so they do not appear in `strings` output and only a device (or a
  re-read of that header) settles them. Both platform notes rest on them, as does the
  404-vs-200 asymmetry against extensions.duckdb.org — recheck that too, since it is a claim
  about someone else's server.
- **The progress-bar gate.** `SetDefaultConfigArguments` in `src/duckdb_py/pyconnection.cpp`
  turns `enable_progress_bar` on only for what it judges an interactive session, which is why
  [Threading](#threading) tells app authors to `SET` it. Should upstream ever enable it
  unconditionally, that instruction becomes unnecessary rather than wrong.
- **The `pytz` gap.** Check `Requires-Dist` in the built wheel rather than assuming: if
  upstream ever declares it, that bullet and the example's SQL-side formatting both stop
  being necessary.
- **The exception and error strings quoted above** — `CatalogException`,
  `InvalidInputException`, `OutOfMemoryException`, the `ModuleNotFoundError` targets. They are
  upstream's wording and upstream rewords them. Which operators spill and which raise is also
  upstream's business and moves between releases, so re-run the over-the-limit measurement
  rather than trusting the shapes named in [Things to know](#things-to-know).
- **The sizes and the file-by-file comparison**: the per-ABI table, the 551 KB of Python, the
  397 KB `duckdb/experimental`, and the 49 non-extension, non-`.dist-info` files that match the
  same-version desktop wheel. Re-measure from the wheels the bump produces.

The recipe's own tests cover only `import duckdb` and an in-memory round trip, so a green CI
run confirms almost none of the above. Worth adding, in rough order of value: the
`duckdb_extensions()` set, a Parquet `COPY` + `read_parquet` round trip through
`FLET_APP_STORAGE_DATA`, `PRAGMA platform`, and a `config={"memory_limit": …}` connect —
after which the README's promises would turn CI red on their own instead of rotting quietly.
