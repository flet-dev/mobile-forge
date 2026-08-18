# safetensors

[`safetensors`](https://huggingface.co/docs/safetensors/index) is Hugging Face's tensor file
format and its reference implementation: an 8-byte length, a JSON header, then raw tensor
bytes. No pickle, so loading a file cannot execute code — and, more to the point on a phone,
the reader **memory-maps** the file by default instead of reading it. Opening a 512 MB file
and reading its entire header costs 0.02 ms and a tenth of a megabyte; pulling one 11 KiB row
out of a 32 MB tensor inside it costs another tenth of a megabyte and stays well under a
millisecond. Loading all of it costs 1 GB.

That gap is the whole reason to reach for this on mobile. A weights file, an embedding table
or a lookup matrix can sit in app storage larger than anything you would dare hold in RAM,
and your app touches only the parts it needs. It is a **storage format, not a runtime**:
nothing here multiplies matrices. Pair it with [`onnxruntime`](../onnxruntime),
[`tflite-runtime`](../tflite-runtime) or plain [`numpy`](../numpy) for the arithmetic, or with
[`faiss-cpu`](../faiss-cpu) when the tensor you are storing is a table of embeddings to search.

The core is Rust — 33 crates on iOS, 34 on Android arm64-v8a and x86_64, 35 on armeabi-v7a,
per the wheel's own CycloneDX SBOM — none of them pulling in a C++ runtime, so the extension
links nothing but the interpreter and the platform's C library.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "safetensors",
    "numpy",
]
```

**`safetensors` on its own pulls in exactly one wheel** — about 420 KB — on both platforms.
Every one of the 36 `Requires-Dist` lines in its `METADATA` is gated behind an extra, so
there is nothing unconditional to install.

**numpy is one of those extras, and you almost certainly want it.** Without it the package
still imports and the bytes-level API (`serialize`, `serialize_file`, `deserialize`) works —
verified in a numpy-free interpreter; that is the path this recipe's first two on-device
tests take, though they run with numpy present. But every file-reading entry point is gone:
`import safetensors.numpy` and `safe_open(..., framework="numpy")` raise
`ModuleNotFoundError: No module named 'numpy'`, and so does `safe_open` under every other
`framework=` value except `pt`, `torch` and `paddle`, which name their own missing module
instead.
Listing `"numpy"` yourself and writing `"safetensors[numpy]"` resolve to the identical set,
so use whichever reads better. On Android that set is 3 wheels — safetensors, numpy and
`flet-libcpp-shared`, which numpy needs and safetensors does not; on iOS it is 2.

**numpy is also the only backend that can exist here.** `torch`, `jax`, `jaxlib`, `flax`,
`paddlepaddle`, `mlx` and `tensorflow` publish nothing at all on pypi.flet.dev — all seven
are HTTP 404 — so asking for `safetensors[torch]` is a hard resolve failure
(`Could not find a version that satisfies the requirement torch>=2.4`), not a fallback to
something that works. Convert weights to a numpy-readable dtype before you ship them; see
[Things to know](#things-to-know) for the one dtype that will bite you.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. The wheel is 15 files; `safetensors/` holds the extension, seven `.py`
files, a `.pyi` stub and an empty `py.typed`, and nothing else — no data file anything opens
at run time, and none of the seven reads `__file__`, `importlib.resources`, `pkgutil` or
`pkg_resources`.

Wheels exist for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and
all three iOS slices (device, and both simulator architectures), on Python 3.12, 3.13 and
3.14 — a complete 18-wheel matrix with no gaps. `Requires-Python` in the wheel is upstream's
`>=3.10`.

## Storage

A `.safetensors` file is an ordinary file, so it belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, included in backups, never auto-deleted:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "weights.safetensors")
```

Never
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) for a file you cannot cheaply regenerate. To ship weights you
produced elsewhere, put the file in your app's `src/assets/` and read it from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir);
reading needs no write permission, and `safe_open` is happy on a mode `0400` file under
both backends.

Three things about writing one:

- **`save_file` will not create a missing parent directory.** It raises
  `SafetensorError: Error while serializing: I/O error: No such file or directory (os error
  2) at path "…/.tmpXXXXXX"` — not an `OSError`, so `except OSError` misses it, and the
  path it names is the temporary one, not yours. `os.makedirs(..., exist_ok=True)` first.
  Both `str` and `os.PathLike` paths are accepted, by `save_file` and `safe_open` alike.
