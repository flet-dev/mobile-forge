# polars

[`polars`](https://pola.rs/) is a DataFrame library written in Rust: columnar storage, a query
optimiser, and a [lazy API](https://docs.pola.rs/user-guide/concepts/lazy-api/) in which you
describe a whole pipeline before any of it runs. Two things make it the interesting table
library on a phone. It is genuinely **parallel** — a group-by spreads across every core the
device has, where [`pandas`](../pandas) here runs on one — and its readers are compiled in, so
CSV, JSON, Parquet, Arrow IPC, Avro and a SQL front-end all work out of the box with no
optional package behind any of them.

## Install

Add polars to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "polars",
]

[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

The [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) line
is required rather than optional. polars uses 64-bit atomics, which 32-bit ARM does not have,
so there is no `armeabi-v7a` wheel — not here and not on PyPI, where upstream ships no 32-bit
build of any kind. Leave the default list alone and the Android build fails when it tries to
resolve packages for that ABI; set it as above and 32-bit devices drop out of your app's device
list instead. 64-bit has been mandatory for Play Store uploads since 2019, so in practice this
costs you old hardware, not current users.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`sales-rollup`](examples/sales-rollup) — joins and groups up to a million synthetic orders
  with the lazy API.

## Usage in a Flet app

Read a file out of app storage, aggregate it, and put the result into a table:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.parquet")

totals = (
    pl.scan_parquet(path)
    .filter(pl.col("hour").is_between(7, 19))
    .group_by("category")
    .agg(orders=pl.len(), revenue=pl.col("revenue").sum())
    .sort("revenue", descending=True)
    .collect()
)

table = ft.DataTable(
    columns=[ft.DataColumn(name) for name in totals.columns],
    rows=[
        ft.DataRow(cells=[ft.DataCell(str(value)) for value in row.values()])
        for row in totals.to_dicts()
    ],
)
```

[`to_dicts()`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.to_dicts.html)
is the bridge from a frame to
[`ft.DataTable`](https://flet.dev/docs/controls/datatable/): a list of plain dicts, one per
row, keyed by column name, and unlike `to_pandas()` or `to_arrow()` it needs nothing installed
beyond polars itself.

### Storage

polars reads and writes ordinary filesystem paths, so its files belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From Flet
0.86.0 it is also the process working directory on device, so a bare relative filename lands
there; spelling it out costs one line and behaves the same on desktop:

```python
df.write_parquet(os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.parquet"))
```

Use [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose; neither is a place to keep the only copy of user data. Do
not write paths beginning with `~`: polars expands them from `$HOME`, which is not a meaningful
location in a mobile app sandbox, so the file lands somewhere you cannot read it back from.

### Lazy queries

Prefer the `scan_*` readers over `read_*` for anything you keep on disk.
[`scan_parquet`](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_parquet.html)
and [`scan_csv`](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_csv.html)
hand the file to the query optimiser, which then reads only the columns and row groups the
query needs — and a phone's storage makes that difference much larger than a laptop's does. A
`read_*` call has already pulled the whole file into memory before your first `filter` is even
parsed.

Write the pipeline in whatever order reads best. Nothing between `scan_*` and
[`collect()`](https://docs.pola.rs/api/python/stable/reference/lazyframe/api/polars.LazyFrame.collect.html)
executes when it is written, so a filter placed after a join still runs before it: polars
pushes predicates down and drops columns the aggregation never reads. Print
[`explain()`](https://docs.pola.rs/api/python/stable/reference/lazyframe/api/polars.LazyFrame.explain.html)
on the pipeline to see the plan it intends to run, which is the fastest way to find a step that
defeated the pushdown.

`collect()` is where memory is spent: it materialises the whole result as a `DataFrame` in RAM.
Aggregate before you collect, not after — collecting a million raw rows in order to count them
is the one shape that turns polars' advantage into an out-of-memory kill on a device.

### Threading

**polars really is multi-threaded here, on both platforms.**
[`thread_pool_size()`](https://docs.pola.rs/api/python/stable/reference/api/polars.thread_pool_size.html)
reports the worker pool it built — normally one per core. That is the whole reason to pick
polars over pandas on a device, and it is worth printing once in your app to confirm you got
it. `POLARS_MAX_THREADS` caps the pool and is read when the pool is first created, so set it
before `import polars` if you want the app to leave cores for the UI; setting it later does
nothing and reports no error.

The count is derived per platform: on Android from the process's CPU affinity mask and any
cgroup CPU quota, on iOS from `sysconf`/`sysctl`. Either can report fewer cores than the
hardware has, and on Android the OS may narrow the mask under thermal or background pressure.
Read `thread_pool_size()` rather than `os.cpu_count()` if the number matters.

Parallel inside does not mean asynchronous outside. `collect()` blocks the thread that calls it
for as long as the query takes, so on the UI thread it freezes the UI regardless of how many
workers it is using. Push it to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end the
handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does not
reach background threads. polars releases the GIL while it works, so a background query and a
live UI genuinely overlap; frames and results then move between threads freely, with no
connection or handle to serialise.

The exception is anything that calls back into Python per row —
[`map_elements`](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.map_elements.html)
and friends — which takes the GIL back for every element and gives up both the parallelism and
the overlap. polars says so itself with a `PolarsInefficientMapWarning` naming the native
expression to use instead; on a phone that warning is worth treating as an error.

### App size

Expect approximately 37–44 MB compressed and 130–185 MB unpacked per architecture, iOS being
the largest slice. Roughly 97% of that is the single compiled extension, so the
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) trick that
shrinks pandas or scipy — both of which carry megabytes of test suites — has nothing to remove
here. The desktop PyPI wheel of the same version unpacks to about 108 MB, so mobile is not
carrying anything extra; polars is simply a large binary, and it is worth budgeting for before
you commit to the dependency.

On Android, use an app bundle, split APKs, or narrow `target_arch` further than the two ABIs
the Install section already requires. These figures are decimal, matching how an index reports
a wheel, so `du -h` shows smaller numbers for the same payload; and they describe the package
payload, not the exact amount added to the final APK or IPA.

### Other considerations

A desktop `flet run` resolves PyPI's polars wheel rather than this one. The Python API is
identical — see the last bullet in [Things to know](#things-to-know) — but the environment
around it is not, and each difference hides a mobile failure:

- The host has `/usr/share/zoneinfo`, so converting a zone-aware value back into a Python
  `datetime` succeeds on your machine and fails on Android. Add `tzdata` to `dependencies`, and
  test time-zone code on a device rather than under `flet run`.
- A development virtualenv that happens to contain `pyarrow` or `pandas`, pulled in by
  something else you installed, makes `to_arrow()` and `to_pandas()` work locally and raise
  `ModuleNotFoundError` on device. Only what is in `dependencies` reaches the app, and that
  goes for every optional path polars has.

## Things to know

- **Every file format is built in, and none of them needs `pyarrow`.** Parquet, Arrow IPC
  (Feather), JSON, NDJSON, Avro and CSV all round-trip with nothing installed but polars:
  [`read_parquet`](https://docs.pola.rs/api/python/stable/reference/api/polars.read_parquet.html)
  takes `use_pyarrow=False` by default and goes through polars' own Rust reader, and
  [`write_parquet`](https://docs.pola.rs/api/python/stable/reference/api/polars.DataFrame.write_parquet.html)
  produces real `PAR1` files with snappy, zstd, LZ4, gzip or brotli (LZO is the one codec that
  is not compiled in, and it is not the default).
  [`pl.sql(...)`](https://docs.pola.rs/api/python/stable/reference/sql/index.html) works too,
  and [`read_database`](https://docs.pola.rs/api/python/stable/reference/api/polars.read_database.html)
  reads straight from a stdlib `sqlite3` connection with no SQLAlchemy, ConnectorX or ADBC
  involved. This is the sharpest difference from [`pandas`](../pandas), where Parquet is
  unavailable on mobile at any price.

- **Most of the extras cannot be installed, and you rarely need them.** What resolves: `numpy`,
  `pandas`, `pyarrow`, `sqlalchemy` and `graph` (matplotlib) have mobile wheels here, and
  `pydantic` resolves through the [`pydantic-core`](../pydantic-core) recipe; `cloudpickle`,
  `fsspec`, `openpyxl`, `xlsx2csv`, `xlsxwriter` and `plot` (altair) are pure Python and come
  from PyPI — though altair only emits Vega-Lite specifications, which Flet has no renderer
  for. What does not resolve at all: `calamine` (fastexcel), `connectorx`, `adbc`, `deltalake`,
  `iceberg`, `async` (gevent), `style` (great-tables, via its native `multimark` dependency),
  `polars-cloud` and `gpu`. That makes the umbrella extras `all`, `database` and `excel`
  unusable as written; ask for the individual pieces instead. The `timezone` extra is a no-op
  off Windows — see the time-zone bullet below for what to install in its place.

- **Handing data to pandas or Arrow needs `pyarrow`, and that costs you the same 32-bit
  exclusion.** [`to_pandas()`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.to_pandas.html)
  and [`to_arrow()`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.to_arrow.html)
  both raise `ModuleNotFoundError: No module named 'pyarrow'` without it, and `pyarrow` has no
  `armeabi-v7a` build either, plus about 31 MB of `flet-libarrow` unpacked per architecture —
  check the [`pyarrow`](../pyarrow) recipe before adding it.
  [`to_numpy()`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.to_numpy.html)
  needs only `numpy`, and `to_dicts()` needs nothing, which is usually all you want for feeding
  Flet controls.

- **Named time zones need the `tzdata` package on Android, and the failure is loud but
  misleading.** polars carries its own copy of the IANA database in Rust, so everything computed
  inside the engine is correct without help:
  [`convert_time_zone`](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.dt.convert_time_zone.html),
  `dt.hour`, `dt.strftime`, printing a frame and `write_csv` all give the right answer.
  Converting a zone-aware value *back into a Python `datetime`* is the part that goes through
  the stdlib `zoneinfo`, and Android ships no IANA directory that `zoneinfo` can read. So
  [`df.item()`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.item.html)
  raises `ZoneInfoNotFoundError` and `to_dicts()` /
  [`Series.to_list()`](https://docs.pola.rs/api/python/stable/reference/series/api/polars.Series.to_list.html)
  surface it as a `pyo3_runtime.PanicException` — a Rust panic, not the exception you would go
  looking for. The fix is one bare dependency, a ~350 KB pure-Python wheel from PyPI that
  `zoneinfo` finds with no configuration:

  ```toml
  dependencies = ["flet", "polars", "tzdata"]
  ```

  Fixed offsets and UTC are unaffected, as are naive timestamps. Do not reach for polars'
  `timezone` extra to do this: it declares `tzdata` only under `platform_system == 'Windows'`
  and installs nothing anywhere else.

- **Remote scanning is compiled in but untested on device.** The object-store, HTTP and TLS
  code is all in the wheel, so `pl.scan_parquet("s3://…")` and an `https://` URL are not going
  to fail for lack of code, and polars needs no `fsspec` for them. Whether TLS trust roots
  resolve inside an app sandbox has not been checked on either platform, so treat
  [cloud storage](https://docs.pola.rs/user-guide/io/cloud-storage/) as unverified and try it
  before you design around it. The temporary directory polars would use to cache remote files
  is derived from `$USER`/`$HOME`, neither of which is dependable on mobile; if you do go
  remote, set `POLARS_TEMP_DIR` to a path under `FLET_APP_STORAGE_CACHE`. Purely local queries
  never initialise that directory.

- **The Python half is the desktop package.** Compared file by file against the PyPI wheel of
  the same version, every Python file is identical except the one recording which architecture
  the wheel was built for. The required-CPU-feature list it checks is empty on mobile as it is
  on desktop arm64, so the "Missing required CPU features … install `polars-lts-cpu`" warning
  cannot fire, including on an x86_64 emulator. Android and iOS are identical to each other
  too. Upstream's documentation therefore applies unchanged, and anything you read about polars
  behaviour is true here unless this page says otherwise.

## Build notes (maintainers)

### Recipe shape

**Excluding `armeabi-v7a` was the choice against patching.** The failure is
`std::sync::atomic::AtomicU64`, and the alternative — routing it through `portable-atomic`,
which ships a lock-based 64-bit fallback — is what the [`tokenizers`](../tokenizers) recipe
does. It was not tried here because polars' use is not a handful of sites in one file but
spread across the whole workspace, and because upstream ships no 32-bit build of polars for any
platform, so a patched 32-bit build would be the only one in existence and unsupported by
anyone. 32-bit x86 is *not* excluded and does build, since it has `cmpxchg8b`.

**The iOS dylib ships unstripped and the Android one does not.** `strip -x -S` on the iOS
`polars.abi3.so` takes it from 180.6 MB to 124.4 MB — 56.2 MB of symbol table in every iOS app
that depends on polars — while the Android `.so` arrives already stripped at 128.9 MB.
Upstream's own release wheels use a `dist-release` cargo profile with `debug = false` and fat
LTO; the plain `release` profile forge gets sets `debug = "line-tables-only"`, which is where
the extra weight comes from. Nobody has established why the strip lands on ELF and not on
Mach-O. Worth chasing before anything else on this recipe: it is the largest available win, and
the figures in [App size](#app-size) move with it.

The patch preamble owns the toolchain, clipboard and allocator changes, and `meta.yaml`
comments own `excluded_arches`. Do not duplicate those mechanisms here.

### Upgrade hazards

**The 1.33 line is a hard version ceiling, so a bump here is not a routine bump.** polars
stopped putting the Rust workspace in its PyPI sdist after it: 1.33.0 and 1.33.1 ship the full
`crates/` and `py-polars/` trees (~4.7 MB), while 1.34.0 and later ship ~700 KB of Python with
no `.rs` files and no `Cargo.toml`. There is nothing for forge to cross-compile in those, and
forge has no `git_url`/`git_rev` support, so anything past 1.33.1 needs a custom builder that
fetches the GitHub source. Until that exists, 1.33.1 is the only bump available at all.

**The pinned Rust toolchain reaches outside this recipe.** The patch's target list has to match
the triples forge builds — `arm-linux-androideabi`, not `armv7-…` — and getting that wrong
fails only on the Python version that still builds 32-bit. Forge's Android Rust link step also
writes a `libgcc.a` shim because polars' pinned old nightly still emits `-lgcc`, which current
stable does not; if a bump moves the pin forward, check whether that shim still does anything.

### Re-verification checklist

In rough order of how quietly each one can go wrong:

- **That the sdist still contains Rust at all.** Check the tarball size and that `crates/`
  exists before starting; a 700 KB sdist means the ceiling above has been hit.
- **The claim that nothing is required at runtime.** Read `Requires-Dist` off the built wheel
  and confirm every line still carries an `extra ==` marker — all 25 did. A release promoting
  an extra to a hard dependency is invisible otherwise; the wheel still builds and imports.
- **The extras matrix**, re-derived from the new `Provides-Extra` list rather than edited: what
  resolves is as much a fact about the other recipes and about PyPI as about polars, and polars
  adds and renames extras between releases.
- **That the format round-trips still hold.** Parquet, IPC, JSON, NDJSON, Avro, CSV and
  `pl.sql` were each exercised with no optional package installed. Upstream moves features
  between crates, and `polars-parquet` or `avro-schema` dropping out would leave the wheel
  building fine and the README wrong; same for the `object_store`/`reqwest`/`rustls` set behind
  the remote-scanning bullet.
- **The threading claims:** `rayon`/`rayon-core` in the crate set, `pthread_create` imported by
  the extension on both platforms, `POLARS_MAX_THREADS` still capping the pool. A build that
  quietly lost its thread pool would still pass every test in `tests/`.
- **That polars still makes no runtime read from its own installation**, which is what lets the
  wheel run from zipped site-packages with no `extract_packages` entry. Re-derive the sites
  building a path from `__file__`: two compare it against traceback filenames for a warning's
  `stacklevel`, and the third is `identify_deprecations`, which nothing calls.
- **What the extension links:** nothing beyond `libc`/`libm`/`libdl` and Python itself on
  Android, `libSystem`/`libiconv`/CoreFoundation on iOS. A new C or C++ crate would pull in
  `libc++_shared.so` and with it a `flet-libcpp-shared` requirement the recipe does not declare.
- **The sizes and the strip figure**, measured per architecture from the published wheels —
  37.1/133.1 MB Android arm64-v8a, 40.8/147.7 MB Android x86_64, 43.5/184.8 MB iOS device,
  compressed/unpacked and decimal. Re-measure rather than scaling.
- **The time-zone split.** That the Rust side answers correctly without `tzdata` while
  `.item()` and `.to_dicts()` do not was reproduced by emptying `zoneinfo`'s search path on
  desktop, not on a device. If polars ever converts zones on the Python side, or the Flet Python
  bundle starts shipping an IANA database, that bullet goes wrong in the safe direction — but
  check it rather than assuming.

### Coverage gaps

`tests/` holds one test: a five-row group-by collected with `to_dicts()`. It proves the wheel
imports and that the engine runs, and nothing more. Every other consumer claim here — the six
file formats, `pl.sql`, `read_database`, the thread pool, the time-zone split, remote scanning
and the sizes — rests on inspection of the wheel or on desktop reproduction. The example app is
the only on-device exercise of a real pipeline.

CI narrows the matrix further: the mobile test builds Android `--arch x86_64` and
`ios-simulator` only, so arm64-v8a and real iOS hardware are green at build time but never
executed. Since the recipe forces the system allocator specifically because of an x86_64
Android seccomp failure, that arch difference is the one worth keeping in view.
