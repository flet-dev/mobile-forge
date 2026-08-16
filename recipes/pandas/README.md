# pandas

[`pandas`](https://pandas.pydata.org/) is the standard table library for Python: labelled
columns, joins, group-bys, rolling windows, time series, and readers and writers for CSV,
JSON, SQL, pickle, Stata and SAS. On mobile it is what lets an app hold a real dataset in
memory and reshape it offline — reading a log the app itself wrote, summarising it, and
handing the result to Flet controls — instead of shipping rows to a server to be
aggregated. Every compiled kernel is in the wheel: these are the same 45 extension
modules the desktop wheel has, and the Python half is byte-for-byte the same code.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pandas",
]
```

Nothing else is *required*. In particular no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry and no
restriction on
[Android target architectures](https://flet.dev/docs/publish/android/#supported-target-architectures),
because **pandas does not require `pyarrow`** — which is the one thing worth reading
[Things to know](#things-to-know) for before you start. Two *optional* entries are worth
knowing about: one that drops 13 MB from your app, and one you need only if you want
`DataFrame.style` on Android.

What comes along needs no configuring either: `numpy`, which pandas is built on;
`python-dateutil` and its `six`, pure-Python wheels that resolve from PyPI; and, on Android
only, `flet-libcpp-shared`, the NDK C++ runtime that exactly one of pandas' extensions —
`pandas/_libs/window/aggregations` — links against. Add `numpy` to the list yourself only
if your own code imports it.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for
iOS, on Python 3.12, 3.13 and 3.14 — and the same pandas version on every one of them, so
a 32-bit phone gets what a 64-bit phone gets.

## Storage

pandas reads and writes ordinary filesystem paths, so everything it produces belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From
Flet 0.86.0 it is also the process working directory on device, so a bare relative filename
lands there; spelling it out costs one line and behaves the same on desktop:

```python
csv_path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.csv")
df.to_csv(csv_path, index=False)
df = pd.read_csv(csv_path)
```

Use
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for a scratch file you re-derive on demand, and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for something you can afford to lose — the OS may purge it under storage pressure, and
temp may vanish between launches. Neither is a place to keep the only copy of user data.

[`read_csv`](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html) and friends
also take a file object, so anything you have already opened — a download, an in-memory
`io.StringIO` — needs no path at all. An `http://` or `https://` string works too: pandas
fetches it with stdlib `urllib`, no extra package involved, though it does so synchronously
and belongs in a background thread. `s3://` and `gs://` do not work — those go through
`fsspec`, which has no mobile wheel.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`orders-summary`](examples/orders-summary) — groups a CSV kept in app storage and shows the totals.

## Threading

**pandas is single-threaded here, and there is no way to change that.** Its 45 extensions
contain no reference to `pthread_create` and none to OpenMP, on either platform — one
group-by runs on one core no matter how many the phone has. The optional accelerators that
would change the picture on a desktop are not available for mobile either: `numexpr`,
`bottleneck` and `numba` have no wheels on this index, so
`pd.get_option("compute.use_numexpr")` reports `True` while pandas quietly runs its own
kernels. Nothing errors; the speed is just the speed.

Which makes it all the more important that work happens off the handler thread. A
group-by over a large frame on the UI thread freezes the UI. Push it to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads.

pandas itself imposes no thread rules: frames and results move between threads freely, and
there is no connection or handle to serialise. Two threads *mutating* the same DataFrame is
your problem, not something pandas will detect, but the ordinary pattern — build a frame in
the worker, hand it back — needs no lock.

## Android notes

