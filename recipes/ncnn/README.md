# ncnn

[`ncnn`](https://github.com/Tencent/ncnn) is Tencent's neural-network inference engine, written for
phones first and ported to desktops afterwards. You hand it a
[`.param`/`.bin` pair](https://github.com/Tencent/ncnn/wiki/param-and-model-file-structure) — a
plain-text graph and its raw float32 weights — and it hands back a `Net` whose `Extractor` turns
numpy arrays into numpy arrays. It runs on the CPU, brings its own threading, and nothing on the
inference path touches the network.

It is the third inference engine on this index. Reach for it over [`onnxruntime`](../onnxruntime),
which takes a model any exporter can produce, or [`tflite-runtime`](../tflite-runtime), when the
model is already in ncnn format, when you want to write the graph yourself, or when the native
footprint decides it — the Android arm64 extension here is about 6.7 MB against onnxruntime's
22 MB on the same ABI. For text generation, [`llama-cpp-python`](../llama-cpp-python) is built for
that job.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "ncnn",
]
```

Wheels cover every slice a [`flet build`](https://flet.dev/docs/publish/) can produce: all three
Android ABIs (arm64-v8a, armeabi-v7a, x86_64) and all three iOS slices (device, arm64 simulator,
x86_64 simulator), on Python 3.12, 3.13 and 3.14.

The wheel's own `Requires-Python` is `>=3.5`, but the numpy that resolves behind it on
pypi.flet.dev declares `>=3.11`. If you pin ncnn with `==`, raise your `requires-python` to
`>=3.11` in the same edit, or the resolve fails naming numpy with nothing to connect it to the line
you just changed. Check it the way a consumer meets it: copy the `pyproject.toml` alone into an
empty directory and run `uv lock` there.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`written-model`](examples/written-model) — a conv net written by the app at runtime, run on
  device and checked against numpy.

## Usage in a Flet app

Load the model once, keep the `Net`, and run it per frame:

```python
net = ncnn.Net()                     # keep this on self or a module global, not per tap
net.load_param(param_path)
net.load_model(bin_path)

x = np.ascontiguousarray(frame, dtype=np.float32)  # named: the Mat will not keep it alive
ex = net.create_extractor()
ex.input("x", ncnn.Mat(x))
code, mat = ex.extract("y")

result = np.array(mat) if code == 0 else None      # np.array of a failed Mat segfaults
score.value = f"{result.max():.3f}" if result is not None else f"ncnn returned {code}"
```

Each of those three comments is a crash averted, and each has a bullet in
[Things to know](#things-to-know).

### Storage

A model is two ordinary files, and `Net` takes paths:

```python
directory = os.getenv("FLET_APP_STORAGE_DATA", ".")
net.load_param(os.path.join(directory, "net.param"))
net.load_model(os.path.join(directory, "net.bin"))
```

Put a model you downloaded or generated in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, included in backups, never auto-deleted.
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
may be purged under storage pressure and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
may vanish between launches, so use either only for a model you can cheaply fetch or regenerate. To
ship a model with the build, put the pair in the
[assets directory](https://flet.dev/docs/cookbook/assets) and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir), which
is read-only and replaced on every app update. Inference itself writes nothing.

### Model files

Models are converted on a laptop — [pnnx](https://github.com/pnnx/pnnx) from PyTorch, or the
[PyTorch/ONNX converters](https://github.com/Tencent/ncnn/wiki/use-ncnn-with-pytorch-or-onnx) — and
only the forward pass ships. Nothing in the mobile wheel trains or converts.

**A model does not have to be a file.** `net.load_param_mem(param_text)` returns `0` and
`net.load_model_mem(weight_bytes)` returns `None` — the memory variants are `void` where the file
variants return an `int`, so there is nothing to check on the second — and the graph then runs
exactly as if it had come off disk, to the last bit. A model in a database column, in a preferences
blob, or generated at startup never has to touch the filesystem, and the format is simple enough
that an app can write one itself, which is what the example does.

**`ncnn.model_zoo` cannot work in a self-contained app.** It downloads from GitHub at call time
into `os.path.expanduser("~/.ncnn/models")`, and `ncnn.utils` goes with it. Convert your model on a
laptop and ship or write it instead.

### Threading

**`ex.extract(...)` holds the GIL for its whole computation**, and so does loading a model. A
canary thread recorded the longest gap between its own iterations while each call ran — a canary
that never gets a turn is a UI thread that never gets a frame. The first two rows are the harness
checking itself; median of five, desktop CPython 3.12 on a 10-core host, ncnn pinned to one thread
so CPU contention could not be mistaken for the GIL:

| call | duration | longest canary stall | stall ÷ call |
| --- | ---: | ---: | ---: |
| `hashlib.sha256` of 600 MB (releases the GIL) | 230 ms | 5.9 ms | 0.03 |
| `sum(range(30_000_000))` (holds it) | 218 ms | 212.9 ms | 0.98 |
| one `ex.extract` of a 102 GFLOP conv stack | 183 ms | 175.0 ms | **0.96** |
| `load_param` + `load_model` of an 84 MB `.bin` | 18 ms | 16.0 ms | **0.91** |

[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is still the
right shape — it keeps the handler from blocking Flet's event dispatch — but it is **not** a
responsiveness guarantee here. Size the work so one `extract` is tens of milliseconds, and set the
spinner and the disabled states *before* starting the worker rather than expecting a change made
inside it to reach the screen while it runs. Wrap the body in `try/except Exception`, since
`run_thread` never retrieves the worker's future and an exception raised inside one surfaces
nowhere at all, and end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), which auto-update does
not do for a background thread.

**`opt.num_threads` is the one knob, and its default is already the right answer.** Upstream sets
it to `get_physical_big_cpu_count()`, which is where the curve peaks. A 25 GFLOP conv stack,
desktop M4 with 4 performance and 6 efficiency cores, median of a 1.5 s loop:

| `num_threads` | 1 | 2 | 3 | 4 | 6 | 8 | 10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| median | 43.2 ms | 25.0 ms | 23.0 ms | 22.5 ms | 22.5 ms | 28.8 ms | 92.8 ms |
| vs 1 thread | 1.00x | 1.73x | 1.88x | 1.92x | 1.92x | 1.50x | **0.47x** |

Past the big-core count it goes backwards, and at one thread per logical core it is **worse than
single-threaded** — the shape a lock-step parallel region takes across cores that finish at very
different speeds, which is what a phone is too. Raising this above the default is the single change
most likely to make an app slower. The example times whichever setting you pick against one thread,
so you can walk the same curve on your own handset.

**How much work the knob shares out is the same on both platforms; how many OS threads that costs
is not.** Android gives you `num_threads` threads and no more. iOS spawns
`ncnn.get_cpu_count() - 1` workers at the first parallel region and keeps them for the life of the
process, and `opt.num_threads` then decides how many of them a region wakes: lowering it there
makes fewer threads *work*, not fewer threads *exist*. Budget for a full-width pool on iOS if you
are counting threads or stacks. That one is read out of upstream's C++ rather than measured on a
phone — the example is the way to check it.

**`OMP_NUM_THREADS` does nothing, on either platform.** Every one of ncnn's parallel regions
carries an explicit `num_threads(opt.num_threads)` clause and not one is bare, and that clause
outranks the environment; setting the variable to 1, 2 and 8 moved neither the wall clock nor the
OS thread count.

`ncnn.set_cpu_powersave(0 | 1 | 2)` — all cores, little clusters only, big clusters only — is
present on every slice and is process-global rather than per-`Net`. Upstream's `src/cpu.h` says the
affinity binding behind it is implemented on Android only, and warns that switching it is expensive
and not thread-safe.

### App size

| slice | wheel | unpacked | the extension alone |
| --- | ---: | ---: | ---: |
| Android arm64-v8a | 2.7 MB | 6.8 MB | 6.7 MB |
| Android armeabi-v7a | 1.7 MB | 3.9 MB | 3.8 MB |
| Android x86_64 | 6.7 MB | 17.5 MB | 17.3 MB |
| iOS device arm64 | 2.2 MB | 4.9 MB | 4.8 MB |
| iOS simulator arm64 | 2.1 MB | 4.7 MB | 4.6 MB |
| iOS simulator x86_64 | 6.2 MB | 14.6 MB | 14.4 MB |

**x86_64 is 2.6x the size of arm64**, so an APK measured on an emulator badly overstates what
reaches a phone. On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the app
does not need every ABI; all three are published, so the choice is yours to make on size.

ncnn is the small part of what installing it costs. Its `Requires-Dist` names `numpy`, `tqdm`,
`requests`, `portalocker` and **`opencv-python`**, and `import ncnn` reaches none of them — it is
`ncnn.model_zoo` and `ncnn.utils` that pull numpy and cv2 in. Resolving the way `flet build` does:

| target | install closure | of which opencv-python | of which ncnn |
| --- | ---: | ---: | ---: |
| Android arm64-v8a | 25.1 MB | 14.4 MB | 2.7 MB |
| Android armeabi-v7a | 22.0 MB | 12.8 MB | 1.7 MB |
| Android x86_64 | 33.6 MB | 17.5 MB | 6.7 MB |
| iOS device arm64 | 23.4 MB | 13.9 MB | 2.2 MB |

Nothing at the `pyproject.toml` level takes those out — `Requires-Dist` is baked into the wheel —
so an app that ships or writes its own model still pays about 20 MB for helpers it never imports.
If that matters, [`opencv-python`](../opencv-python) at least earns its place the moment you decode
an image.

### Other considerations

**The arm kernels are the same on both platforms**, which is worth knowing precisely because
its neighbour is not: [`onnxruntime`](../onnxruntime)'s iOS slices carry no i8mm at all, where
its Android ones do. ncnn's do not differ — `fmla` counts 7,397 on iOS against 7,403 on
Android, and `smmla`/`ummla` (110) and `bfmmla` (216) match exactly. So an int8 workload that
loses its wide kernels when moved to iOS keeps them here.

A desktop `flet run` uses PyPI's own ncnn wheel, and it is not the same build. It carries the
twenty Vulkan names the mobile slices do not, so `ncnn.get_gpu_count()` exists there and code
written against it fails on device with `AttributeError`; its `ncnn.__version__` reports the
release date rather than the day the extension was compiled; and it links the same OpenMP runtime
Android does, so a thread count measured at your desk matches Android and not iOS. The API, the
layer set, the fp16 defaults and the return codes are the same, so those three are what to re-check
on a device.

## Things to know

- **`ncnn.Mat(array)` does not keep `array` alive, and reading a dead one is silent.** The
  constructor takes no reference, so the Mat is left pointing at a buffer Python may reuse. The
  realistic shape is one expression —
  `ex.input("x", ncnn.Mat(np.ascontiguousarray(frame, np.float32)))` — where the temporary dies
  before `extract` ever runs and what comes back is whatever landed in the freed buffer, with a `0`
  return code. Bind the input array to a name that outlives the call. Outputs run the other way:
  `mat.numpy()` and `np.asarray(mat)` are views of a buffer owned by the `Net`'s pool allocator,
  while `np.array(mat)` copies. Take the copy before you release the `Net`, and keep the `Net` in
  an attribute for the app's lifetime rather than rebuilding it per tap.

- **Anything that is not float32 is accepted and then goes wrong.** `ncnn.Mat` takes a float64,
  int32 or uint8 array without complaint and then reads the bytes as float32. float64 **kills the
  process** — SIGBUS, with no Python exception to catch — while int32 and uint8 return nonsense
  with a `0` return code: zeros, NaN or plausible finite garbage depending on the values, so there
  is no signature to test for. numpy's default float dtype *is* float64, so `np.zeros(n)`,
  `np.array([...])` and most arithmetic produce exactly the array that crashes.
  `np.ascontiguousarray(x, dtype=np.float32)` on the way in is not optional.

- **Nothing raises. Every failure is a negative return code and a line on stderr — and the natural
  next line then crashes the app.** A missing or malformed `.param`, a missing `.bin` and a typo'd
  blob name are all `-1`; an `extract` whose input was never set is `-100`. A failed `extract` hands
  back an **empty** Mat — `dims`, `w`, `h`, `c` and `elemsize` all zero — and `np.array(that)`
  **segfaults the process**, while `that.numpy()` at least raises `RuntimeError`. Check the code
  *before* you touch the Mat. On device the stderr messages land in logcat or `console.log` where a
  user never sees them, so put the code on screen too.

- **The defaults do fp16 arithmetic, so ncnn does not agree with float32 numpy out of the box — and
  the flags are a load-time decision.** `use_fp16_packed`, `use_fp16_storage` and
  `use_fp16_arithmetic` are all true by default. Against a numpy float32 reference, relative to the
  largest output: a 3-layer 3x3 conv stack over 1x128x128 differs by **5.6e-02** with the defaults
  and by 7.5e-06 with the three off; a 3-layer MLP, ~1e-03 against ~1e-07. A cross-check written to
  a float32 expectation looks broken when nothing is wrong. Turning them off costs memory as well
  as speed: an 84 MB float32 `.bin` cost about 60 MB of resident memory to load with fp16 on and
  about 100 MB with it off. Set them **before `load_param`** — turning them off after `load_model`
  poisons the output with NaN and still returns `0`, so a partial answer can look survivable, and
  turning them on there kills the process with SIGSEGV. Build one `Net` per configuration and keep
  it. On armeabi-v7a there is less behind `use_fp16_arithmetic` to begin with: the armv8.2 fp16
  kernels are gated on aarch64, so 32-bit ARM has NEON but not that kernel family.

- **In a `.param` line the first name is the layer and the names after the two counts are blobs**,
  and `ex.input()`/`ex.extract()` take blob names. `Input in 0 1 x` declares a layer called `in`
  producing a blob called `x`; asking for `in` fails, and ncnn even prints the name it wanted.
  Print `net.input_names()` and `net.output_names()` after `load_param` — they return the blob
  names and are the authoritative answer.

- **CPU only, on both platforms — there is no GPU path, not even a disabled one.** Twenty public
  API names are absent from all six mobile slices against the desktop wheel of the same release,
  and every one is Vulkan: `get_gpu_count`, `get_gpu_device`, `VulkanDevice`, the `Vk*Allocator`
  and `Vk*Memory` types, `Net.set_vulkan_device` and the rest. The other 165 are present
  everywhere. `opt.use_vulkan_compute` survives as a settable bool with nothing behind it.

- **All 110 upstream layer types are compiled in, on every slice**, the modern set included —
  `Gemm`, `MatMul`, `MultiHeadAttention`, `SDPA`, `LayerNorm`, `RMSNorm`, `GRU`, `LSTM`,
  `RotaryEmbed`, `Einsum`, `GridSample`, `DeformableConv2D`, `Spectrogram`. Nothing was trimmed for
  size.

- **`ncnn.__version__` is the date the extension was compiled, not the version you installed**,
  because upstream derives that string from a build-time timestamp. The two disagree on every
  mobile slice. Read `importlib.metadata.version("ncnn")` when you need the installed version.

- **`import ncnn` sets two OpenMP environment variables in your process**, `KMP_AFFINITY=disabled`
  and `KMP_DUPLICATE_LIB_OK=1`, from a library constructor, before any of your code runs. The first
  keeps LLVM's OpenMP from aborting when `sched_getaffinity` fails, which happens on Android when a
  core goes offline in powersave mode; the second is why an app can carry ncnn *and* another
  OpenMP-using wheel instead of dying on import. It is still a process-wide mutation you did not
  make, and whichever library loads first wins it.

- **Budget about 11 MB of resident memory for `import ncnn` itself**, before any model. Staged on a
  desktop with `resource.getrusage(...).ru_maxrss` — indicative, not device evidence — that ran
  about 18 MB at baseline, 30 MB after `import numpy` and 41 MB after `import ncnn`, then whatever
  the weights cost: an 84 MB float32 `.bin` took it to about 100 MB. Weights dominate, and with
  fp16 on they cost roughly half the file.

## Build notes (maintainers)

### Recipe shape

The plain pybind11 shape. Upstream's `setup.py` drives CMake itself, so there is no PEP 517 shim
and no companion native-library recipe — one extension, one patch, no `host_build` chain. The
Android wheel picks up `flet-libcpp-shared` for `libc++_shared.so`; the iOS one needs no equivalent
because the OS ships `libc++`.

One cosmetic defect, recorded so a metadata audit does not chase it: the Android wheels' `METADATA`
loses the long description when forge appends the `flet-libcpp-shared` requirement — 1,585 bytes
ending at `Requires-Dist:` with no body, against 28,501 bytes on the iOS wheel of the same build.
Nothing on device reads it.

### Upgrade hazards

- **The version-date patch.** A new sdist means a new build date, and if the patch is not updated
  alongside the version in `meta.yaml` the build stays green while the wheel version stops matching
  the recipe. The *extension's* `__version__` is a separate value that nothing pins.
- **`NCNN_VULKAN=OFF` wins on argument order, not on merit.** Upstream's `setup.py` force-enables
  Vulkan, and the override only takes effect because `EXTRA_CMAKE_ARGS` is appended after its own
  list. A change to how `setup.py` assembles that list turns the CPU-only claim false with a green
  build and no failing test.
- **Upstream adds layers regularly.** The claim above is that nothing was trimmed, not that the
  number is 110, so recount from `src/CMakeLists.txt` rather than carrying the figure forward.

### Re-verification checklist

- **The `Option` defaults.** `num_threads` and the three fp16 flags come from upstream's
  `src/option.cpp`, and both the threading advice and the fp16 agreement figures rest on them.
- **The Vulkan diff and the layer sweep**, both of which need the desktop wheel of the *same*
  release as their control. Without one, a scan that finds nothing proves nothing.
- **The two thread-accounting facts, which no test covers and no measurement here can see.**
  `OMP_NUM_THREADS` is inert because every parallel region names `num_threads(opt.num_threads)`
  (`grep -c 'pragma omp parallel for num_threads'` over `src/` against the bare-pragma count: 3306
  and 0 today), and iOS holds a `get_cpu_count() - 1` pool whatever `num_threads` says
  (`KMPGlobal::init()` in `src/simpleomp.cpp`). Both are read out of upstream C++, so a bump can
  flip either with a green build.
- **`Requires-Dist`.** Five packages, `opencv-python` much the largest. If upstream ever moves the
  model-zoo extras behind a marker the install-closure table changes — and it would be worth
  reconsidering whether the recipe should strip them, since nothing on the import path uses any.
- **The sizes.** The per-slice table came off the cp314 wheels; the install closure came off a
  `pip download --only-binary=:all: --extra-index-url https://pypi.flet.dev/ --platform … --abi
  cp314`. Measure with `stat`/`unzip -l` and divide by 10⁶ — `du -h` reports binary units and the
  difference reads as a regression. The install-closure figures in this revision were converted
  from an earlier binary-unit measurement rather than re-measured; re-measure at the next bump.
- **Every behavioural figure above** — the GIL table, the thread sweep, the fp16 agreement, the
  memory staging, the dangling-`Mat` and dtype failures — came off a desktop install of the same
  ncnn release from PyPI, not off a device. What carries over is the code, not the clock: the
  shipped `.py` files are byte-identical across all six mobile slices, one C++ tree builds every
  one of them, and the two things that genuinely differ are called out where they matter. Run the
  [`written-model`](examples/written-model) example after a bump to read them off a phone instead.

### Coverage gaps

`tests/test_ncnn.py` covers three things and this page claims a dozen: the `Mat`/numpy round trip,
one weightless graph through the full `Net`/`Extractor` machinery, and `get_cpu_count() >= 1`.
Nothing there covers the fp16 agreement, the dtype trap, the dangling-`Mat` lifetime, the
fp16-flag-after-load failure, or the return codes — all consumer-facing claims a bump could break
silently, and all cheap to assert. `test_cpu_info` is also the one test in the file without a
docstring, against this repo's convention; worth fixing at the next touch.
