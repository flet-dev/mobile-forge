# pandas

[`pandas`](https://pandas.pydata.org/) is the standard table library for Python: labelled
columns, joins, group-bys, rolling windows, time series, and readers and writers for CSV,
JSON, SQL, pickle, Stata and SAS. On mobile it is what lets an app hold a real dataset in
memory and reshape it offline — reading a log the app itself wrote, summarising it, and
handing the result to Flet controls — instead of shipping rows to a server to be
aggregated.

## Install

Add pandas to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pandas",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`orders-summary`](examples/orders-summary) — groups a CSV kept in app storage and shows
  the totals.

## Usage in a Flet app

Read a frame out of app storage, group it, and put the result into a table:

```python
orders = pd.read_csv(os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.csv"))
summary = (
    orders.groupby("region")
    .agg(orders=("units", "size"), revenue=("revenue", "sum"))
    .sort_values("revenue", ascending=False)
    .reset_index()
)

table = ft.DataTable(
    columns=[ft.DataColumn(ft.Text(name)) for name in summary.columns],
    rows=[
        ft.DataRow(cells=[ft.DataCell(ft.Text(str(value))) for value in row.values()])
        for row in summary.to_dict("records")
    ],
)
```

[`to_dict("records")`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_dict.html)
is the least awkward bridge from a frame to
[`ft.DataTable`](https://flet.dev/docs/controls/datatable/): a list of plain dicts, one per
row, keyed by column name.
[`reset_index()`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.reset_index.html)
is what completes it — a
[`groupby`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.groupby.html)
leaves the group label on the index, where `to_dict("records")` cannot see it, so without
that call the table arrives with totals and no labels.

### Storage

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
and belongs in a background thread. `s3://` and `gs://` paths go through `fsspec`, which
has no mobile wheel, and raise `ImportError: Missing optional dependency 'fsspec'` — fetch
the object yourself and hand pandas the bytes.

### Threading

**pandas is single-threaded here, and there is no way to change that.** One group-by runs
on one core however many the phone has. The optional accelerators that would change that
on a desktop are not on this index either: `numexpr`, `bottleneck` and `numba` have no
mobile wheels, so `pd.get_option("compute.use_numexpr")` answers `True` while pandas
quietly runs its own kernels. Nothing errors and nothing warns; the speed is just the
speed.

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

### DataFrame.style and packaged templates

Installed packages live inside a zip on Android, and one corner of pandas assumes they do
not. [`DataFrame.style`](https://pandas.pydata.org/docs/reference/style.html) loads its
jinja2 templates through a `FileSystemLoader` pointed at `pandas/io/formats/templates/`,
resolved from that module's own `__file__` the first time `.style` is touched. Inside a zip
that is not a directory, so the templates are not found. If you want the Styler on Android,
[extract the package](https://flet.dev/docs/publish/android/#extract-packages):

```toml
[tool.flet.android]
extract_packages = ["pandas"]
```

That is the only part of pandas that reads a file from its own installation — nothing else
in the package touches `__file__` at runtime — so without `.style` you need no entry at
all. `.style` additionally needs `jinja2` in your dependencies, on every platform;
[`to_html`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_html.html)
and `to_string` do not, and are unaffected by any of this.

### App size

Expect approximately 9–11 MB compressed and 32–41 MB unpacked per architecture. About
13 MB of that unpacked total, on every architecture, is pandas' own `tests` package, which
an app never imports. Flet's default
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) strips headers,
static archives and `__pycache__`, not test suites, so name it yourself:

```toml
[tool.flet.cleanup]
package_files = ["pandas/tests"]
```

pandas imports and runs fine without it; only `pandas.test()` goes away, and
[`pandas.testing`](https://pandas.pydata.org/docs/reference/testing.html) lives elsewhere
in the package and survives.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI. These figures describe the package payload, not the exact
amount added to the final APK or IPA; packaging and compression determine that result.
They are decimal, so re-measuring with `du` — which reports binary units and turns 13 MB
into 12 M — reads as a regression that is not there.

### Other considerations

A desktop `flet run` resolves PyPI's pandas wheel rather than this one. The Python API is
identical, but the environment around it is not, and each difference hides a mobile
failure:

- The host has `/usr/share/zoneinfo`, so `pd.Timestamp("2026-06-01", tz="Europe/Paris")`
  succeeds on your machine and raises `ZoneInfoNotFoundError` on Android. Add `tzdata` to
  `dependencies`, and test time-zone code on a device rather than under `flet run`.
- A development virtualenv that happens to contain `pyarrow`, pulled in by something else
  you installed, silently changes the default string backend. `dtype.storage` reads
  `pyarrow` there and `python` on the device, so anything branching on it — or any memory
  figure measured there — describes the wrong build.
- Optional engines resolve against whatever the machine already has, so `openpyxl`, `lxml`
  or `sqlalchemy` sitting in the dev environment makes a reader work under `flet run` that
  raises `ImportError` on device unless it is also in `dependencies`.

## Things to know

- **`pyarrow` is optional, and you almost certainly do not want it.** pandas 3.0 made `str`
  the default dtype for text columns, and it is Arrow-backed *when pyarrow is installed*;
  when it is not, the same `str` dtype falls back to a Python-object implementation
  (`StringDtype(storage='python')`) and everything keeps working. What you give up by
  leaving it out is memory and speed on string-heavy frames: 200 000 short strings
  measured about 11 MB with the Python storage against about 3 MB Arrow-backed, a group-by
  on that column ran roughly 3× slower and `.str.upper()` roughly 5× — desktop ratios, so
  treat them as the shape of the problem rather than device numbers. What you pay for
  putting it in is roughly 17 MB of pyarrow plus 31 MB of `flet-libarrow` unpacked per
  Android architecture — and armeabi-v7a, which `pyarrow` does not build for at all, so
  every 32-bit Android device drops out of your build unless you also set
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
  zones](https://pandas.pydata.org/docs/user_guide/timeseries.html#time-zone-handling). The
  failure was reproduced on Android; iOS is untested, because the simulator resolves zones
  against the host Mac's `/usr/share/zoneinfo` and would pass either way.
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

- **Nothing is compiled out, and the two platforms are identical.** The mobile wheel carries
  the same 45 extension modules as the desktop one and the same Python sources byte-for-byte,
  so an API that exists on your laptop exists on the device. The exceptions are the two
  optional engines above, which are absent because a *dependency* is absent rather than
  because pandas was trimmed.

## Build notes (maintainers)

### Recipe shape

pandas' own meson-python build is used unchanged — no PEP 517 shim, nothing vendored,
nothing compiled out — so `meta.yaml` is the standard cross-file handoff plus the two
settings its comments justify, and the one patch explains itself in its preamble. The
Android host dependency on `flet-libcpp-shared` exists because exactly one translation unit
in `_libs` is C++; that comment lives next to the requirement.

### Upgrade hazards

- pandas moves its build-requirement floors (numpy, meson-python) between releases, so read
  upstream's `pyproject.toml` against the `requirements` block rather than assuming the
  existing pins still bracket it.
- Check whether meson-python has since gained a supported way to choose the interpreter.
  That would retire the patch entirely, and with it the claim that a single file differs
  from the desktop wheel.
- A pandas release that promotes `pyarrow` to a hard requirement, or that changes the
  default string backend, rewrites the whole first Things-to-know bullet and takes
  armeabi-v7a with it.

### Re-verification checklist

- **The patch's anchor.** Confirm `mobile.patch` still applies at the point it names rather
  than landing with fuzz elsewhere, and that all three Android ABIs (arm64-v8a,
  armeabi-v7a, x86_64) plus iOS resolve the *same* pandas version on 3.12, 3.13 and 3.14.
  A 32-bit-only failure is the tell that it did not, and the symptom is distinctive: the two
  32-bit Android ABIs fail on `LONG_BIT definition appears wrong for platform` while
  arm64-v8a and iOS go green.
- **The desktop-wheel comparison.** Diff the built wheels against PyPI's desktop wheel of
  the same version: total files, extension modules, byte-identical Python files, and
  `pandas/pyproject.toml` as the only difference. That diff is the sole evidence for
  "nothing is compiled out" and "Android and iOS are identical", and no test asserts it.
- **The single-threaded claim.** No extension may reference `pthread_create` or OpenMP on
  either platform; a new one that does invalidates the Threading section outright.
- **The `__file__` inventory.** `pandas/io/formats/templates/` must remain the only thing
  pandas reads from its own installation. A new template or data file loaded that way turns
  `extract_packages` from optional into mandatory for everyone.
- **What is required versus optional.** Read `Requires-Dist` off the built wheel: `numpy`
  and `python-dateutil` hard, `pyarrow` behind extras. Time zones must still resolve
  through stdlib `zoneinfo`, which is what the `tzdata` advice rests on.
- **The sizes and the reader/writer matrix.** Both are per-build facts: re-measure the
  wheels rather than scaling old figures, and read pandas' release notes for a moved
  engine.

### Coverage gaps

The three device tests cover a `to_csv` round-trip, the pyarrow-absent string storage, and
importing the Styler, tslibs and groupby submodules. They do not touch the readers and
writers the consumer matrix lists, `read_sql`, time zones (no `tzdata` in the test app),
the sizes, or the desktop-wheel comparison — and `DataFrame.style` is imported, not
rendered, so nothing exercises the template load that `extract_packages` exists for.

Coverage is also narrower per architecture than the build matrix suggests: the Android test
app is built `--arch x86_64` and iOS runs on the simulator, so `arm64-v8a` and
`armeabi-v7a` — the ABI the patch exists to keep alive — and real iOS hardware are
build-time green only.