- **`save_file` is already atomic — do not write your own temp-and-rename around it.**
  `serialize_file` creates a hidden `.tmp…` file in the *target's* directory and renames it
  into place, so the destination path never exists half-written: `SIGKILL` partway through a
  1.5 GB write left `.tmpcegaih` behind and no `weights.safetensors` at all. What you owe the
  user is therefore not an `os.replace()` dance but a sweep of stale `.tmp*` in that
  directory after a crash. (The truncation story in [Things to know](#things-to-know) is
  still worth having — it is how you catch a file that arrived truncated from a download or a
  copy, which is not something this writer can produce.) Replacing the file under a live
  reader is safe either way: a handle that had it mapped went on reading correct values after
  an `os.replace()` over it, and after an `os.unlink()` of it outright.
- **Put your own digest in the header.** `metadata={"sha256": ...}` round-trips as a
  freeform `str → str` dict and `f.metadata()` reads it back without touching a byte of
  tensor data. The format has no checksum of its own, and that is the one damage class it
  cannot detect for you.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`lazy-weights`](examples/lazy-weights) — writes a 48 MB file on device and measures what
  reading its header, one row, and all of it each cost.

## Threading

**Reading holds the GIL for essentially the whole call. Writing releases it completely.**
Measured by the longest stall a busy canary thread suffers while the call runs — a canary
that never gets a turn is a UI thread that never gets a frame. The first three rows are the
harness checking itself: an idle wait and a call known to release must sit at the floor, and
one known to hold must sit near 1, or nothing below them means anything. Median of 5–9 runs,
desktop CPython 3.14, 512 MB file:

| call | duration | longest canary stall | stall ÷ call |
| --- | --- | --- | --- |
| `time.sleep(0.3)` (nothing running) | 314 ms | 14.4 ms | 0.05 |
| `hashlib.sha256` of 200 MB (releases) | 79 ms | 13.3 ms | 0.17 |
| `sum(range(60_000_000))` (holds) | 317 ms | 310.4 ms | 0.98 |
| `load_file`, backend `mmap` | 58 ms | 48.2 ms | 0.83 |
| `load_file`, backend `pread` | 59 ms | 52.5 ms | 0.90 |
| `save_file` | 482 ms | 13.7 ms | 0.03 |

The floor is about 14 ms on this host, so the two `load_file` rows are the signal and the
`save_file` row is a clean zero. **Do not read the 0.83 as "17% of the time is yours"** —
below roughly 50 ms this ratio is dominated by the canary's own scheduling jitter rather
than by the GIL, and the row is only just clear of the floor. The conclusion that survives
is the qualitative one, and it has a practical edge:
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys you
**nothing** for a big read. Moving a 200 ms load onto a worker freezes the UI for about
200 ms anyway.

So read lazily instead, which is fast enough to be invisible — one row out of a 512 MB file
is a fraction of a millisecond and a fraction of a megabyte. Where a big read is genuinely
unavoidable, still push it to `run_thread` so the handler returns and a spinner can paint,
but budget for the freeze. And remember the two
standing Flet caveats: `run_thread` never retrieves the worker's future, so an exception
raised inside one surfaces nowhere at all — wrap the body in `try/except Exception` — and
auto-update does not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**One `safe_open` handle is safe to share across threads.** Eight threads doing 200 reads
each on a single handle produced zero exceptions and zero wrong values — with each thread
reading a *different* tensor carrying a value only it should see, so a cross-thread mixup
would show up rather than hide behind everyone asking for the same bytes, and repeated for
`get_tensor` and `get_slice` on both backends. That is the opposite of [`apsw`](../apsw),
where an overlap raises, and of [`duckdb`](../duckdb), where it silently returns another
thread's answer. The arrays it returns outlive the `with` block, as does a `get_slice`
object, which still slices correctly after `__exit__`.

**Only the default backend gives the handle back its file descriptor.** Under `mmap` the fd
is closed once the mapping exists: five live handles added 0 entries to `/dev/fd`, where five
plain `open()` calls added 5. Under `backend="pread"` every live handle keeps one — five
handles, five entries — so a screen that holds one open per candidate model file is spending
descriptors it does not spend on the default.

## Android notes

The extension links three libraries and the list is identical on all three ABIs:
`libpython3.<minor>.so`, `libdl.so` and `libc.so`. There is no `SONAME`, nothing is
vendored, and — unlike [`tokenizers`](../tokenizers) — **no `libc++_shared.so`**, because
nothing in the crate graph pulls a C++ runtime in. That is why the Android wheels carry no
`flet-libcpp-shared` dependency and the recipe needs no `requirements.host`. The
`flet-libcpp-shared` you see in a `safetensors[numpy]` resolve comes from numpy.

