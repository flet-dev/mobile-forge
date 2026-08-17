# pyarrow

[`pyarrow`](https://arrow.apache.org/docs/python/index.html) is the Python binding for Apache
Arrow: a columnar in-memory format, native readers and writers for CSV, JSON and Arrow's own
IPC/Feather files, and a library of compute kernels that run over columns instead of over
Python objects. On mobile that is worth having for one reason above the rest — a file the app
owns can be parsed by C++ at native speed and then held column-wise, so a hundred thousand rows
cost a few megabytes and a few milliseconds instead of a hundred thousand Python objects.

What you do **not** get is the rest of Arrow. This wheel is built with every optional component
switched off: no Parquet, no Datasets, no Acero query engine, no cloud filesystems. If you came
here for `pq.read_table`, read [Things to know](#things-to-know) before you add the dependency —
that is the single most important thing on this page.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pyarrow",
]

[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

The
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
line is **required, not optional**, and leaving it out is a build failure rather than a runtime
surprise. `flet build apk` targets all three Android ABIs by default, there is no
`armeabi-v7a` pyarrow wheel on this index, and the resolve for that ABI takes the whole build
down with it — after the other two have already succeeded, which makes the error look like a
fluke. The cause is in Arrow's C++ package config: `ArrowConfigVersion.cmake` declares itself
unsuitable unless `sizeof(void*) == 8`, so a 32-bit pyarrow cannot link the Arrow C++ it
needs, and 32-bit ARM is the only 32-bit ABI Flet still supports. Write the ABI names out in
full as above — `arm64` and `x64` are the macOS spellings and Flet rejects them here with
`Unsupported Android architecture`. The practical cost is old 32-bit handsets; 64-bit has been
mandatory for Play Store uploads since 2019.

On iOS you need **Flet 0.86.0 or newer**. Flet relocates each of Arrow's C++ dylibs into its own
framework, and pyarrow finds them again through a marker file that only Flet 0.86 and later
leave behind; on an older Flet the app dies on `import pyarrow` with
`Library not loaded: @rpath/libarrow.dylib`. See [iOS notes](#ios-notes).

What comes along is `flet-libarrow`, which carries the Arrow C++ libraries the extension modules
link against, plus `flet-libcpp-shared` on Android — the NDK C++ runtime. Neither needs
configuring, and both are large; see the size bullet in [Things to know](#things-to-know). The
list ends there. The wheel's `Requires-Dist` names nothing else, so **`numpy` and `pandas` are
not installed for you**: add them yourself if you call
[`to_numpy()`](https://arrow.apache.org/docs/python/numpy.html) or
[`to_pandas()`](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html#pyarrow.Table.to_pandas),
which raise `ModuleNotFoundError` without them.

No [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
needed. Two places in pyarrow build a path from `__file__` — `get_include()` and
`get_library_dirs()`, which exist for compiling C extensions against pyarrow and are never
reached in an app — and the iOS preload shim probes for the Arrow dylibs beside the package,
which on Android finds nothing inside the zipped site-packages and moves on, because the
libraries it would have wanted are already in the APK's `jniLibs`.

Builds for Python 3.12, 3.13 and 3.14, on Android arm64-v8a and x86_64 and on iOS for device
and both simulator slices.

## Storage

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
uses LZ4 when a codec is available and silently falls back when none is, and neither of the two
codecs Feather accepts is compiled in here. Asking for `compression="lz4"` or `"zstd"`
explicitly fails rather than falling back, and files written this way still read anywhere. Use
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose; neither is a place to keep the only copy of user data.

[`pa.fs.LocalFileSystem`](https://arrow.apache.org/docs/python/generated/pyarrow.fs.LocalFileSystem.html)
and `SubTreeFileSystem` work, and so do
[`pa.memory_map`](https://arrow.apache.org/docs/python/generated/pyarrow.memory_map.html) and
`pa.OSFile` for reading a large file without pulling it all into memory. The remote filesystems
do not — see [Things to know](#things-to-know).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`csv-rollup`](examples/csv-rollup) — writes a CSV to app storage, parses it back with Arrow and totals it per city.

## Threading

**Arrow brings its own thread pool and uses it.** The shipped `libarrow` imports
`pthread_create` on both platforms, and the CSV and JSON readers run multi-threaded by default
(`ReadOptions(use_threads=True)`), so parsing a file spreads across cores without you asking.
[`pa.cpu_count()`](https://arrow.apache.org/docs/python/generated/pyarrow.cpu_count.html)
reports the pool Arrow built and
[`pa.set_cpu_count()`](https://arrow.apache.org/docs/python/generated/pyarrow.set_cpu_count.html)
resizes it; the initial size is taken from `OMP_NUM_THREADS` / `OMP_THREAD_LIMIT` if either is
set and from the hardware otherwise. There is a separate I/O pool, sized by `ARROW_IO_THREADS`
and reported by
[`pa.io_thread_count()`](https://arrow.apache.org/docs/python/generated/pyarrow.io_thread_count.html).
No OpenMP runtime is linked — those two variables are read as hints, nothing more.

What you do not get is parallelism *across* a query, because the engine that would provide it
is [Acero](https://arrow.apache.org/docs/cpp/acero/overview.html) and Acero is not in this
build. The concurrency here is inside one reader or one kernel.

Either way it is not asynchronous: a read blocks the thread that called it however many workers
it is using, so on the UI thread it freezes the UI. Push it to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end the
handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does not
reach background threads. Arrow imposes no thread rules of its own: tables and arrays are
immutable and move between threads freely, and there is no connection or handle to serialise.

## Android notes

**No compression codec is compiled in at all**, and that is the one functional difference
between the two mobile platforms — iOS has gzip.
[`pa.Codec.is_available`](https://arrow.apache.org/docs/python/generated/pyarrow.Codec.html#pyarrow.Codec.is_available)
answers `False` here for gzip, zstd, lz4, snappy, brotli and bz2 alike. What it costs you is
reading compressed files, because Arrow's readers detect compression from the *file extension*:
`csv.read_csv("orders.csv.gz")` fails with `Support for codec 'gzip' not built` where the same
call succeeds on iOS. Name the file `.csv` and it is read as plain text on both platforms;
compressing with the stdlib `gzip` module works everywhere and simply moves the work from Arrow
to Python.

Time zones need no help. Arrow's C++ reads Android's own database directly from
`/apex/com.android.tzdata/etc/tz`, so
[`pc.assume_timezone`](https://arrow.apache.org/docs/python/generated/pyarrow.compute.assume_timezone.html)
and casts between zone-aware timestamps work with no `tzdata` package installed — unlike
[`pandas`](../pandas) and [`polars`](../polars), which both need it. The Python boundary is the
exception; see the time-zone bullet in [Things to know](#things-to-know).

Arrow's C++ libraries ride into the APK as `jniLibs` and resolve by soname, which is why no
`extract_packages` entry is needed for them.

## iOS notes

**pyarrow patches its own `__init__.py` to preload the Arrow C++ dylibs, and that is what makes
`import pyarrow` work.** The extension modules link `libarrow`, `libarrow_compute` and
`libarrow_python` through `@rpath`, but nothing on their run-path resolves those names on
device — the only absolute entry left in the binary points at the build machine. So the shim
loads the three dylibs with `RTLD_GLOBAL` first, in dependency order, and dyld then binds each
`@rpath` reference to the image already in memory. It finds them either in `opt/lib` or by
following the `.fwork` marker Flet leaves when it has relocated a dylib into a framework. That
marker is why **Flet 0.86.0 is the floor on iOS**: earlier versions move the dylibs without
leaving one, and the app fails at import with `Library not loaded: @rpath/libarrow.dylib`.

The gzip codec *is* available here, unlike on Android. Not by design: Arrow's vendored
date library decompresses the system time-zone database with zlib on Apple platforms, so
`libarrow` links the SDK's `libz` and `Codec.is_available("gzip")` comes back `True` as a side
effect. `.csv.gz` therefore reads on iOS and not on Android — do not build a file format on
that difference. zstd, lz4, snappy, brotli and bz2 are unavailable on both.

## Things to know

- **What is actually in this wheel.** Seven extension modules, against the desktop wheel's
  twenty-one: `lib`, `_compute`, `_csv`, `_feather`, `_fs`, `_json` and `_pyarrow_cpp_tests`.
  Those are the ones pyarrow has no switch for — everything optional is compiled out, and each
  removal costs you a named import failure rather than a silent wrong answer:

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
  kernels; the CSV, JSON, IPC and Feather readers and writers; and the local filesystem. That
  is enough for the job most apps actually want — parse a file, reshape it, show it — and not
  enough for anything that treats Arrow as a query engine.
- **Grouped aggregation and joins are the removal you will hit first.** They look like plain
  Arrow and they are not: `.aggregate()` on a
  [`group_by`](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html#pyarrow.Table.group_by),
  `join`, `join_asof` and `Table.filter` with an
  [expression](https://arrow.apache.org/docs/python/generated/pyarrow.compute.field.html) each
  import `pyarrow.acero` lazily and raise at that point — `group_by(...)` on its own does not,
  so the failure arrives one call later than you expect. The kernels themselves are present, the
  `hash_sum` family included; there is simply no engine to drive them. Doing it by hand is
  short: `pc.unique` for the distinct keys, then one boolean mask per key and the scalar
  aggregates over what it selects. The [`csv-rollup`](examples/csv-rollup) example does exactly
  that. Pass masks, not expressions — `table.filter(pc.equal(table["city"], "Lagos"))` works,
  `table.filter(pc.field("city") == "Lagos")` does not. If you want a real query engine on a
  phone, [`polars`](../polars) is the recipe to look at.
- **Parquet is not available, and installing pyarrow does not change that.** There is no
  `_parquet` extension in this wheel and `fastparquet` has no mobile wheel either, so
  `pandas.to_parquet` raises `ImportError: Unable to find a usable engine` whatever you install
  — the [`pandas`](../pandas) page says the same thing from the other side. Feather is the
  columnar file format you have instead: it is Arrow IPC on disk, reads and writes at full
  speed, keeps the schema, and pandas can use it once pyarrow is installed. It is bigger than
  the Parquet you wanted, because nothing here can compress it.
- **The only filesystem is the local one.** `fs.S3FileSystem`, `GcsFileSystem`,
  `HadoopFileSystem` and `AzureFileSystem` are absent, and `pyarrow.fs` reports them through a
  module-level `__getattr__` — so they fail on *attribute access*, not on `import pyarrow.fs`,
  with `ImportError: The pyarrow installation is not built with support for 'S3FileSystem'`.
  `fsspec` has no mobile wheel either. Fetch the bytes yourself and hand Arrow a
  `pa.BufferReader`.
- **The string kernels that need re2 or utf8proc are gone.** Arrow is built without both, which
  removes eight regex kernels (`match_substring_regex`, `extract_regex`, `replace_substring_regex`,
  `split_pattern_regex`, `count_substring_regex`, `find_substring_regex`, `extract_regex_span`,
  `match_like`) and twenty Unicode-aware ones — every `utf8_is_*` predicate plus `utf8_upper`,
  `utf8_lower`, `utf8_title`, `utf8_capitalize`, `utf8_swapcase`, `utf8_normalize`, the
  `utf8_*trim_whitespace` family and `utf8_split_whitespace`. The `ascii_*` equivalents all
  survive, as do the literal-match kernels (`match_substring`, `starts_with`, `ends_with`,
  `replace_substring`, `split_pattern`, `count_substring`) and the non-case `utf8_*` kernels
  (`utf8_length`, `utf8_slice_codeunits`, `utf8_reverse`, `utf8_trim`, `utf8_lpad`). For
  anything genuinely Unicode, pull the column out with `to_pylist()` and use Python's `re` and
  `str` methods; you lose the kernel speed, not the answer.
- **Time zones work in Arrow and stop at the Python boundary.** Arrow's C++ carries its own
  time-zone code and reads the platform's database — CoreFoundation on iOS, the bionic tzdata
  files on Android — so zone conversions inside Arrow need no `tzdata` package. Converting a
  zone-aware timestamp *back into a Python `datetime`* is the part that goes through the stdlib
  `zoneinfo`, and Android ships no IANA directory that `zoneinfo` can read, so expect the same
  failure [`pandas`](../pandas) and [`polars`](../polars) describe. Add `tzdata` — a ~350 KB
  pure-Python wheel from PyPI — if you call `.as_py()` on zone-aware timestamps, and nothing at
  all if you keep the values in Arrow.
- **Size: pyarrow is the small half.** The wheel is modest and `flet-libarrow` is not, and both
  are per-architecture:

  | slice | pyarrow, download → unpacked | flet-libarrow, download → unpacked | installed, after cleanup |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 4.3 MB → 16.0 MB | 7.2 MB → 29.9 MB | 39.1 MB |
  | Android x86_64 | 4.5 MB → 16.2 MB | 7.9 MB → 32.7 MB | 42.1 MB |
  | iOS arm64 (device) | 4.2 MB → 16.6 MB | 6.5 MB → 31.2 MB | 41.1 MB |

  The last column is what survives Flet's default
  [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup), which strips the
  7.2 MB of C++ headers the two wheels carry between them; almost all of the remainder is the
  two Arrow shared libraries (26.4 MB on arm64-v8a). You can take another 2.4 MB off with
  `[tool.flet.cleanup] package_files = ["pyarrow/tests"]` — pyarrow imports and runs without
  its test suite. There is nothing else to trim: the C++ is the package.
- **The Python half is the desktop package, byte for byte.** Compared file by file against the
  PyPI wheel of the same version, 104 of the 105 Python files are identical; the 105th is
  `pyarrow/__init__.py`, which carries the iOS preload shim. Android and iOS ship exactly the
  same 583 files as each other. So upstream's documentation applies unchanged, and anything you
  read about pyarrow is true here unless it needs one of the components listed above.

## Build notes (maintainers)

The two patches explain themselves in their preambles and every build flag is justified in
`meta.yaml` next to it, so this section is what neither file records.

**Arrow C++ lives in its own `flet-libarrow` recipe, depended on as `requirements.host` and not
as `host_build`, and getting the libraries onto the device is the whole reason.** `host_build`
puts a dependency in the cross environment for the link and then does not ship it, which leaves
the app with extension modules and nothing to load; bundling the dylibs inside the pyarrow wheel
instead — the approach this recipe used before — does not help either, because the relocation
that turns them into per-slice iOS frameworks only looks at `opt/lib`. Shipping them as an
ordinary runtime dependency's `opt/lib` is what makes both platforms pick them up: Android's
`jniLibs` on one side, framework relocation on the other.

The component set is a floor, not a preference. pyarrow 24 builds seven Cython modules
unconditionally and `FATAL_ERROR`s unless Arrow C++ was built with `ARROW_COMPUTE` and
`ARROW_CSV`, and cannot link `_json`/`_fs`/`_feather` without `ARROW_JSON`, `ARROW_FILESYSTEM`
and `ARROW_IPC`. Everything above that line is switched off twice over — by Arrow's own flags in
`build.sh` and again by pyarrow's `PYARROW_WITH_*` environment overrides in `meta.yaml`. That
duplication is deliberate: the environment wins over whatever the Arrow build happened to
enable, so a change on one side cannot quietly switch a component on from the other.

What to re-verify on a bump, in rough order of how quietly it can go wrong:

- **The component list, from the wheel rather than from the flags.** List the `.so`/`.dylib`
  files in the built wheel and check the count is still seven with the same names. A new
  unconditional Cython module upstream would appear as a build failure demanding another Arrow
  component; an optional one that starts building anyway would appear as nothing at all, and
  the table in [Things to know](#things-to-know) would quietly become wrong in the direction
  users notice least.
- **The exact `ImportError` strings.** They are upstream's, produced by `try/except ImportError`
  blocks in `pyarrow/dataset.py`, `acero.py`, `flight.py`, `substrait.py`, `parquet/core.py` and
  the `__getattr__` in `fs.py`. The table quotes them verbatim, and upstream rewords them
  between releases. The recipe's tests cover the modules that *do* import, not these.
- **`armeabi-v7a`, and whether it is still excluded.** The exclusion is Arrow's 32/64-bit
  `find_package` gate, not a pyarrow limitation, so an Arrow release that drops the gate would
  make a 32-bit build possible — and the required `target_arch` snippet in
  [Install](#install), which is the loudest thing on this page, would stop being required.
  Check the built index actually has no `armeabi_v7a` file before repeating the claim.
- **The codec asymmetry.** That iOS has gzip and Android has nothing is a side effect of Arrow
  force-enabling zlib on Apple for its vendored `date` library, not a decision. It is visible
  in the linkage — iOS `libarrow.dylib` loads `/usr/lib/libz.1.dylib`, Android `libarrow.so`
  has no `libz` in `DT_NEEDED` — and an upstream change to how `date` reads the system tzdata
  would flip it. Both [Android notes](#android-notes) and [iOS notes](#ios-notes) rest on it.
- **The missing compute kernels.** Twenty-eight of them, all downstream of
  `ARROW_WITH_RE2=OFF` and `ARROW_WITH_UTF8PROC=OFF`. Re-derive the list from the shipped
  binaries against a desktop wheel of the same version rather than editing the old one; Arrow
  adds kernels every release and moves them between `libarrow` and `libarrow_compute`.
- **The iOS preload shim, and the Flet floor that follows from it.** The shim works because
  Flet leaves a `.fwork` marker where it moved each `opt/lib` dylib, which is a
  serious-python behaviour, not a pyarrow one — so the version stated in [Install](#install) is
  really a claim about which serious-python the current Flet bundles, and wants re-checking
  whenever either moves. If Flet ever rewrites the extension modules' load commands to point at
  the frameworks directly, the shim becomes dead code and the floor goes with it.
- **The sizes and the file-by-file comparison.** Both are measured from the published wheels —
  the per-architecture table, the 7.2 MB of headers cleanup removes, the 2.4 MB `pyarrow/tests`,
  and the claim that 104 of 105 Python files match the desktop wheel. Re-measure; do not scale.
