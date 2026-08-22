# pyarrow

[`pyarrow`](https://arrow.apache.org/docs/python/index.html) is the Python binding for Apache
Arrow: a columnar in-memory format, native readers and writers for CSV, JSON and Arrow's own
IPC/Feather files, and a library of compute kernels that run over whole columns instead of over
Python objects. In a Flet app that is what lets a file the app owns be parsed by C++ on the
device and then held column-wise, so a real dataset can be reshaped offline instead of being
shipped to a server to be aggregated.

What you do **not** get is the rest of Arrow. This wheel is built with every optional component
switched off: no Parquet, no Datasets, no Acero query engine, no cloud filesystems. If you came
here for `pq.read_table`, read [Things to know](#things-to-know) before you add the dependency —
that is the single most important thing on this page.

## Install

Add pyarrow to your `pyproject.toml`, and name the Android ABIs:

```toml
dependencies = [
    "flet",
    "pyarrow",
]

[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

The [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) line
is **required, not optional**, and leaving it out is a build failure rather than a runtime
surprise. `flet build apk` targets all three Android ABIs by default, there is no `armeabi-v7a`
pyarrow wheel on this index, and the resolve for that ABI takes the whole build down with it —
after the other two have already succeeded, which makes the error look like a fluke. The cause
is in Arrow's C++ package config: `ArrowConfigVersion.cmake` declares itself unsuitable unless
`sizeof(void*) == 8`, so a 32-bit pyarrow cannot link the Arrow C++ it needs, and 32-bit ARM is
the only 32-bit ABI Flet still supports. Write the ABI names out in full as above — `arm64` and
`x64` are the macOS spellings, and Flet rejects them here with
`Unsupported Android architecture`. The practical cost is old 32-bit handsets; 64-bit has been
mandatory for Play Store uploads since 2019. Wheels are published for Python 3.12, 3.13 and
3.14, on those two Android ABIs and on iOS for device and both simulator slices.

On iOS you need **Flet 0.86.0 or newer**. Flet relocates each of Arrow's C++ dylibs into its own
framework, and pyarrow finds them again through a marker file that only Flet 0.86 and later
leave behind; on an older Flet the app dies on `import pyarrow` with
`Library not loaded: @rpath/libarrow.dylib`. A bare `flet` dependency resolves to a current
release, so this matters mainly when another dependency or an application pin holds Flet below
0.86.0.

Add [`numpy`](../numpy) or [`pandas`](../pandas) to your own dependencies if you call
[`to_numpy()`](https://arrow.apache.org/docs/python/numpy.html) or
[`to_pandas()`](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html#pyarrow.Table.to_pandas);
both raise `ModuleNotFoundError` without them.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`csv-rollup`](examples/csv-rollup) — writes a CSV to app storage, parses it back with Arrow
  and totals it per city.

## Usage in a Flet app

Read a file the app owns, total it per key, and put the result on screen:

```python
table = csv.read_csv(os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.csv"))

rows = []
for city in pc.unique(table["city"]).to_pylist():
    amounts = table.filter(pc.equal(table["city"], city))["amount"]
    rows.append((city, len(amounts), pc.sum(amounts).as_py()))

view = ft.DataTable(
    columns=[ft.DataColumn(ft.Text(name)) for name in ("city", "orders", "total")],
    rows=[
        ft.DataRow(cells=[ft.DataCell(ft.Text(str(value))) for value in row])
        for row in rows
    ],
)
```

That loop is the group-by. `table.group_by("city").aggregate(...)` is the call you would reach
for on a desktop and it raises here, because grouped aggregation runs on Acero and Acero is not
in this build; the kernels it would have driven are all present, so
[`pc.unique`](https://arrow.apache.org/docs/python/generated/pyarrow.compute.unique.html) plus
one boolean mask per key does the same work. Pass masks and not expressions —
[`Table.filter`](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html#pyarrow.Table.filter)
accepts both, and an expression goes through Acero too.

### Storage

Arrow's readers and writers take ordinary filesystem paths, so what they produce belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From Flet
0.86.0 it is also the process working directory on device, so a bare relative filename lands
there; spelling it out costs one line and behaves the same on desktop:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.arrow")
feather.write_feather(table, path)
table = feather.read_table(path)
```

[Feather](https://arrow.apache.org/docs/python/feather.html) — Arrow's own IPC file format — is
the format to reach for here, because it is the one columnar format this build can write. It
writes **uncompressed** on both platforms:
[`write_feather`](https://arrow.apache.org/docs/python/generated/pyarrow.feather.write_feather.html)
uses LZ4 when a codec is available and falls back silently when none is, and neither of the two
codecs Feather accepts is compiled in here. Asking for `compression="lz4"` or `"zstd"`
explicitly raises rather than falling back, and files written this way still read anywhere.

Use
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose; neither is a place to keep the only copy of user data.

[`pa.fs.LocalFileSystem`](https://arrow.apache.org/docs/python/generated/pyarrow.fs.LocalFileSystem.html)
and `SubTreeFileSystem` work, and so do
[`pa.memory_map`](https://arrow.apache.org/docs/python/generated/pyarrow.memory_map.html) and
`pa.OSFile` for reading a large file without pulling all of it into memory. The remote
filesystems — S3, GCS, Azure and HDFS — are not in this build at all.

### Threading

**Arrow brings its own thread pool and uses it.** The CSV and JSON readers run multi-threaded by
default (`ReadOptions(use_threads=True)`) on both platforms, so parsing a file spreads across
cores without you asking.
[`pa.cpu_count()`](https://arrow.apache.org/docs/python/generated/pyarrow.cpu_count.html)
reports the pool Arrow built and
[`pa.set_cpu_count()`](https://arrow.apache.org/docs/python/generated/pyarrow.set_cpu_count.html)
resizes it; the initial size is taken from `OMP_NUM_THREADS` / `OMP_THREAD_LIMIT` if either is
set and from the hardware otherwise. There is a separate I/O pool, sized by `ARROW_IO_THREADS`
and reported by
[`pa.io_thread_count()`](https://arrow.apache.org/docs/python/generated/pyarrow.io_thread_count.html).
No OpenMP runtime is linked — those two variables are read as hints, nothing more.

What you do not get is parallelism *across* a query, because the engine that would provide it is
[Acero](https://arrow.apache.org/docs/cpp/acero/overview.html) and Acero is not in this build.
The concurrency here is inside one reader or one kernel.

Either way it is not asynchronous: a read blocks the thread that called it however many workers
it is using, so on the UI thread it freezes the UI. Push it to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end the
handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does not
reach background threads. Arrow imposes no thread rules of its own: tables and arrays are
immutable and move between threads freely, and there is no connection or handle to serialise.

### Compression and codecs

**No compression codec is compiled in on Android, and iOS has only gzip.**
[`pa.Codec.is_available`](https://arrow.apache.org/docs/python/generated/pyarrow.Codec.html#pyarrow.Codec.is_available)
answers `False` for zstd, lz4, snappy, brotli and bz2 on both platforms, and `False` for gzip on
Android as well. The gzip that iOS does have is not a decision: Arrow's vendored `date` library
decompresses the system time-zone database with zlib on Apple platforms, so `libarrow` links the
SDK's `libz` and the codec arrives as a side effect.

What that costs you is reading compressed files, because Arrow's readers detect compression from
the *file extension*: `csv.read_csv("orders.csv.gz")` fails with
`Support for codec 'gzip' not built` on Android where the same call succeeds on iOS. Do not
build a file format on that difference. Name the file `.csv` and it is read as plain text on
both platforms; compressing with the stdlib
[`gzip`](https://docs.python.org/3/library/gzip.html) module works everywhere and simply moves
the work from Arrow to Python.

### Time zones

Zone conversions *inside* Arrow need no help and no extra package. Arrow's C++ carries its own
time-zone code and reads the platform's database directly — `/apex/com.android.tzdata/etc/tz` on
Android, CoreFoundation on iOS — so
[`pc.assume_timezone`](https://arrow.apache.org/docs/python/generated/pyarrow.compute.assume_timezone.html)
and casts between zone-aware timestamps behave as they do on a desktop, unlike
[`pandas`](../pandas) and [`polars`](../polars), which resolve named zones through Python.

The Python boundary is the exception. `.as_py()` on a zone-aware timestamp builds a `datetime`
through the stdlib [`zoneinfo`](https://docs.python.org/3/library/zoneinfo.html), which looks for
a directory of IANA files that Android does not have — the OS keeps its database in a
bionic-specific format Python cannot read — so the call raises
`ZoneInfoNotFoundError: 'No time zone found with key …'`. If you cross that boundary, add
`tzdata` — a pure-Python wheel of about 340 KB that `zoneinfo` finds with no configuration:

```toml
dependencies = ["flet", "pyarrow", "tzdata"]
```

Keep the values inside Arrow and you need nothing at all.

### App size

pyarrow is the small half of what gets installed. Expect roughly 11–12 MB of compressed wheel
and 46–49 MB unpacked per architecture across the two wheels, of which about 39–42 MB survives
Flet's default [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) — it
strips the C++ headers they carry between them. Almost all of that remainder is Arrow's own
shared libraries, around 26 MB on arm64-v8a, so there is little left to trim. The one item worth
naming is pyarrow's test suite, roughly 2.5 MB, which the package imports and runs without:

```toml
[tool.flet.cleanup]
package_files = ["pyarrow/tests"]
```

On Android that payload lands once per ABI, and the two ABIs the Install snippet names are
already the floor here — there is no third one to drop. An app bundle or
[split APKs](https://flet.dev/docs/publish/android/#split-apk-per-abi) are the remaining lever.
These figures are decimal and describe the package payload rather than the amount added to the
final APK or IPA — and re-measuring with `du`, which reports binary units, turns 42 MB into
40 M and reads as a saving that is not there.

### Other considerations

A desktop `flet run` resolves PyPI's pyarrow, which is the complete build — Parquet, Datasets,
Acero, the cloud filesystems and the regex and Unicode string kernels all included. So
`pq.read_table`, `table.group_by(...).aggregate(...)`, `Table.join` and `fs.S3FileSystem` work
on your machine and fail on the device, `pc.utf8_upper` is registered there and not here, and a
`.csv.gz` reads under `flet run` and on iOS but not on Android. Every component this page says
is missing is therefore a desktop/mobile divergence: validate anything that touches one on a
device or emulator/simulator rather than under `flet run`.

The Python layer itself is upstream's own. The only file this recipe changes is
`pyarrow/__init__.py`, which gains the iOS preload shim, so upstream's documentation applies
unchanged and anything you read about pyarrow is true here unless it needs one of those
components.

## Things to know

- **Everything optional is compiled out, and each removal costs a named import failure rather
  than a silent wrong answer:**

  | switched off | what stops working | what you get |
  | --- | --- | --- |
  | Parquet | [`pq.read_table`](https://arrow.apache.org/docs/python/parquet.html), `pq.write_table`, all of `pyarrow.parquet` | `ImportError: The pyarrow installation is not built with support for the Parquet file format` |
  | Dataset | [`ds.dataset`](https://arrow.apache.org/docs/python/dataset.html), partitioned directory reads, `write_dataset` | `ImportError: … not built with support for 'dataset'` |
  | Acero | `Table.group_by(...).aggregate(...)`, [`Table.join`](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html#pyarrow.Table.join), `join_asof`, `Table.filter(<expression>)` | `ImportError: … not built with support for 'acero'` |
  | Substrait, Flight | `pyarrow.substrait`, `pyarrow.flight` | `ImportError: … not built with support for 'substrait'` / `'flight'` |
  | ORC | `pyarrow.orc` | `ModuleNotFoundError: No module named 'pyarrow._orc'` |
  | S3, GCS, Azure, HDFS | `fs.S3FileSystem` and the other three | `ImportError: The pyarrow installation is not built with support for 'S3FileSystem'` |
  | CUDA | `pyarrow.cuda` | `ModuleNotFoundError: No module named 'pyarrow._cuda'` |

  What remains is the core: arrays, tables, record batches, schemas and types; the compute
  kernels; the CSV, JSON, IPC and Feather readers and writers; and the local filesystem. That is
  enough for the job most apps actually want — parse a file, reshape it, show it — and not
  enough for anything that treats Arrow as a query engine.
- **Grouped aggregation and joins are the removal you will hit first.** They look like plain
  Arrow and they are not: `.aggregate()` on a
  [`group_by`](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html#pyarrow.Table.group_by),
  `join`, `join_asof` and `Table.filter` with an
  [expression](https://arrow.apache.org/docs/python/generated/pyarrow.compute.field.html) each
  import `pyarrow.acero` lazily and raise at that point — `group_by(...)` on its own does not,
  so the failure arrives one call later than you expect. The kernels themselves are present, the
  `hash_sum` family included; there is simply no engine to drive them. Doing it by hand is short,
  as the snippet above and the [`csv-rollup`](examples/csv-rollup) example both show:
  `table.filter(pc.equal(table["city"], "Lagos"))` works where
  `table.filter(pc.field("city") == "Lagos")` does not. If you want a real query engine on a
  phone, [`polars`](../polars) is the recipe to look at.
- **Parquet is not available, and installing pyarrow does not change that.** There is no
  `_parquet` extension in this wheel and `fastparquet` has no mobile wheel either, so
  `pandas.to_parquet` raises `ImportError: Unable to find a usable engine` whatever you install —
  [`pandas`](../pandas) covers the same limit from the DataFrame side. Feather is the columnar
  file format you have instead: it is Arrow IPC on disk, it keeps the schema, and pandas can use
  it once pyarrow is installed. It is bigger than the Parquet you wanted, because nothing here
  can compress it.
- **The only filesystem is the local one.** `fs.S3FileSystem`, `GcsFileSystem`,
  `HadoopFileSystem` and `AzureFileSystem` are absent, and `pyarrow.fs` reports them through a
  module-level `__getattr__` — so they fail on *attribute access*, not on `import pyarrow.fs`,
  with `ImportError: The pyarrow installation is not built with support for 'S3FileSystem'`.
  `fsspec` has no mobile wheel either. Fetch the bytes yourself and hand Arrow a
  `pa.BufferReader`.
- **The string kernels that need re2 or utf8proc are gone.** Arrow is built without both, which
  removes all eight regex kernels — `match_substring_regex`, `extract_regex`,
  `replace_substring_regex`, `match_like` and the rest — and twenty Unicode-aware ones: every
  `utf8_is_*` predicate, the case conversions (`utf8_upper`, `utf8_lower`, `utf8_title`,
  `utf8_capitalize`, `utf8_swapcase`), `utf8_normalize`, the `utf8_*trim_whitespace` family and
  `utf8_split_whitespace`. Every `ascii_*` equivalent survives, as do the literal-match kernels
  (`match_substring`, `starts_with`, `replace_substring`, `split_pattern`, `count_substring`) and
  the `utf8_*` kernels that do not case-fold (`utf8_length`, `utf8_slice_codeunits`, `utf8_reverse`, `utf8_trim`, `utf8_lpad`), plus `ends_with` (`utf8_length`, `utf8_slice_codeunits`,
  `utf8_reverse`, `utf8_trim`). For anything genuinely Unicode, pull the column out with
  `to_pylist()` and use Python's `re` and `str` methods; you lose the kernel speed, not the
  answer.

## Build notes (maintainers)

### Recipe shape

Arrow C++ lives in its own `flet-libarrow` recipe, depended on as `requirements.host` and not as
`host_build`, and getting the libraries onto the device is the whole reason. `host_build` puts a
dependency in the cross environment for the link and then does not ship it, which leaves the app
with extension modules and nothing to load; bundling the dylibs inside the pyarrow wheel instead
— the approach this recipe used before — does not help either, because the relocation that turns
them into per-slice iOS frameworks only looks at `opt/lib`. Shipping them as an ordinary runtime
dependency's `opt/lib` is what makes both platforms pick them up: Android's `jniLibs` on one
side, framework relocation on the other. `flet-libcpp-shared` rides along on Android for the
related reason that both sets of binaries are C++ and need the NDK runtime; iOS uses the system
libc++.

The component set is a floor, not a preference. pyarrow builds seven Cython modules
unconditionally and `FATAL_ERROR`s unless Arrow C++ was built with `ARROW_COMPUTE` and
`ARROW_CSV`, and cannot link `_json`, `_fs` and `_feather` without `ARROW_JSON`,
`ARROW_FILESYSTEM` and `ARROW_IPC`. Everything above that line is switched off twice over — by
Arrow's own flags in `flet-libarrow` and again by pyarrow's `PYARROW_WITH_*` environment
overrides here — so that a change on one side cannot quietly switch a component on from the
other.

### Upgrade hazards

- **`flet-libarrow` moves in lockstep.** It is pinned with `==` because the extension modules
  link a SONAME carrying the Arrow major version; bump both recipes in the same commit and
  rebuild both, or the wheel ends up naming a library nothing on the device provides.
- **The double switch-off only holds while the option names hold.** `PYARROW_WITH_*` binds to
  pyarrow's `define_option` macro, so if upstream renames or drops one of those variables the
  override silently stops applying and Arrow's own flags become the only gate. Check a renamed
  or new component against the built wheel, not against `meta.yaml`.

### Re-verification checklist

- **The component list, from the wheel rather than from the flags.** List the `.so`/`.dylib`
  files in the built wheel and check the count is still seven with the same names. A new
  unconditional Cython module upstream shows up as a build failure demanding another Arrow
  component; an optional one that starts building anyway shows up as nothing at all, and the
  consumer table above quietly becomes wrong in the direction users notice least.
- **The exact `ImportError` strings.** They are upstream's, from `try/except ImportError` blocks
  in `pyarrow/dataset.py`, `acero.py`, `flight.py`, `substrait.py`, `parquet/core.py` and the
  `__getattr__` in `fs.py`, and upstream rewords them between releases. The recipe's tests cover
  the modules that *do* import, not these.
- **`armeabi-v7a`, and whether it is still excluded.** The exclusion is Arrow's 32/64-bit
  `find_package` gate, not a pyarrow limitation, so an Arrow release that drops the gate would
  make a 32-bit build possible — and the required `target_arch` snippet, the loudest thing on
  this page, would stop being required. Check the built index really has no `armeabi_v7a` file
  before repeating the claim.
- **The codec asymmetry.** That iOS has gzip and Android has nothing is visible in the linkage —
  iOS `libarrow.dylib` loads `/usr/lib/libz.1.dylib`, Android `libarrow.so` has no `libz` in
  `DT_NEEDED` — and an upstream change to how the vendored `date` library reads the system tzdata
  would flip it.
- **The missing compute kernels.** Twenty-eight of them, all downstream of `ARROW_WITH_RE2=OFF`
  and `ARROW_WITH_UTF8PROC=OFF`. Re-derive the list from the shipped binaries against a desktop
  wheel rather than editing the old one; Arrow adds kernels every release and moves them between
  `libarrow` and `libarrow_compute`.
- **The iOS preload shim, and the Flet floor that follows from it.** The shim works because Flet
  leaves a `.fwork` marker where it moved each `opt/lib` dylib, which is a serious-python
  behaviour rather than a pyarrow one — so the minimum Flet version stated in Install is really a
  claim about which serious-python the current Flet bundles, and wants re-checking whenever
  either moves. If Flet ever rewrites the extension modules' load commands to point at the
  frameworks directly, the shim becomes dead code and the floor goes with it.
- **Android package layout.** Test from zipped site-packages. Two places in pyarrow build a path
  from `__file__` — `get_include()` and `get_library_dirs()`, both for compiling C extensions
  against pyarrow and never reached in an app — and the preload shim's probe finds nothing inside
  the zip and moves on, which is why consumer guidance carries no `extract_packages` entry. Add
  one only if a real runtime filesystem read makes it mandatory, and include the failure symptom.
- **The sizes and the file-by-file comparison.** Both are measured from the published wheels: the
  compressed and unpacked ranges, the headers cleanup removes, the `pyarrow/tests` figure, and
  the claim that every Python file except `pyarrow/__init__.py` matches the desktop wheel of the
  same version and that both platforms ship the same file set. Re-measure; do not scale.

### Coverage gaps

The device tests cover arrays and tables, schemas and record batches, an IPC round-trip through
memory buffers, and the arithmetic, comparison and aggregate compute kernels. They do not touch
the CSV or JSON readers, Feather, the local filesystem, `memory_map`, codec availability, time
zones, or any of the `ImportError` strings above — the [`csv-rollup`](examples/csv-rollup)
example is the only device evidence for the CSV path and the codec probe, and everything else is
inspection of the wheel. The iOS preload path is covered only by `import pyarrow` succeeding,
which does not distinguish loading from `opt/lib` from following a `.fwork` marker.