All four `PT_LOAD` segments carry 16 KB alignment (`0x4000`) on every Android slice, which
Android 15 requires.

Android uses the large-file syscall variants — `mmap64`, `pread64`, `lseek64` and
`ftruncate64` alongside plain `mmap`/`munmap` — where iOS uses plain `_mmap`/`_munmap`/
`_pread`. Both the `mmap` and the `pread` backend are compiled into every slice on both
platforms, so `backend=` behaves the same either side.

**armeabi-v7a is the only 32-bit slice**, and it is the one place the central premise has a
ceiling: mapping a file needs address space, and a 32-bit process has a few gigabytes of it
for everything. No figure has been established for where that starts to bite, so if you ship
that ABI and your files are large, measure it. Dropping it via
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) costs
little else — 64-bit has been mandatory for Play Store uploads since 2019:

```toml
[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

## iOS notes

**The extension needs no fixing up.** All three iOS slices are already `MH_DYLIB` marked
`NOUNDEFS` (`otool -hv`), so forge's `MH_BUNDLE`→`MH_DYLIB` conversion never engages for
this recipe. Linkage is Flet's Python framework plus two OS libraries:
`@rpath/Python.framework/Python`, `/usr/lib/libiconv.2.dylib` and
`/usr/lib/libSystem.B.dylib`.

**`otool -L` prints a build-machine path first and it is not a missing dependency.** The
`LC_ID_DYLIB` install name is
`/Users/runner/work/mobile-forge/…/target/aarch64-apple-ios/release/deps/libsafetensors_rust.dylib`,
an artefact of how maturin links a Rust cdylib. Python loads the extension by file path and
nothing resolves that name. Same artefact [`tokenizers`](../tokenizers) records.

**The deployment-target load command is not the same on all three slices**, and none of them
says 13.0 despite the `ios_13_0` in every filename: the device and x86_64-simulator slices
carry `LC_VERSION_MIN_IPHONEOS version 10.0`, the arm64 simulator carries
`LC_BUILD_VERSION platform 7, minos 14.0`. It bites nothing on a phone Flet supports, and it
is recorded here because a slice comparison that opens one binary and generalises gets it
wrong. Same discrepancy [`protobuf`](../protobuf) and `tokenizers` record.

**iOS carries 27% more native code than Android arm64-v8a** for the same source — 1,044 KiB
against 824 KiB. Every shipped `.py` file is byte-identical between the two platforms, and
so is `METADATA`, at 4,189 bytes: forge rewrote nothing, because there was no unconditional
`Requires-Dist` to rewrite. (That is the opposite of `tokenizers`, whose Android `METADATA`
is a rewritten stub.) The one `dist-info` file that does differ is the SBOM: Android's crate
graph carries `linux-raw-sys` where iOS's does not, and armeabi-v7a carries `portable-atomic`
on top of that — the 32-bit atomics shim, which no 64-bit slice needs.

## Things to know

- **bfloat16 — the dtype most modern weights ship in — cannot be read through numpy, and it
  fails late.** The header reads fine, so `keys()`, `metadata()` and every shape and dtype
  come back normally; only the actual tensor fetch blows up, typically after your UI has
  already listed the model. `get_tensor`, `get_slice(...)[...]` and `load_file` all raise
  `TypeError: data type 'bfloat16' not understood` — a numpy error with safetensors nowhere
  in the message — and the bytes path fails differently again, with `KeyError('BF16')`, since
  `safetensors/numpy.py`'s `_TYPES` table has 13 entries and no `BF16`. The five float8
  codes behave the same way (`AttributeError: module 'numpy' has no attribute
  'float8_e4m3fn'`). Two ways out. Convert to `float16` before shipping the file — it works
  everywhere, halves the file, and needs nothing special. Or read it raw, with no framework
  involved: `dict(deserialize(open(p, "rb").read()))` yields
  `{"dtype": "BF16", "shape": [...], "data": <bytes>}`, and
  `(np.frombuffer(data, np.uint16).astype(np.uint32) << 16).view(np.float32)` reconstructs
  the exact float32 values — verified equal to the originals. The cost is that `deserialize`
  takes bytes, so you read the whole file into RAM and lose the mmap entirely.
- **A non-contiguous numpy array is written as silent garbage.** There is no contiguity
  check anywhere: `_flatten` passes `tensor.ctypes.data` and `tensor.nbytes` straight
  through, so a strided view has `nbytes` bytes read raw from its base pointer. With
  `a = np.arange(12, dtype=np.float32).reshape(3, 4)`, `a[:, ::2]` goes in as
  `[[0,2],[4,6],[8,10]]` and comes back `[[0,1],[2,3],[4,5]]`; `a.T` comes back with the
  right shape and the wrong contents; `a[::-1]` reads past the end of the buffer and returns
  whatever was there. Nothing raises. `np.ascontiguousarray(x)` before `save_file` fixes all
  three; `assert x.flags.c_contiguous` gets you the error early. Upstream's docstring says
  tensors "need to be contiguous and dense", and nothing enforces it.
- **There is no checksum: the format is safe against code execution, not against bit rot.**
  A single flipped byte inside a tensor payload opens without complaint and hands you a wrong
  number — measured, the other tensors in the same file still matching perfectly. If a file
  can be damaged in transit or by a half-finished write, carry your own digest (see
  [Storage](#storage)) and check it before you trust the tensors.
- **Truncation, by contrast, is always caught — at `safe_open`, before any tensor is read.**
  So is every other structural defect: an empty file, three stray bytes, a header length with
  nothing behind it, a truncated header, a header with no tensor data, a file with its tail
  cut, one byte lopped off the end, a non-JSON header, an absurd header length. Each of the
  nine produces the same `SafetensorError` from `safe_open`, `keys()`, `get_tensor` and
  `load_file` alike, with one of five specific messages — `header too small`,
  `invalid header length`, `header too large` (the JSON header is capped at exactly
  100,000,000 bytes), `invalid JSON in header: …`, and, for anything truncated,
  `incomplete metadata, file not fully covered`. Hand-edited headers are rejected just as
  precisely: overlaps, gaps and a reversed offset pair give ``invalid offset for tensor `b` ``;
  a shape that disagrees with its byte length gives `invalid shape, data type, or offset`; a
  shape large enough to overflow gives `overflow computing buffer size from shape and/or
  element type`; and a header whose declared data simply runs past the end of the file is
  indistinguishable from a truncation, so it gives `incomplete metadata` too. This one is
  free — just open the file and let it throw.
- **Two exception families come out of the same call, and neither is an `OSError`.**
  Structural damage is `SafetensorError`, whose MRO is `SafetensorError → Exception →
  BaseException → object`; a missing path is a plain `FileNotFoundError`; a bfloat16 tensor
  is a numpy `TypeError`. So `except OSError` and `except SafetensorError` both miss cases.
  Catch broad `Exception` around every open and read and show `str(error)` — the Rust
  messages are specific and worth surfacing verbatim, since *"incomplete metadata, file not
  fully covered"* tells a user their download was truncated. This matters more in Flet than
  elsewhere: an unhandled exception in an event handler makes Flet send `SESSION_CRASHED`.
- **`backend="pread"` silently destroys laziness for slices**, which is a trap because it is
  otherwise the memory-cheaper backend. Fresh process per row, 512 MB file, 16 tensors of
  32 MB, peak RSS delta:

  | what you do | `mmap` (default) | `pread` |
  | --- | --- | --- |
  | `safe_open` | +0.1 MB | +0.1 MB |
  | …plus every name, shape and dtype | +0.1 MB | +0.2 MB |
  | …plus one 11 KiB row of one tensor | +0.1 MB | **+32.2 MB** |
  | one whole 32 MB tensor | +64.2 MB | +32.2 MB |
  | `load_file` (all 512 MB) | **+1024.3 MB** | +512.4 MB |
  | `numpy.load(open(p, "rb").read())` | +1024.2 MB | +1024.3 MB |

  Read the third row first: under `pread` a one-row slice materialises the entire tensor, so
  you pay 32 MB for 11 KiB. Leave the default `mmap` whenever you are slicing or reading a
  subset. The fifth row is the other half of the story — under `mmap` a full `load_file`
  peaks at **twice** the file, because the mapped pages go resident *and* the copy handed to
  numpy is a second allocation, so `backend="pread"` is the right choice for a deliberate
  whole-file load. And never call `safetensors.numpy.load(f.read())` on a file of any size:
  it has no mmap at all, and the backend argument cannot help it.
- **`safe_open` is O(header), not O(file).** Median over 15 runs: 0.018 ms on an 8 MB file
  and 0.022 ms on a 512 MB one — flat — against `load_file`'s 0.66 ms and 60.3 ms, which is
  linear. Reading every tensor's shape and dtype on top of the open adds under 0.005 ms.
  The same header read in pure Python — `struct.unpack("<Q", f.read(8))` then
  `json.loads(f.read(n))` — takes 0.018 ms, so a screen that lists candidate model files
  need not load the extension at all.
- **`framework=` takes exactly `numpy`, `np`, `pt`, `torch`, `tf`, `tensorflow`, `flax`,
  `jax`, `mlx`, `paddle`, and it is case-sensitive.** Anything else, `"NUMPY"` included, is
  `SafetensorError: framework … is invalid`; `None` is a `TypeError`. **With numpy
  installed** the unavailable ones do not fail uniformly: `pt`, `torch` and `paddle` raise
  `ModuleNotFoundError` from `safe_open` itself, while `tf`, `tensorflow`, `flax`, `jax` and
  `mlx` open fine and raise it at the first `get_tensor` — and `flax` names `jax`, not
  `flax`. **Without numpy** that split disappears: all ten raise at `safe_open`, and the
  seven that are not `pt`/`torch`/`paddle` name numpy rather than the framework you asked
  for, so `framework="mlx"` reports a missing numpy. Import `safetensors.numpy` explicitly
  (`from safetensors.numpy import save_file, load_file`); plain `import safetensors` does not
  pull numpy in.
- **Drop `device=` entirely.** Every value but `"cpu"` fails —
  `SafetensorError: Device mps is not supported for framework numpy`, likewise `cuda`,
  `cuda:0` and `0`; `"meta"` gives `device meta is invalid`. The Apple-silicon MPS fast path
  the upstream docstrings describe needs PyTorch, which cannot be installed here.
- **`keys()` is lexicographic, so `block.10` sorts before `block.2`.** `offset_keys()` and
  the raw header agree with it for files this library wrote, because `save_file` writes in
  sorted-name order — which means code assuming `keys()[-1]` is the last tensor in the file
  is wrong for any file with more than nine numbered blocks. Sort numerically yourself for
  display, and read `data_offsets` out of the header if you need a tensor's position in the
  file.
- **Tensors come back as copies, not writable windows onto the file.** `owndata` is `False`
  and the array's `base` is another ndarray, but writing to one leaves the file on disk
  unchanged.
- **Edge cases worth knowing once.** `save_file({})` and a zero-element array both round-trip
  cleanly; a 0-d numpy scalar does not — `np.float32(3.5)` raises
  `AttributeError: 'numpy.float32' object has no attribute 'ctypes'` from inside
  `safetensors/numpy.py`. Big-endian arrays are handled correctly: `numpy.py` byteswaps them
  into a keep-alive buffer first, and a `">f4"` array round-trips equal. Every numpy dtype
  numpy itself has works through `safe_open` and `load_file` — float64/32/16, int and uint in
  all four widths, bool and complex64 — and `complex128` is refused at save with a message
  naming the 20 dtypes the writer accepts. That list is not everything the format knows: the
  header parser also accepts the sub-byte codes `F6_E2M3` and `F6_E3M2`, 22 in all.
- **Size: about 420 KB to download, and 87–91% of it is the extension.**

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 412 KiB | 936 KiB | 824 KiB |
  | Android armeabi-v7a | 417 KiB | 895 KiB | 781 KiB |
  | Android x86_64 | 438 KiB | 1016 KiB | 904 KiB |
  | iOS arm64 (device) | 419 KiB | 1155 KiB | 1044 KiB |
  | iOS arm64 (simulator) | 427 KiB | 1164 KiB | 1052 KiB |
  | iOS x86_64 (simulator) | 449 KiB | 1199 KiB | 1087 KiB |

  Across Python 3.12, 3.13 and 3.14 the wheels for a given slice differ by at most 74 bytes.
  Of the 115 KB that is not the extension on Android arm64-v8a, **41 KB is a CycloneDX
  SBOM** under `dist-info/sboms/` and 11 KB is the licence; the Python layer is 47 KB, of
  which 42 KB is `torch.py`, `paddle.py`, `tensorflow.py`, `flax.py` and `mlx.py` — backends
  that cannot be installed on a phone — against `numpy.py`'s 5.5 KB. serious_python's mobile
  cleanup list carries `**.pyi` and `**.typed`, so the 9.7 KB stub that documents the whole
  API and the empty `py.typed` are dropped on the way into the app; the SBOM and the licence
  are not on that list and do ship. Import cost is negligible either way:
  `python -X importtime -c "import safetensors"` is 0.68–0.72 ms warm, essentially all of it
  the extension load.
- **`abi3` in the filename is cosmetic here.** The extension is
  `safetensors/_safetensors_rust.abi3.so` on both platforms, but the wheels are not
  interchangeable across Python versions — the cp312 Android slice needs `libpython3.12.so`
  and the cp314 one `libpython3.14.so`. The import itself resolves normally, since
  `.abi3.so` is a standard extension suffix.

## Build notes (maintainers)

`meta.yaml` is the whole recipe, its two non-obvious settings are commented in place, and
there is no `patches/` directory. The shape needs no defending — safetensors publishes an
sdist, builds with maturin, and the minimal Rust recipe worked for every ABI and both
platforms with zero patches, zero `excluded_arches` and no `requirements.host`. The ELF
confirms that last one is right rather than lucky: nothing links `libc++_shared.so`, so
there is no C++ runtime to declare.

What is left is the bump checklist, and a green build verifies almost none of what this page
promises.

- **No on-device run backs a single number above.** Every behavioural figure — the memory
  table, the GIL table, the timings, the dtype and corruption matrices — came off a desktop
  install of exactly `safetensors==0.8.0` plus `numpy==2.4.6`. The bridge is narrow but real:
  all seven shipped `.py` files and the `.pyi` stub hash identically across the Android
  wheel, the iOS wheel and the desktop PyPI wheel of the same version, and everything else
  lives in one Rust source tree compiled per slice. Anything about linkage, sizes and slices
  came off the wheels themselves. The [`lazy-weights`](examples/lazy-weights) example exists
  to put the memory and timing figures on a real screen, which is the thing to run after a
  bump.
- **`tests/test_safetensors.py` covers the bytes API and one numpy `safe_open` round trip,
  and nothing else.** It does not touch `backend=`, corruption, bfloat16, contiguity,
  `metadata()` or `get_slice`, all of which [Things to know](#things-to-know) makes claims
  about. Worth adding, in rough order of value: a `backend="pread"` round trip, a truncated
  file asserting the `incomplete metadata` message, and a bf16 header asserting the
  `TypeError` — after which three of this page's louder claims would turn CI red rather than
  rotting quietly. Note that `test.requires: [numpy]` is what makes the numpy test runnable
  on device at all, and that `SMOKE_TEST_PACKAGES` is only the fallback recipe list, so
  absence from it says nothing about whether the test ran.
- **Re-check the extras, not just the build.** That `safetensors` installs one wheel and
  nothing else is a property of upstream's `METADATA`, and a future release could add an
  unconditional dependency — at which point forge starts rewriting `Requires-Dist` on Android
  and the byte-identical `METADATA` noted in [iOS notes](#ios-notes) stops being true. The
  404 status of torch/jax/flax/paddlepaddle/mlx/tensorflow on pypi.flet.dev is likewise
  someone else's business and could change.
- **The dtype tables are upstream's and they move.** The 13-entry `_TYPES` dict in
  `safetensors/numpy.py` is what makes bfloat16 unreadable, and the 20-name list in the
  "Unknown dtype" message is what makes `complex128` unwritable. Both are quoted above; both
  are one upstream commit from being wrong. Re-read them from the built wheel — and note the
  two disagree with the Rust enum, which the binary's own panic string still puts at 22
  variants (`strings … | grep 'variant index'`).
- **The error strings are quoted verbatim**, and upstream rewords them. So are the accepted
  `framework=` and `backend=` values and the 100,000,000-byte header cap.
- **The sizes, the linkage and the Mach-O flags are measured.** Re-measure rather than
  adjusting by eye — in particular, `otool -hv` reporting `DYLIB` on all three iOS slices is
  what keeps [iOS notes](#ios-notes) honest, and the 16 KB `PT_LOAD` alignment on all three
  Android ABIs is what keeps the wheel installable on Android 15. Open **every** slice, not
  one per platform: the crate counts quoted at the top of this page are 33/34/35, because
  armeabi-v7a alone pulls `portable-atomic` in, and a two-binary comparison misses that.
- **Bump the example's pins with the recipe.** `examples/lazy-weights/pyproject.toml` pins
  `safetensors`, `numpy` and `flet` with `==`, and `requires-python = ">=3.11"` is the floor
  numpy 2.4.6 forces — verified by copying that file alone into an empty directory and
  running `uv lock`, which resolves at `>=3.11` and fails at `>=3.10`. Moving numpy may move
  that floor.
