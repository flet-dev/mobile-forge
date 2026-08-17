# polars

[`polars`](https://pola.rs/) is a DataFrame library written in Rust: columnar storage, a query
optimiser, and a [lazy API](https://docs.pola.rs/user-guide/concepts/lazy-api/) in which you
describe a whole pipeline before any of it runs. Two things make it the interesting table
library on a phone. It is genuinely **parallel** — a group-by spreads across every core the
device has, where [`pandas`](../pandas) here runs on one — and its readers are compiled in, so
CSV, JSON, Parquet, Arrow IPC, Avro and a SQL front-end all work out of the box with no
optional package behind any of them.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "polars",
]

[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

The
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) line is
required rather than optional. polars uses 64-bit atomics, which 32-bit ARM does not have, so
there is no `armeabi-v7a` wheel — not here and not on PyPI, where upstream ships no 32-bit
build of any kind. Leave the default list alone and the Android build fails when it tries to
resolve packages for that ABI; set it as above and every 32-bit Android device drops out of
your app's device list instead. 64-bit has been mandatory for Play Store uploads since 2019,
so in practice this costs you old hardware, not current users.

Nothing else comes along. The wheel's metadata has **no unconditional requirements at all** —
every one of polars' 25 extras sits behind an `extra ==` marker — so `numpy`, `pandas` and
`pyarrow` are installed only if you ask for them. There is no `flet-libcpp-shared` either: the
extension is Rust, and links nothing beyond `libc`/`libm`/`libdl` and Python itself on Android,
`libSystem`, `libiconv` and CoreFoundation on iOS.

No [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
needed. Apart from the compiled extension and a `py.typed` marker the package is nothing but
Python source, and nothing you would call opens a file from its own installation: of the three
places that build a path from `__file__`, two compare it against traceback filenames to work
out a warning's `stacklevel`, and the third is `identify_deprecations`, a maintenance helper
nothing in polars calls.

Builds for Python 3.12, 3.13 and 3.14, on Android arm64-v8a and x86_64 and on iOS for device
and both simulator slices.

## Storage

polars reads and writes ordinary filesystem paths, so its files belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From Flet
0.86.0 it is also the process working directory on device, so a bare relative filename lands
there; spelling it out costs one line and behaves the same on desktop:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.parquet")
df.write_parquet(path)
totals = pl.scan_parquet(path).group_by("category").agg(pl.col("amount").sum()).collect()
```

Prefer the `scan_*` readers over `read_*` for anything you keep on disk:
[`scan_parquet`](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_parquet.html)
and [`scan_csv`](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_csv.html)
hand the file to the query optimiser, which then reads only the columns and row groups the
query needs — the difference between the two is much larger on a phone's storage than on a
laptop's.

Use
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose; neither is a place to keep the only copy of user data. Do
not write paths beginning with `~`: polars expands them from `$HOME`, which is not a meaningful
location in a mobile app sandbox.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`sales-rollup`](examples/sales-rollup) — joins and groups up to a million synthetic orders with the lazy API.

## Threading

**polars really is multi-threaded here, on both platforms.** The wheels carry `rayon` and
`rayon-core`, the extension imports `pthread_create`, and
[`thread_pool_size()`](https://docs.pola.rs/api/python/stable/reference/api/polars.thread_pool_size.html)
reports the pool it built — normally one worker per core. That is the whole reason to pick
polars over pandas on a device, and it is worth printing once in your app to confirm you got
it. `POLARS_MAX_THREADS` caps the pool and is read when the pool is first created, so set it
before `import polars` if you want the app to leave cores for the UI.

The count is derived per platform: on Android from the process's CPU affinity mask and any
cgroup CPU quota, on iOS from `sysconf`/`sysctl`. Either can report fewer cores than the
hardware has, and on Android the OS may narrow the mask under thermal or background pressure.
Read `thread_pool_size()` rather than `os.cpu_count()` if the number matters.

Parallel inside does not mean asynchronous outside.
[`collect()`](https://docs.pola.rs/api/python/stable/reference/lazyframe/api/polars.LazyFrame.collect.html)
blocks the thread that calls it for as long as the query takes, so on the UI thread it freezes
the UI regardless of how many workers it is using. Push it to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end the
handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does not
reach background threads. polars releases the GIL while it works, so a background query and a
live UI genuinely overlap rather than taking turns.

The exception is anything that calls back into Python per row —
[`map_elements`](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.map_elements.html)
and friends — which takes the GIL back for every element and gives up both the parallelism and
the overlap. polars says so itself with a `PolarsInefficientMapWarning` that names the native
expression to use instead; on a phone that warning is worth treating as an error.

Frames and results move between threads freely; there is no connection or handle to serialise.

## Things to know

- **It is a very large wheel, and there is nothing to trim.** Roughly 97% of it is the single
  compiled extension, so the `[tool.flet.cleanup]` trick that shrinks pandas or scipy — both of
  which carry megabytes of test suites — has nothing to remove here:

  | wheel | download | unpacked | of which `polars.abi3.so` |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 37.1 MB | 133.1 MB | 128.9 MB |
  | Android x86_64 | 40.8 MB | 147.7 MB | 143.6 MB |
  | iOS arm64 (device) | 43.5 MB | 184.8 MB | 180.6 MB |

  The iOS slice is the biggest because its dylib still carries its symbol table; see
  [Build notes](#build-notes-maintainers). For comparison the desktop PyPI wheel of the same
  version unpacks to 108.1 MB, so mobile is not carrying anything extra — polars is simply a
  large binary. Budget for it before you commit to the dependency.
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
- **Most of the extras cannot be installed, and you rarely need them.** What resolves:
  `numpy`, `pandas`, `pyarrow`, `sqlalchemy` and `graph` (matplotlib) have mobile wheels here,
  and `pydantic` resolves through the [`pydantic-core`](../pydantic-core) recipe;
  `cloudpickle`, `fsspec`, `openpyxl`, `xlsx2csv`, `xlsxwriter` and `plot` (altair) are
  pure Python and come from PyPI — though altair only emits Vega-Lite specifications, which
  Flet has no renderer for. What does not resolve at all: `calamine` (fastexcel), `connectorx`,
  `adbc`, `deltalake`, `iceberg`, `async` (gevent), `style` (great-tables, via its native
  `multimark` dependency), `polars-cloud` and `gpu`. That makes the umbrella extras `all`,
  `database` and `excel` unusable as written; ask for the individual pieces instead. The
  `timezone` extra is a no-op off Windows — see the time-zone bullet below for what to install
  in its place.
- **Handing data to pandas or Arrow needs `pyarrow`, and that costs you the same 32-bit
  exclusion.** [`to_pandas()`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.to_pandas.html)
  and `to_arrow()` both raise `ModuleNotFoundError: No module named 'pyarrow'` without it, and
  `pyarrow` has no `armeabi-v7a` build either, plus about 31 MB of `flet-libarrow` unpacked per
  architecture — check the [`pyarrow`](../pyarrow) recipe before adding it.
  [`to_numpy()`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.to_numpy.html)
  needs only `numpy`, and
  [`to_dicts()`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.to_dicts.html)
  needs nothing, which is usually all you want for feeding Flet controls.
- **Named time zones need the `tzdata` package on Android, and the failure is loud but
  misleading.** polars carries its own copy of the IANA database in Rust, so everything
  computed inside the engine is correct without help:
  [`convert_time_zone`](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.dt.convert_time_zone.html),
  `dt.hour`, `dt.strftime`, printing a frame and `write_csv` all give the right answer.
  Converting a zone-aware value *back into a Python `datetime`* is the part that goes through
  the stdlib `zoneinfo`, and Android ships no IANA directory that `zoneinfo` can read. So
  `df.item()` raises `ZoneInfoNotFoundError` and `to_dicts()` / `Series.to_list()` surface it
  as a `pyo3_runtime.PanicException` — a Rust panic, not the exception you would go looking
  for. The fix is one bare dependency, a ~350 KB pure-Python wheel from PyPI that `zoneinfo`
  finds with no configuration:

  ```toml
  dependencies = ["flet", "polars", "tzdata"]
  ```

  Fixed offsets and UTC are unaffected, as are naive timestamps. Do not reach for polars'
  `timezone` extra to do this: it declares `tzdata` only under `platform_system == 'Windows'`
  and installs nothing anywhere else.
- **Remote scanning is compiled in but untested on device.** `object_store`, `reqwest` and
  `rustls` are all in the wheel, so `pl.scan_parquet("s3://…")` and an `https://` URL are not
  going to fail for lack of code, and polars needs no `fsspec` for them. Whether TLS trust
  roots resolve inside an app sandbox has not been checked on either platform, so treat
  [cloud storage](https://docs.pola.rs/user-guide/io/cloud-storage/) as unverified and try it
  before you design around it. The temporary directory polars would use to cache remote files
  is derived from `$USER`/`$HOME`, neither of which is dependable on mobile; if you do go
  remote, set `POLARS_TEMP_DIR` to a path under `FLET_APP_STORAGE_CACHE`. Nothing else in
  polars touches that directory — purely local queries never initialise it.
- **The Python half is byte-for-byte the desktop package.** Compared file by file against the
  PyPI wheel of the same version, 193 of the 194 Python files are identical, and the 194th
  differs by one line: `_cpu_check.py` records the architecture the wheel was built for. The
  required-CPU-feature list it checks is empty on mobile as it is on desktop arm64, so the
  "Missing required CPU features … install `polars-lts-cpu`" warning cannot fire, including on
  an x86_64 emulator. Android and iOS are identical to each other too, down to the same crate
  set apart from three platform crates. So upstream's documentation applies unchanged, and
  anything you read about polars behaviour is true here unless this page says otherwise.

## Build notes (maintainers)

The patch explains its three changes in its own preamble and `meta.yaml` justifies
`excluded_arches` next to it, so this section is what neither file records.

**The 1.33 line is a hard version ceiling, so a bump here is not a routine bump.** polars
stopped putting the Rust workspace in its PyPI sdist after it: 1.33.0 and 1.33.1 ship the full
`crates/` and `py-polars/` trees (~4.7 MB), while 1.34.0 and later ship ~700 KB of Python with
no `.rs` files and no `Cargo.toml`. There is nothing for forge to cross-compile in those, and
forge has no `git_url`/`git_rev` support, so anything past 1.33.1 needs a custom builder that
fetches the GitHub source. Until that exists, 1.33.1 is the only bump available at all.

**Excluding `armeabi-v7a` was the choice against patching.** The failure is
`std::sync::atomic::AtomicU64`, and the alternative — routing it through `portable-atomic`,
which ships a lock-based 64-bit fallback — is what the [`tokenizers`](../tokenizers) recipe
does. It was not tried here because polars' use is not a handful of sites in one file but
spread across the whole workspace, and because upstream ships no 32-bit build of polars for
any platform, so a patched 32-bit build would be the only one in existence and unsupported by
anyone. 32-bit x86 is *not* excluded and does build, since it has `cmpxchg8b`.

**The iOS dylib ships unstripped and the Android one does not.** `strip -x -S` on the iOS
`polars.abi3.so` takes it from 180.6 MB to 124.4 MB — 56.2 MB of symbol table in every iOS
app that depends on polars — while the Android `.so` arrives already stripped at 128.9 MB.
Upstream's own release wheels use a `dist-release` cargo profile with `debug = false` and fat
LTO; the plain `release` profile forge gets sets `debug = "line-tables-only"`, which is where
the extra weight comes from. Nobody has established why the strip lands on ELF and not on
Mach-O. Worth chasing before anything else on this recipe: it is the largest available win,
and the size table in [Things to know](#things-to-know) moves with it.

What to re-verify on a bump, in rough order of how quietly it can go wrong:

- **That the sdist still contains Rust at all.** Check the tarball size and that `crates/`
  exists before starting; a 700 KB sdist means the ceiling above has been hit and the build
  will fail in a confusing place.
- **The claim that nothing is required at runtime.** Read `Requires-Dist` off the built wheel
  and confirm every line still carries an `extra ==` marker. A polars release that promotes
  one of its extras to a hard dependency rewrites the whole Install section, and would be
  invisible otherwise because the wheel would still build and import.
- **The extras matrix.** Which extras resolve is as much a fact about the other recipes and
  about PyPI as about polars — `multimark` gaining a mobile wheel, or `fastexcel` getting a
  recipe, each move a line. Re-derive it from the new `Provides-Extra` list rather than
  editing the old one, since polars adds and renames extras between releases.
- **That the format round-trips still hold.** Parquet, IPC, JSON, NDJSON, Avro, CSV and
  `pl.sql` were each exercised with no optional package installed; the recipe's test covers
  only the group-by. Upstream moves features between crates, and `polars-parquet` or
  `avro-schema` dropping out of the crate set would leave the wheel building fine and the
  README wrong.
- **The threading claims.** `rayon`/`rayon-core` in the crate set, `pthread_create` imported by
  the extension on both platforms, and `POLARS_MAX_THREADS` still capping the pool. These are
  the reason to choose polars at all, and a build that quietly lost its thread pool would
  still pass every test in `tests/`.
- **The pinned Rust toolchain.** Two things hang off it that live outside this recipe. The
  patch's target list has to match the triples forge builds — `arm-linux-androideabi`, not
  `armv7-…`, and getting that wrong fails only on the Python version that still builds 32-bit.
  And forge's Android Rust link step writes a `libgcc.a` shim because polars' pinned old
  nightly still emits `-lgcc`, which current stable does not; if a bump moves the pin forward,
  check whether that shim is still doing anything.
- **The sizes and the strip figure.** Measured per architecture from the published wheels;
  re-measure rather than scaling, particularly if the profile question above gets resolved.
- **The time-zone split.** That the Rust side answers correctly without `tzdata` while
  `.item()` and `.to_dicts()` do not was reproduced by emptying `zoneinfo`'s search path on
  desktop, not on a device. If polars ever converts zones on the Python side, or the Flet
  Python bundle starts shipping an IANA database, that bullet becomes wrong in the safe
  direction — but check it rather than assuming.
