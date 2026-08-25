# safetensors

[`safetensors`](https://huggingface.co/docs/safetensors/index) is Hugging Face's tensor file
format and its reference implementation: an 8-byte length, a JSON header, then raw tensor
bytes. No pickle, so loading a file cannot execute code — and, more to the point on a phone,
the reader **memory-maps** the file by default instead of reading it. Opening a
half-gigabyte file and reading its whole header costs a fraction of a millisecond and a
fraction of a megabyte; one row out of one tensor inside it costs about the same. Loading all
of it costs twice the file in RAM.

That gap is the whole reason to reach for this on mobile: a weights file, an embedding table
or a lookup matrix can sit in app storage larger than anything you would dare hold in RAM,
and your app touches only the parts it needs. It is a **storage format, not a runtime** —
nothing here multiplies matrices. Pair it with [`onnxruntime`](../onnxruntime),
[`tflite-runtime`](../tflite-runtime) or plain [`numpy`](../numpy) for the arithmetic, or with
[`faiss-cpu`](../faiss-cpu) when the tensor you store is a table of embeddings to search.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "safetensors",
    "numpy",
]
```

**Ask for numpy.** Upstream treats it as an extra rather than a hard dependency, and without
it every file-reading entry point is gone: `import safetensors.numpy` and
`safe_open(..., framework="numpy")` both raise
`ModuleNotFoundError: No module named 'numpy'`. Only the bytes-level API (`serialize`, `serialize_file`, `deserialize`)
still works. Listing `"numpy"` yourself and writing `"safetensors[numpy]"` resolve to the
identical set, so use whichever reads better.

**numpy is also the only backend that can exist here.** `safetensors[torch]` is a hard
resolve failure — `Could not find a version that satisfies the requirement torch>=2.4` — not
a fallback to something that works, and the jax, flax, paddle, mlx and tensorflow extras fail
the same way: none of those frameworks has a wheel on pypi.flet.dev. Convert weights to a
numpy-readable dtype before you ship them; [Things to know](#things-to-know) has the one that
will bite you.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`lazy-weights`](examples/lazy-weights) — writes a 50 MB weights file on device and measures
  what reading its header, one row, and all of it each cost.

## Usage in a Flet app

Open the file, read the header, take the one row you need, and pour the result into a Flet
control such as a [`ft.ListView`](https://flet.dev/docs/controls/listview/).
[`safe_open` and `get_slice`](https://huggingface.co/docs/safetensors/index) are the lazy
pair, and nothing below reads more than a few kilobytes off disk:

```python
import os

import flet as ft
from safetensors import safe_open

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "weights.safetensors")

with safe_open(path, framework="numpy") as weights:
    # keys() and get_shape() touch the header only.
    shapes = [(name, weights.get_slice(name).get_shape()) for name in weights.keys()]
    first = weights.get_slice(shapes[0][0])[0:1]