Installed packages live inside a zip on Android, and one corner of pandas assumes they do
not. [`DataFrame.style`](https://pandas.pydata.org/docs/reference/style.html) loads its
jinja2 templates through a `FileSystemLoader` pointed at `pandas/io/formats/templates/`,
resolved from that module's own `__file__` the first time `.style` is touched. Inside a zip
that is not a directory, so the templates are not found. If you want the Styler on Android,
extract the package:

```toml
[tool.flet.android]
extract_packages = ["pandas"]
```

That is the only part of pandas that reads a file from its own installation — nothing else
in the package touches `__file__` at runtime — so without `.style` you need no entry at
all. `.style` additionally needs `jinja2` in your dependencies, on every platform;
[`to_html`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_html.html)
and `to_string` do not, and are unaffected by any of this.

## Things to know

- **`pyarrow` is optional, and you almost certainly do not want it.** pandas 3.0 made `str`
  the default dtype for text columns, and it is Arrow-backed *when pyarrow is installed*;
  when it is not, the same `str` dtype falls back to a Python-object implementation
  (`StringDtype(storage='python')`) and everything keeps working. The shipped wheel's
  metadata is explicit: the only hard requirements are `numpy` and `python-dateutil`, with
  `pyarrow` behind the `pyarrow`, `parquet`, `feather` and `all` extras. What you give up
  by leaving it out is memory and speed on string-heavy frames — on a desktop, 200 000
  short strings measured 11.4 MB with the Python storage against 3.2 MB Arrow-backed, a
  group-by on that column ran about 3× slower and `.str.upper()` about 5×. (Desktop ratios,
  not device ones — treat them as the shape of the problem.) What you pay for putting it in
  is roughly 17 MB of pyarrow plus 31 MB of `flet-libarrow` unpacked per Android
  architecture — and armeabi-v7a, which `pyarrow` does not build for at all, so every
  32-bit Android device drops out of your build unless you also set
  `[tool.flet.android] target_arch`. Add it only for a specific feature you need, and check
  the [`pyarrow`](../pyarrow) recipe first.
- **Parquet is not available, with or without pyarrow.** The mobile `pyarrow` is built with
  the Parquet component off — there is no `_parquet` extension in the wheel — and
  `fastparquet` has no mobile wheel either, so
  [`to_parquet`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_parquet.html)
  raises `ImportError: Unable to find a usable engine` no matter what you install.
  [`to_feather`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_feather.html)
  *does* work once pyarrow is installed. For a columnar file that needs no extra
  dependency at all, compressed CSV is the honest answer.
- **Named time zones need the `tzdata` package.** pandas 3.0 resolves zones through the
  stdlib `zoneinfo`, which reads a directory of IANA files from `/usr/share/zoneinfo` and
  three sibling paths. **None of those four exist on Android** — the OS keeps its own
  database in a bionic-specific format that Python cannot read — and Flet's Python bundle
  ships no copy, so `pd.Timestamp("2026-06-01", tz="Europe/Paris")` and
  `Series.dt.tz_convert("America/New_York")` raise
  `ZoneInfoNotFoundError: 'No time zone found with key …'`. Fixed-offset and UTC work
  everywhere, and naive timestamps are unaffected. The fix is one bare dependency, a 340 KB
  pure-Python wheel from PyPI that `zoneinfo` finds with no configuration:

  ```toml
  dependencies = ["flet", "pandas", "tzdata"]
  ```

  Add it whenever you touch [time
  zones](https://pandas.pydata.org/docs/user_guide/timeseries.html#time-zone-handling), and
  the question stops depending on which platform you are on. The failure above was
  reproduced on Android; iOS is untested, because the simulator resolves zones against the
  host Mac's `/usr/share/zoneinfo` and would pass whether or not a real device does.
- **Size, and the 13 MB you can delete.** The wheels are 9–10 MB and unpack to 32–41 MB
  depending on architecture (Android arm64-v8a: 9.4 MB and 35.7 MB; iOS arm64: 9.8 MB and
  40.8 MB). Of that unpacked total, 13.0 MB on every architecture is pandas' own `tests`
  package, which your app will never import. Flet's default
  [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) does not remove
  it — it strips headers, static archives and `__pycache__`, not test suites — so say so
  yourself:

  ```toml
  [tool.flet.cleanup]
  package_files = ["pandas/tests"]
  ```

  pandas imports and runs fine without it; only `pandas.test()` goes away.
  [`pandas.testing`](https://pandas.pydata.org/docs/reference/testing.html) lives elsewhere
  in the package and survives.
- **What the readers and writers can and cannot do without extra dependencies.** Working
  out of the box: CSV (including `gzip`, `bz2`, `xz` and `zip` compression, and the fast C
  parser), JSON, pickle, Stata, SAS, `to_html`, `to_string`, and
  [`read_sql`](https://pandas.pydata.org/docs/reference/api/pandas.read_sql.html) against a
  plain stdlib `sqlite3` connection — no SQLAlchemy needed. Needing a package that *does*
  have a mobile wheel: `read_html`/`read_xml` (`lxml`), `DataFrame.plot` (`matplotlib`),
  SQLAlchemy engines (`sqlalchemy`), `.zst` compression (`zstandard`). Needing a
  pure-Python package from PyPI: Excel (`openpyxl`, `xlsxwriter`, `xlrd`), `.style`
  (`jinja2`), `to_markdown` (`tabulate`). Not available at all: HDF5 (`tables`), SPSS
  (`pyreadstat`), Iceberg, the ADBC drivers, and the `fsspec` remote filesystems. Each of
  these raises a named `ImportError` telling you which package is missing, so nothing fails
  silently.
- **Everything else in pandas is here.** Measured file-by-file against the desktop wheel of
  the same version, the mobile wheels contain exactly the same 1516 files, the same 45
  extension modules and the same 1421 Python files byte-for-byte. The one file that differs
  at all is the vestigial `pandas/pyproject.toml` the wheel happens to carry, which this
  recipe's patch appends a build setting to. Nothing is compiled out, and Android and iOS
  are identical to each other.

## Build notes (maintainers)

pandas builds through meson-python, and the recipe is three settings and one patch:

- `mobile.patch` adds `[tool.meson-python] meson = "meson-wrapper.py"` plus that
  three-line wrapper, which re-enters meson through `sys.executable`. Without it
  meson-python runs the `meson` console script from `PATH`, whose shebang points at the
  *build* Python; meson then reads the build Python's sysconfig and leaks its `Python.h`
  include path into the Cython sanity check, which on the 32-bit Android targets fails as
  `pyport.h: LONG_BIT definition appears wrong for platform`. The wrapper is the only
  consumer-visible trace of the patch: it is why the `pandas/pyproject.toml` inside the
  wheel differs from upstream's.
- `PYTHONSAFEPATH=1` in `script_env`. meson introspects numpy by running the cross-Python
  from pandas' source directory, where the top-level `pandas/io/` shadows the stdlib `io`
  on `sys.path[0]` and numpy's C extension fails to initialise
  (`cannot import name 'TextIOWrapper' from 'io'`). `PYTHONSAFEPATH` drops that implicit
  entry while leaving `PYTHONPATH` alone, so crossenv's bridge still works.
- `backend-args` passes `-Csetup-args=--cross-file {MESON_CROSS_FILE}`, the standard
  meson-python cross-build handoff.
- `flet-libcpp-shared` is an Android-only host requirement because
  `pandas/_libs/window/aggregations` is the one C++ translation unit in the package; iOS
  picks up `/usr/lib/libc++.1.dylib` from the OS instead. Everything else in `_libs` is C.
