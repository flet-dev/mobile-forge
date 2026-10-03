# lz4

[`lz4`](https://python-lz4.readthedocs.io/en/stable/) binds Python to
[LZ4](https://lz4.org/), a lossless compressor built for speed rather than ratio. Its files
come out larger than zlib's, but it compresses several times faster and decompresses two to
three times faster, which on a phone means less CPU time and battery for every cached API
response, packed log or snapshot read back often. When size matters more than speed, the
standard library's [`zlib`](https://docs.python.org/3/library/zlib.html) needs no extra
wheel. This one compiles in the liblz4 the package vendors.

## Install

```toml
dependencies = [
    "flet",
    "lz4",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`log-archive`](examples/log-archive) — writes a generated app log to an `.lz4` file at
  three compression levels and reports ratio, timings and a verified round trip.

## Usage in a Flet app

Use [`lz4.frame`](https://python-lz4.readthedocs.io/en/stable/lz4.frame.html): its output is
the standard LZ4 format (see **Storage**), while `lz4.block` output carries a size header
only python-lz4 reads. For files,
[`lz4.frame.open`](https://python-lz4.readthedocs.io/en/stable/lz4.frame.html#lz4.frame.open)
returns a file object that compresses as you write to it, so data written in pieces never
has to sit in memory whole:

```python
import os
import lz4.frame

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "events.lz4")
with lz4.frame.open(path, "wb") as f:
    for chunk in chunks:
        f.write(chunk)
```

`compression_level` picks the trade. The default (0) is LZ4's fast codec; 3 and up switch
to LZ4-HC, which compresses noticeably smaller and many times slower, while decompression
stays just as fast. HC tops out at 12 — liblz4 treats anything higher as 12, whatever
`lz4.frame.COMPRESSIONLEVEL_MAX` says. HC pays off for data written once and read often,
such as a bundled cache; the default suits anything written constantly, such as a log. The
[example](examples/log-archive) measures both on your device.

In an app, run the work off the UI thread and put the result into a control:

```python
status = ft.Text()

def work():
    try:
        packed = lz4.frame.compress(payload)
        status.value = f"{len(payload):,} → {len(packed):,} bytes"
    except Exception as e:
        status.value = f"failed: {e!r}"
    page.update()          # a background thread needs this explicitly

page.add(status, ft.Button("Compress", on_click=lambda _: page.run_thread(work)))
```

### Storage

lz4 reads and writes nothing of its own — no config directory, no cache. Files you create
belong under
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
when they must survive,
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for caches you can rebuild (the OS may purge it under storage pressure), or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch that may vanish between launches. What `lz4.frame` writes is the standard LZ4
frame format, so a file uploaded from the device decodes with the `lz4` command-line tool or
any other LZ4 implementation, with no Python on the server.

### Threading

[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) keeps
the UI responsive whatever lz4 call it runs, and the LZ4 calls themselves release the GIL,
so compressing (through any API) and `lz4.frame.decompress` genuinely run in parallel with
other threads. Reading through `lz4.frame.open` is the exception: it decompresses in small
chunks driven by Python code that holds the GIL, so several readers do not speed each other
up.

Catch exceptions inside the worker — `run_thread` does not surface them, and `lz4.frame`
reports corrupt input as a plain `RuntimeError` — and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). The one-shot
functions are safe from any number of threads. A compressor, decompressor or open `.lz4`
file is not: it has no lock, and lz4 changes it with the GIL released, so sharing one
between threads can crash the app. Give each thread its own, and remember `run_thread` uses
a pool, so two quick taps can overlap.

### App size

About 155–210 KB compressed and 280–650 KB unpacked per slice, all of it three small
compiled extensions; there are no data files. Small enough that it need not figure in which
ABIs you ship.

## Build notes (maintainers)

### Recipe shape

Plain setuptools over a self-contained sdist, no patches. The package vendors liblz4
(`lz4libs/`: the fast and HC codecs, the frame layer and xxHash), and each of its three
extensions statically compiles the parts it uses: `lz4._version` only the fast codec,
`lz4.block` adds HC, `lz4.frame` adds the frame layer and xxHash. PyPI's desktop wheels do
the same, so `flet run` and the device run the same liblz4. A separate shared `flet-liblz4`
would add a recipe and a load-time dependency for no consumer that needs one.

### Upgrade hazards

- **The version comes from setuptools_scm.** forge builds inside mobile-forge's own git
  checkout; setuptools_scm does not search parent directories by default, so it falls back
  to the sdist's `PKG-INFO`. Confirm the wheel filename and `lz4.__version__` still match
  the recipe after a bump — a git-derived version here would be mobile-forge's.
- **`lz4.stream` is experimental upstream** and only built when `PYLZ4_EXPERIMENTAL` is
  set, exactly as on PyPI. Leave it off unless upstream promotes it.
- **The HC ceiling is liblz4's, not python-lz4's.** If a bump moves the vendored liblz4 past
  1.9.x, re-check `LZ4HC_CLEVEL_MAX` in `lz4libs/lz4hc.h` before keeping the "tops out at
  12" sentence.

### Re-verification checklist

- **Wheel hygiene:** correct `Machine` per ABI, every Android `LOAD` segment aligned
  `0x4000`, `DT_NEEDED` limited to bionic and `libpython` — a `liblz4.so` entry means the
  vendored copy was bypassed. iOS `LC_BUILD_VERSION` platform 2 on device and 7 on the
  simulators.
- **Interop:** a file written by the example decompresses with the desktop `lz4` CLI. Pull
  the path the app shows from the iOS simulator's data container
  (`xcrun simctl get_app_container <udid> com.flet.lz4-log-archive data`) or from a
  `google_apis` emulator after `adb root`, then run `lz4 -d`.
  `test_decodes_reference_cli_frame` covers the other direction.
- **Sizes:** re-measure from the wheels rather than scaling the figures above.

### Coverage gaps

The device tests cover the frame API with both checksums, the default, accelerated and HC
block modes with and without the size header, chunked compressor/decompressor objects,
`lz4.frame.open` written in pieces to device storage, and decoding a frame made by the
reference CLI. They do not cover dictionaries, `return_bytearray`, or concurrent use from
several threads. CI executes two of the six slices — Android `x86_64` on an emulator and
the arm64 iOS simulator; `arm64-v8a`, `armeabi-v7a`, the iOS device slice and the x86_64
simulator slice are built and inspected but not run there.
