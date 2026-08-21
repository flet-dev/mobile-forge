# srsly

[`srsly`](https://github.com/explosion/srsly) is the serialisation layer Explosion wrote for
spaCy and then published on its own: one API over JSON, JSONL, msgpack, pickle and YAML, with
`*_dumps`/`*_loads` pairs for values in memory and `read_*`/`write_*` pairs that take a path
and own the file handle. Most readers meet it because something in the spaCy stack brought it
along. What it offers is that consistent surface across five formats — plus one thing worth
knowing before you debug a serialisation difference: it **vendors its own copies** of the
libraries underneath, so its msgpack is not the `msgpack` wheel you may also have installed,
and its JSON is a decade older than the one on PyPI.

## Install

Add srsly to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "srsly",
]
```

Every `read_*`/`write_*` function accepts a `str` or a `pathlib.Path`. The in-memory pairs
cover JSON, msgpack, pickle and YAML — JSONL and the gzip variants are file-only — and work on
`str` for JSON and YAML and on `bytes` for msgpack and pickle. `msgpack_dumps` additionally
accepts numpy arrays and scalars anywhere inside the object.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`serial-toolbox`](examples/serial-toolbox) — sends one record set through every format
  srsly bundles and reports size, timing and whether the round trip was exact.

## Usage in a Flet app

The two calls that do the job, and the file pair that puts the same object on disk:

```python
import os

import flet as ft
import srsly

blob = srsly.msgpack_dumps({"label": "v3", "weights": [0.1, 0.2, 0.3]})
state = srsly.msgpack_loads(blob)

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "state.msgpack")
srsly.write_msgpack(path, state)
caption = ft.Text(srsly.json_dumps(srsly.read_msgpack(path)))
```

### Storage

Put anything the user expects to keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
as above; [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
holds anything regenerable and [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
scratch files. A corpus or config shipped with the app is an asset: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and resolve it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

For a growing log of records, the line-delimited pair fits best:
[`write_jsonl`](https://github.com/explosion/srsly#function-srslywrite_jsonl) takes
`append=True`, and [`read_jsonl`](https://github.com/explosion/srsly#function-srslyread_jsonl)
yields one record at a time instead of building the whole list. Compression pays on this shape
of data: the 1000 records the example generates measured 121.2 kB through `write_jsonl` against
8.0 kB through
[`write_gzip_jsonl`](https://github.com/explosion/srsly#function-srslywrite_gzip_jsonl).

### Threading

Serialising a large object is CPU work on the calling thread, so move it into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch
exceptions inside the worker, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). YAML forces the
issue: it is a pure-Python parser, and 1000 of those same records took about 114 ms to write
and about 242 ms to read on a desktop machine, against 0.3 ms and 0.5 ms for msgpack. A phone
is slower.

`msgpack_loads` and `read_msgpack` switch the cyclic garbage collector off around the unpack,
and that is process-global: it is off for the whole app while a background unpack runs, and
stays off if that unpack raises — see **Things to know**.

### Precision

**srsly's JSON is not a drop-in for the standard library's: it loses float precision in both
directions, and how much depends on magnitude.** `json_dumps` is
[ujson](https://github.com/ultrajson/ultrajson) **1.35**, a 2016 release frozen inside the
package, whose `double_precision` counts digits *after the decimal point*, defaults to ten, and
never falls back to exponent notation. A large number can survive intact while a small one is
destroyed:

| value | `srsly.json_dumps` |
| --- | --- |
| `123456789.01234567` | `123456789.0123456717` — reads back exactly |
| `0.8444218515250481` | `0.8444218515` |
| `1.2345678901234567e-11` | `0.0` |

Anything below about `5e-11` becomes zero, silently. Of 1000 values from `random.random()`
(seed 0), **none** survived `srsly.json_dumps` → `srsly.json_loads` on desktop, against all
1000 through `json.dumps` → `json.loads`; and the parser loses independently of the writer,
keeping 81 of that same 1000 when the text came from `json.dumps`. Raising
`srsly.ujson.dumps(..., double_precision=...)` lifts the ceiling to fifteen places and no
further — 79 then survive, and everything under `5e-11` is still a zero.

If the numbers matter, use msgpack or pickle, which carry a double as eight bytes and round
trip exactly, or the standard library's `json` on both sides. Three smaller surprises in the
same function: `json_dumps(value, sort_keys=True)` hands the work to the standard library's
`json` rather than ujson, making one call lossless and the other lossy; `nan` and `inf` raise
`OverflowError` where `json.dumps` emits `NaN` and `Infinity`; and an integer of `2 ** 64` or
more raises `OverflowError: int too big to convert`. None of this describes today's ultrajson,
which round-trips all 1000. It describes the copy srsly froze.

### App size

Expect approximately 0.63–0.66 MB of compressed wheel and 3.1–3.5 MB unpacked per
architecture. Most of that never runs: of the 3.21 MB in the Android arm64 payload, 1.90 MB is
the C, C++ and Cython source the extensions were generated from, and
[`cleanup.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup) defaults on and
deletes every bit of it — 3.21 MB down to 1.30 MB with nothing configured. What survives is
upstream's own 0.43 MB test suite, and that is the one worth naming yourself:

