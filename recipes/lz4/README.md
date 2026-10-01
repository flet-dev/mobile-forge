# lz4

[`lz4`](https://python-lz4.readthedocs.io/en/stable/) binds Python to
[LZ4](https://lz4.org/), a lossless compressor built for speed rather than ratio. It
compresses at hundreds of MB/s and decompresses faster still, which on a phone means the
cost you pay is a little storage rather than CPU time and battery: caching API responses,
packing logs before upload, keeping snapshots that are read back often. The wheel compiles
in the liblz4 the package vendors.

## Install

```toml
dependencies = [
    "flet",
    "lz4",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`log-archive`](examples/log-archive) — streams a generated app log into an `.lz4` file
  at three compression levels and reports ratio, timings and a verified round trip.

## Usage in a Flet app

[`lz4.frame`](https://python-lz4.readthedocs.io/en/stable/lz4.frame.html) is the module to
use. For data already in memory:

```python
import lz4.frame

packed = lz4.frame.compress(payload)
payload = lz4.frame.decompress(packed)
```

For files,
[`lz4.frame.open`](https://python-lz4.readthedocs.io/en/stable/lz4.frame.html#lz4.frame.open)
compresses as it writes and decompresses as it reads, so a large file never has to sit in
memory whole:

```python
import os
import lz4.frame

path = os.path.join(os.environ["FLET_APP_STORAGE_DATA"], "events.lz4")
with lz4.frame.open(path, "wb") as f:
    for chunk in chunks:
        f.write(chunk)
```

`compression_level` picks the trade. The default (0) is LZ4's fast codec; 3 to 16 switch
to LZ4-HC, which compresses noticeably smaller and many times slower, while decompression
stays just as fast. HC pays off for data written once and read often, such as a bundled
cache; the default suits anything written constantly, such as a log. The
[example](examples/log-archive) measures both on your device.

In an app, run the work off the UI thread and put the result into a control:

```python
status = ft.Text()

def work():
    packed = lz4.frame.compress(payload)
    status.value = f"{len(payload):,} → {len(packed):,} bytes"
    page.update()          # a background thread needs this explicitly

page.add(status, ft.Button("Compress", on_click=lambda _: page.run_thread(work)))
```

### Storage

lz4 reads and writes nothing of its own — no config directory, no cache. Files you create
belong under
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
when they must survive, or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
when the OS may clear them. What `lz4.frame` writes is the standard LZ4 frame format, so a
file copied off the device opens with the `lz4` command-line tool or any other LZ4
implementation, and a server can decode an upload without Python.

### Threading

Compression and decompression release the GIL, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) above
gives real concurrency, not only a responsive UI. Catch exceptions inside the worker and
finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). The one-shot
functions are safe to call from any number of threads; a compressor, decompressor or open
`.lz4` file is a single stream, so give each thread its own.

## Build notes (maintainers)

### Recipe shape

Plain setuptools over a self-contained sdist, no patches. The package vendors liblz4
(`lz4libs/`: the fast and HC codecs, the frame layer and xxHash), and each of its three
extensions compiles its own copy. PyPI's desktop wheels do the same, so `flet run` and the
device run the same liblz4. A separate shared `flet-liblz4` would add a recipe and a
load-time dependency for no consumer that needs one.

### Upgrade hazards

- **The version comes from setuptools_scm.** forge builds inside mobile-forge's own git
  checkout; setuptools_scm does not search parent directories by default, so it falls back
  to the sdist's `PKG-INFO`. Confirm the wheel filename and `lz4.__version__` still match
  the recipe after a bump — a git-derived version here would be mobile-forge's.
- **`lz4.stream` is experimental upstream** and only built when `PYLZ4_EXPERIMENTAL` is
  set, exactly as on PyPI. Leave it off unless upstream promotes it.

### Re-verification checklist

- **Wheel hygiene:** correct `Machine` per ABI, every Android `LOAD` segment aligned
  `0x4000`, `DT_NEEDED` limited to bionic and `libpython` — a `liblz4.so` entry means the
  vendored copy was bypassed. iOS `LC_BUILD_VERSION` platform 2 on device and 7 on the
  simulators.
- **Interop:** a file written by the example decompresses with the desktop `lz4` CLI
  (`adb pull`, then `lz4 -d`); `test_decodes_reference_cli_frame` covers the other
  direction.
- **Sizes:** re-measure from the wheels rather than scaling the figures above.

### Coverage gaps

The device tests cover the frame API with both checksums, all three block modes with and
without the size header, chunked compressor/decompressor objects, `lz4.frame.open` on
device storage, and decoding a frame made by the reference CLI. They do not cover
dictionaries, linked blocks, `return_bytearray`, or concurrent use from several threads,
and `armeabi-v7a` is built but never executed, since CI's emulators are arm64 and x86_64.