listing = ft.ListView(
    expand=True,
    controls=[ft.Text(f"{name}  {shape}") for name, shape in shapes]
    + [ft.Text(f"row 0 of {shapes[0][0]}: {first[0, :4]}")],
)
```

[`load_file`](https://huggingface.co/docs/safetensors/api/numpy#safetensors.numpy.load_file)
and [`save_file`](https://huggingface.co/docs/safetensors/api/numpy#safetensors.numpy.save_file)
are the whole-file pair; both take `str` or `os.PathLike`.

### Storage

A `.safetensors` file is an ordinary file, so it belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, in backups, never auto-deleted. Never
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) for a file you cannot cheaply regenerate. Weights you produced
elsewhere are an [asset](https://flet.dev/docs/cookbook/assets): put the file in `src/assets/`
and read it from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).
Reading needs no write permission, and `safe_open` is happy on a mode `0400` file.

Three things about writing one:

- **`save_file` will not create a missing parent directory.** It raises
  `SafetensorError: Error while serializing: I/O error: No such file or directory (os error
  2) at path "…/.tmpXXXXXX"` — not an `OSError`, so `except OSError` misses it, and the path
  it names is the temporary one, not yours. `os.makedirs(..., exist_ok=True)` first.
- **`save_file` is already atomic — do not write your own temp-and-rename around it.** It
  writes a hidden `.tmp…` file in the *target's* directory and renames it into place, so the
  destination never exists half-written: `SIGKILL` partway through a 1.5 GB write left
  `.tmpcegaih` behind and no `weights.safetensors` at all. What you owe the user is a sweep of
  stale `.tmp*` in that directory after a crash, not an `os.replace()` dance. Replacing the
  file under a live reader is safe either way — a handle that had it mapped went on reading
  correct values across both an `os.replace()` over it and an `os.unlink()` of it.
- **Put your own digest in the header.** `metadata={"sha256": ...}` round-trips as a freeform
  `str → str` dict and `f.metadata()` reads it back without touching a byte of tensor data.
  The format has no checksum of its own, and that is the one damage class it cannot detect
  for you.

### Threading

**Reading holds the GIL for essentially the whole call. Writing releases it completely.**
Measured as the longest stall a busy canary thread suffers while the call runs, because a
canary that never gets a turn is a UI thread that never gets a frame. Median of 5–9 runs,
desktop CPython 3.14, 512 MB file:

| call | duration | longest canary stall |
| --- | --- | --- |
| `load_file`, backend `mmap` | 58 ms | 48 ms |
| `load_file`, backend `pread` | 59 ms | 53 ms |
| `save_file` | 482 ms | 14 ms |

The harness floor on that host is about 14 ms, so `save_file` is a clean zero and the two
reads hold the GIL for most of the call. The practical edge:
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys you
**nothing** for a big read — moving a 200 ms load onto a worker freezes the UI for about
200 ms anyway. Read lazily instead, which is fast enough to be invisible. Where a big read is
unavoidable, still push it to `run_thread` so the handler returns and a spinner can paint,
but budget for the freeze, and mind the two standing Flet caveats: `run_thread` never
retrieves the worker's future, so an exception inside one surfaces nowhere at all (wrap the
body in `try/except Exception`), and auto-update does not reach background threads, so end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**One `safe_open` handle is safe to share across threads.** Eight threads doing 200 reads
each on one handle produced zero exceptions and zero wrong values, with each thread reading a
*different* tensor so a mixup could not hide behind everyone asking for the same bytes; both
backends, `get_tensor` and `get_slice` alike. That is the opposite of [`apsw`](../apsw),
where an overlap raises, and of [`duckdb`](../duckdb), where it silently returns another
thread's answer. Arrays it returns outlive the `with` block, as does a `get_slice` object.

**Only the default backend gives the handle back its file descriptor.** Under `mmap` the fd
closes once the mapping exists; under `backend="pread"` every live handle keeps one, so a
screen holding one open per candidate model file spends descriptors the default does not.

### Reading and memory

**`backend="pread"` silently destroys laziness for slices**, which is a trap because it is
otherwise the memory-cheaper backend. Fresh process per row, 512 MB file, 16 tensors of
32 MB, peak resident-set delta:

| what you do | `mmap` (default) | `pread` |
| --- | --- | --- |
| `safe_open`, plus every name, shape and dtype | +0.1 MB | +0.2 MB |
| …plus one 11 KB row of one tensor | +0.1 MB | **+32 MB** |
| one whole 32 MB tensor | +64 MB | +32 MB |
| `load_file` (all 512 MB) | **+1024.3 MB** | +512.4 MB |
| `safetensors.numpy.load(open(p, "rb").read())` | +1024.3 MB | +1024.3 MB |

Read the second row first: under `pread` a one-row slice materialises the entire tensor, so
you pay 32 MB for 11 KB. Leave the default `mmap` whenever you slice or read a subset. The
fourth row is the other half — under `mmap` a full `load_file` peaks at **twice** the file,
because the mapped pages go resident *and* the copy handed to numpy is a second allocation,
so `pread` is the right choice for a deliberate whole-file load. Never call
[`safetensors.numpy.load(f.read())`](https://huggingface.co/docs/safetensors/api/numpy#safetensors.numpy.load)
on a file of any size: it has no mmap at all and the backend argument cannot help it. Both
backends are compiled into every slice on both platforms, so `backend=` behaves the same
either side.

**`safe_open` is O(header), not O(file)** — 0.018 ms on an 8 MB file and 0.022 ms on a 512 MB
one, flat, against `load_file`'s 0.66 ms and 60 ms, which is linear. Every tensor's shape and
dtype on top of the open adds under 0.005 ms. The same
[header read in pure Python](https://huggingface.co/docs/safetensors/metadata_parsing) —
`struct.unpack("<Q", f.read(8))` then `json.loads(f.read(n))` — takes 0.018 ms, so a screen
listing candidate model files need not load the extension at all.

### App size

Approximately 420–460 KB compressed per slice and 0.9–1.2 MB unpacked, 87–91% of it the
extension. There is no useful cleanup lever inside the wheel: the Python layer is about
48 KB, most of it backend modules that cannot be installed on a phone anyway.

The lever is architecture. On Android use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures):

```toml
[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

Dropping `armeabi-v7a` costs little — 64-bit has been mandatory for Play Store uploads since
2019 — and it is the one slice where the central premise has a ceiling: mapping a file needs
address space, and a 32-bit process has a few gigabytes of it for everything. No figure
exists for where that starts to bite, so if you ship that ABI and your files are large,
measure it.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel, and here the two are unusually close: all
seven shipped `.py` files hash identically across the Android wheel, the iOS wheel and the
desktop wheel of the same version, and everything below them is one Rust source tree compiled
per slice. Desktop behaviour of the Python layer therefore transfers.

Memory does not. A desktop has address space and page cache a phone does not, and the mmap
story above is exactly what changes when either runs out — validate a real file at its real
size on a device. One cosmetic difference: serious_python's mobile cleanup drops the `.pyi`
stub and `py.typed` on the way into the app, so your editor's view of the API comes from the
desktop install. Nothing imports a stub at run time.

## Things to know

- **bfloat16 — the dtype most modern weights ship in — cannot be read through numpy, and it
  fails late.** The header reads fine, so `keys()`, `metadata()` and every shape and dtype
  come back normally; only the tensor fetch blows up, typically after your UI has already
  listed the model. `get_tensor`, `get_slice(...)[...]` and `load_file` all raise
  `TypeError: data type 'bfloat16' not understood` — a numpy error with safetensors nowhere
  in the message — and the bytes path fails differently again, with `KeyError('BF16')`. The
  five float8 codes fail similarly but not identically, with
  `AttributeError: module 'numpy' has no attribute 'float8_e4m3fn'` rather than a `TypeError`. Two ways out: convert to `float16` before shipping
  the file, which works everywhere and halves it; or read it raw, with no framework involved,
  where `dict(deserialize(open(p, "rb").read()))` yields
  `{"dtype": "BF16", "shape": [...], "data": <bytes>}` and
  `(np.frombuffer(data, np.uint16).astype(np.uint32) << 16).view(np.float32)` reconstructs
  the exact float32 values. The cost of the second is that `deserialize` takes bytes, so you
  read the whole file into RAM and lose the mmap.
- **A non-contiguous numpy array is written as silent garbage.** Nothing checks contiguity:
  `nbytes` bytes are read raw from the array's base pointer. With
  `a = np.arange(12, dtype=np.float32).reshape(3, 4)`, `a[:, ::2]` goes in as
  `[[0,2],[4,6],[8,10]]` and comes back `[[0,1],[2,3],[4,5]]`; `a.T` returns the right shape
  with the wrong contents; `a[::-1]` reads past the end of the buffer. Nothing raises.
  `np.ascontiguousarray(x)` before `save_file` fixes all three, and
  `assert x.flags.c_contiguous` gets you the error early.
- **There is no checksum: the format is safe against code execution, not against bit rot.** A
  single flipped byte inside a tensor payload opens without complaint and hands you a wrong
  number — measured, with every other tensor in the same file still matching perfectly. If a
  file can be damaged in transit or by a half-finished write, carry your own digest (see
  [Storage](#storage)) and check it before trusting the tensors.
- **Truncation, by contrast, is always caught — at `safe_open`, before any tensor is read.**
  So is every other structural defect: an empty file, stray bytes, a header length with
  nothing behind it, a truncated or non-JSON header, a file with its tail cut, an absurd
  header length. All of them raise `SafetensorError` from `safe_open`, `keys()`, `get_tensor`
  and `load_file` alike, with one of five messages — `header too small`,
  `invalid header length`, `header too large` (the JSON header is capped at exactly
  100,000,000 bytes), `invalid JSON in header: …`, and, for anything truncated,
  `incomplete metadata, file not fully covered`. Hand-edited headers are rejected as
  precisely: offset overlaps, gaps and reversed pairs give ``invalid offset for tensor `b` ``,
  a shape disagreeing with its byte length gives `invalid shape, data type, or offset`, and an
  overflowing shape says so. This check is free — open the file and let it throw.
- **Two exception families come out of the same call, and neither is an `OSError`.**
  Structural damage is `SafetensorError`, which inherits straight from `Exception`; a missing
  path is a plain `FileNotFoundError`; a bfloat16 tensor is a numpy `TypeError`. So
  `except OSError` and `except SafetensorError` both miss cases. Catch broad `Exception`
  around every open and read and show `str(error)` — the Rust messages are worth surfacing
  verbatim, since *"incomplete metadata, file not fully covered"* tells a user their download
  was truncated. This matters more in Flet than elsewhere: an unhandled exception in an event
  handler makes Flet send `SESSION_CRASHED`.
- **`framework=` takes exactly `numpy`, `np`, `pt`, `torch`, `tf`, `tensorflow`, `flax`,
  `jax`, `mlx`, `paddle`, and it is case-sensitive** — anything else, `"NUMPY"` included, is
  `SafetensorError: framework … is invalid`, and `None` is a `TypeError`. The unavailable ones
  do not fail uniformly: with numpy installed, `pt`, `torch` and `paddle` raise
  `ModuleNotFoundError` from `safe_open` itself while `tf`, `tensorflow`, `flax`, `jax` and
  `mlx` open fine and raise at the first `get_tensor` (and `flax` names `jax`, not `flax`);
  without numpy all ten raise at `safe_open`, and the seven that are not `pt`/`torch`/`paddle`
  name numpy rather than the framework you asked for, so `framework="mlx"` reports a missing
  numpy. Import `safetensors.numpy` explicitly — plain `import safetensors` does not pull
  numpy in.
- **Drop `device=` entirely.** Every value but `"cpu"` fails —
  `SafetensorError: Device mps is not supported for framework numpy`, likewise `cuda`,
  `cuda:0` and `0`; `"meta"` gives `device meta is invalid`. The Apple-silicon MPS fast path
  the upstream docstrings describe needs PyTorch, which cannot be installed here.
- **`keys()` is lexicographic, so `block.10` sorts before `block.2`.** `offset_keys()` and the
  raw header agree with it for files this library wrote, since `save_file` writes in
  sorted-name order — so code assuming `keys()[-1]` is the last tensor in the file is wrong
  for any file with more than nine numbered blocks. Sort numerically yourself for display, and
  read `data_offsets` from the header if you need a tensor's position in the file.
- **Tensors come back as copies, not writable windows onto the file.** `owndata` is `False`
  and the array's `base` is another ndarray, but writing to one leaves the file unchanged.
- **Edge cases worth knowing once.** `save_file({})` and a zero-element array round-trip
  cleanly; a 0-d numpy scalar does not — `np.float32(3.5)` raises
  `AttributeError: 'numpy.float32' object has no attribute 'ctypes'`. Big-endian arrays are
  handled correctly, and a `">f4"` array round-trips equal. Every dtype numpy itself has works
  through `safe_open` and `load_file` except `complex128`, which is refused at save with a
  message naming the 20 dtypes the writer accepts.
- **`abi3` in the filename is cosmetic here.** The extension is
  `safetensors/_safetensors_rust.abi3.so` on both platforms, but the wheels are not
  interchangeable across Python versions — the cp312 Android slice needs `libpython3.12.so`
  and the cp314 one `libpython3.14.so`. The import resolves normally either way, since
  `.abi3.so` is a standard extension suffix.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is the whole recipe, its two non-obvious settings are commented in place, and
there is no `patches/`. The shape needs no defending: safetensors publishes an sdist, builds
with maturin, and the minimal Rust recipe worked for every ABI and both platforms with zero
patches, zero `excluded_arches` and no `requirements.host`.

The ELF confirms that last one is right rather than lucky. On every Android ABI the extension
links exactly `libpython3.<minor>.so`, `libdl.so` and `libc.so`, has no `SONAME`, and vendors
nothing — in particular **no `libc++_shared.so`**, because nothing in the crate graph pulls a
C++ runtime in. (The `flet-libcpp-shared` in a `safetensors[numpy]` resolve comes from numpy.)
That graph is 33 crates on iOS, 34 on Android arm64-v8a and x86_64, and 35 on armeabi-v7a,
which alone pulls `portable-atomic` — the 32-bit atomics shim — per each wheel's CycloneDX
SBOM.

### Upgrade hazards

- **Re-check the extras, not just the build.** That `safetensors` installs one wheel and
  nothing else is a property of upstream's `METADATA`: all 36 `Requires-Dist` lines are gated
  behind an extra. A release adding an unconditional dependency starts forge rewriting
  `Requires-Dist` on Android, at which point `METADATA` stops being byte-identical across
  platforms. The 404 status of `torch`, `jax`, `jaxlib`, `flax`, `paddlepaddle`, `mlx` and
  `tensorflow` on pypi.flet.dev is likewise someone else's business and could change.
- **The dtype tables are upstream's and they move.** The 13-entry `_TYPES` dict in
  `safetensors/numpy.py` is what makes bfloat16 unreadable, and the 20-name list in the
  "Unknown dtype" message is what makes `complex128` unwritable. Re-read both from the built
  wheel — and note they disagree with the Rust enum, which the binary's own panic string still
  puts at 22 variants (`strings … | grep 'variant index'`).
- **The error strings are quoted verbatim** on the page above, and upstream rewords them. So
  are the accepted `framework=` and `backend=` values and the 100,000,000-byte header cap.
- **Bump the example's pins with the recipe.** `examples/lazy-weights/pyproject.toml` pins
  `safetensors`, `numpy` and `flet` with `==`, and `requires-python = ">=3.11"` is the floor
  numpy 2.4.6 forces — verified by copying that file alone into an empty directory and running
  `uv lock`, which resolves at `>=3.11` and fails at `>=3.10`. Moving numpy may move it.

### Re-verification checklist

- **Open every slice, not one per platform.** The crate counts are 33/34/35 because
  armeabi-v7a alone pulls `portable-atomic` in, and a two-binary comparison misses it.
- **Android:** every `PT_LOAD` segment must carry 16 KB alignment (`0x4000`) on all three
  ABIs, which is what keeps the wheel installable on Android 15.
- **iOS:** `otool -hv` must report `MH_DYLIB` marked `NOUNDEFS` on all three slices — that is
  why forge's `MH_BUNDLE`→`MH_DYLIB` conversion never engages here. Two artefacts are expected
  and are not defects: the `LC_ID_DYLIB` install name is a build-machine path under
  `target/…/release/deps/`, which nothing resolves because Python loads the extension by file
  path; and the deployment-target load command differs between slices (device and
  x86_64-simulator carry `LC_VERSION_MIN_IPHONEOS 10.0`, the arm64 simulator
  `LC_BUILD_VERSION platform 7, minos 14.0`) despite `ios_13_0` in every filename.
- **Re-audit the shipped `.py` files** for `__file__`, `importlib.resources`, `pkgutil` and
  `pkg_resources`. None of the seven uses any of them today, and the wheel carries no data
  file opened at run time, which is why Install needs no
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry. If one
  appears on a bump, consumer guidance needs that entry and the failure symptom.
- **Re-measure sizes and linkage from the built wheels** rather than scaling old figures. The
  matrix is 18 wheels — three Android ABIs, three iOS slices, Python 3.12/3.13/3.14 — and
  upstream's `Requires-Python` is `>=3.10`.

### Coverage gaps

- **No on-device run backs a single behavioural number on this page.** The memory table, the
  GIL table, the timings, and the dtype and corruption matrices all came off a desktop install
  of the pinned version plus numpy 2.4.6. The bridge is narrow but real: all seven shipped
  `.py` files and the `.pyi` stub hash identically across the Android wheel, the iOS wheel and
  the desktop PyPI wheel, and everything else lives in one Rust source tree compiled per
  slice. Sizes, linkage and Mach-O flags came off the wheels themselves. The
  [`lazy-weights`](examples/lazy-weights) example exists to put the memory and timing figures
  on a real screen, which is the thing to run after a bump.
- **`tests/test_safetensors.py` covers the bytes API and one numpy `safe_open` round trip, and
  nothing else.** It does not touch `backend=`, corruption, bfloat16, contiguity, `metadata()`
  or `get_slice`, all of which [Things to know](#things-to-know) makes claims about. Worth
  adding, in rough order of value: a `backend="pread"` round trip, a truncated file asserting
  the `incomplete metadata` message, and a bf16 header asserting the `TypeError` — after which
  three of this page's louder claims would turn CI red rather than rotting quietly. Note that
  `test.requires: [numpy]` is what makes the numpy test runnable on device at all, and that
  `SMOKE_TEST_PACKAGES` is only the fallback recipe list, so absence from it says nothing
  about whether the test ran.