```toml
[tool.flet.cleanup]
package_files = ["srsly/tests"]
```

That takes the same tree to 0.88 MB — near what lands on the device, not exactly it, since
`compile.packages` is on too and replaces the remaining `.py` files with `.pyc`. A glob that
matches nothing simply does nothing, so confirm yours with
`unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l /tmp/sp.zip | grep srsly`.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These figures describe the package payload, not the amount
added to the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's wheel of the same srsly version with the same vendored
copies inside it, so the API behaves the same way. The interpreter underneath need not be the
same one — `flet build` picks the bundled version from your `requires-python` — and that
matters for exactly one format. Plain data written by `pickle_dumps` moved between CPython
3.12 and 3.13 in both directions intact, and so did an instance whose class cloudpickle could
name and re-import. A payload carrying a *function*, or a class cloudpickle had to write out
by value, is carrying bytecode, and there the mismatch is fatal rather than loud — see
**Things to know**. Restrict anything that crosses the desktop/device line to data. Every
measurement quoted on this page was taken on desktop and is here for the ratio, not the
absolute number.

## Things to know

- **A failed msgpack read leaves the cyclic garbage collector switched off.**
  `msgpack_loads` calls `gc.disable()`, unpacks, then `gc.enable()`, with no `try`/`finally` in
  between: a corrupt or truncated payload raises straight past the re-enable and the collector
  stays off for the rest of the process. `read_msgpack` does the same, and nothing reports it.
  Wrap the call wherever the input is not certainly valid:

  ```python
  try:
      state = srsly.msgpack_loads(blob)
  finally:
      gc.enable()
  ```

- **A cloudpickle payload can carry bytecode, and the wrong interpreter crashes rather than
  raising.** `pickle_dumps` is [cloudpickle](https://github.com/cloudpipe/cloudpickle), which
  serialises by value anything it cannot name for re-import — a lambda, a nested function, a
  class defined in the module you launched — putting the code objects in the payload. Such a
  lambda pickled on CPython 3.12 loaded fine on 3.13, and *calling* it killed the interpreter
  with SIGSEGV (exit 139) on desktop; a method reached through an instance of a by-value class
  did the same, and the reverse direction raised `SystemError: no locals found when setting up
  annotations`. Move that class into an importable module and the instance crosses cleanly,
  because only its name travels. There is nothing to catch in the crashing case, so the version
  check has to happen before the load, and like any pickle it executes code on load.

- **srsly's msgpack is a fork frozen inside the package, and both can be loaded at once.**
  `srsly.msgpack.version` reports its own number — `1.1.0` at srsly 2.5.3, against `1.1.2`
  for the standalone [`msgpack`](https://github.com/msgpack/msgpack-python) currently built
  for mobile — and the two are separate module objects with separate extensions. Plain data
  packs to identical bytes, which is exactly why the split is easy to miss. Where it shows:
  `msgpack.ExtType(42, b"xy")` handed to `srsly.msgpack_dumps` is not the `ExtType` class
  srsly checks for, so it is packed as an ordinary two-element array and comes back as
  `[42, b'xy']` with nothing raised; and a numpy array, which `srsly.msgpack_dumps` carries
  and plain `msgpack.packb` rejects with `TypeError: can not serialize 'numpy.ndarray'
  object`, reads back through `msgpack.unpackb` as a dict keyed `b'nd'`, `b'type'`, `b'kind'`,
  `b'shape'`, `b'data'`.

- **YAML is safe, but old and slow.** `yaml_loads` uses a vendored
  [ruamel.yaml](https://yaml.readthedocs.io/) 0.16.7 as the pure-Python safe loader — a
  `!!python/object/apply` tag comes back as `ValueError: Invalid YAML: could not determine a
  constructor` rather than a call — but the timings above are what a 2019 pure parser costs.
  Use it for a config a human edits, not for data the app writes at volume.

## Build notes (maintainers)

### Recipe shape

A plain Python package recipe with no patches: srsly's `setup.py` cythonizes three `.pyx`
sources (`msgpack/_packer`, `msgpack/_unpacker`, `msgpack/_epoch`) and compiles ujson's five C
files into a fourth extension, with Cython pulled in by the sdist's own `build-system.requires`.
It cross-compiles as-is for both platforms. `setup.py` appends `-lstdc++` to the link line of
*every* extension, the C-only ujson one included, which is where the Android host requirement
in `meta.yaml` comes from; on iOS all four resolve against `/usr/lib/libc++.1.dylib`.
cloudpickle and ruamel.yaml are vendored source directories rather than dependencies, which
is what most of the consumer page rests on.

### Upgrade hazards

- **A version bump can re-vendor.** srsly re-syncs its copies on its own schedule and the
  page above quotes those numbers directly, so after a bump read `srsly.msgpack.version`,
  `srsly.ujson.ujson.__version__`, `srsly.cloudpickle.__version__` and
  `srsly.ruamel_yaml.__version__` out of the built wheel. The float behaviour in particular
  is ujson 1.35's, not srsly's; upstream ultrajson has already fixed it, so the day srsly
  re-vendors, the whole **Precision** section goes.
- **`catalogue` is a runtime dependency on the msgpack hot path.** srsly rebuilds its numpy
  encoder list from a catalogue registry with entry-point scanning on every `Packer`, once per
  `msgpack_dumps` call — measured between twenty and thirty-six times the cost of plain
  `msgpack.packb` for a tiny object on desktop depending on whether the registry is warm, a gap
  that has all but closed by a thousand records. If the pin moves,
  confirm entry-point discovery still works from Android's zipped site-packages.
- srsly 2.5.3 declares `Requires-Python <3.15,>=3.9`, so a newer interpreter needs an
  upstream release first.

### Re-verification checklist

- **Extensions per slice:** all four `.so` files present with the right ABI tag, and the iOS
  ones `MH_DYLIB` — a `MH_BUNDLE` slice cannot be linked into an app.
- **Precision claims:** re-run the round-trip counts and state the distribution — they swing
  from 0 to 671 out of 1000 between `random.random()` and `random.uniform(-1e6, 1e6)`.
- **The `gc` bracket:** if upstream has added a `try`/`finally` around the unpack, the
  **Things to know** entry and its workaround go.
- **Sizes:** re-measure compressed and unpacked from the wheels, and measure the cleanup lever
  against the *current* serious_python junk list rather than the raw wheel — most of what looks
  droppable is already dropped by default.

### Coverage gaps

The device tests cover a JSON round trip and a msgpack round trip. Importing srsly at all
loads every one of the four extensions, so those two prove the whole native side plus the
catalogue registry resolving on device — but no more than that. YAML, cloudpickle, the
`read_*`/`write_*` file functions, the gzip variants, numpy encoding and the float-precision
behaviour rest on desktop measurement and on the example app instead.
