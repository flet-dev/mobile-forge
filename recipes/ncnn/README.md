# ncnn

[`ncnn`](https://github.com/Tencent/ncnn) is Tencent's neural-network inference engine, written
for phones first and ported to desktops afterwards. You hand it a
[`.param`/`.bin` pair](https://github.com/Tencent/ncnn/wiki/param-and-model-file-structure) — a
plain-text graph and its raw float32 weights — and it gives you a `Net` whose `Extractor` turns
numpy arrays into numpy arrays. Nothing in the inference path reaches the network.

The wheel is one extension module of 3.6–16.5 MB plus 130 KB of Python, and the native half links
nothing but the platform: `/usr/lib/libSystem.B.dylib` and `/usr/lib/libc++.1.dylib` on iOS, the
NDK's own libraries on Android. Models come from [pnnx](https://github.com/pnnx/pnnx) or the
[PyTorch/ONNX converters](https://github.com/Tencent/ncnn/wiki/use-ncnn-with-pytorch-or-onnx) on a
laptop; only the forward pass ships. The format is simple enough that an app can also write a
working model at runtime with no asset file at all, which is what the example does.

It is the third inference option on this index, beside [`onnxruntime`](../onnxruntime) — which
takes a model any exporter can produce — and [`tflite-runtime`](../tflite-runtime). Reach for ncnn
when the model is already in ncnn format, when you want to write the graph yourself, or when the
native footprint matters: its Android arm64-v8a extension is 6,657,232 bytes against
onnxruntime's 22,063,880 on the same ABI. For text-generation models,
[`llama-cpp-python`](../llama-cpp-python) is the one built for that job.

What it is **not** here is a route to the phone's GPU. `NCNN_VULKAN` is off in all six mobile
slices — see [Things to know](#things-to-know) — so everything runs on CPU and NEON.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "ncnn",
]
```

Nothing else to configure. Wheels exist for **every slice a `flet build` can produce** — all three
Android ABIs (arm64-v8a, armeabi-v7a, x86_64) and all three iOS slices (device, arm64 simulator,
x86_64 simulator), on Python 3.12, 3.13 and 3.14 — so unlike [`onnxruntime`](../onnxruntime) no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) narrowing is
forced on you.

**Five packages come along and `import ncnn` uses none of them.** The wheel's `Requires-Dist` names
`numpy`, `tqdm`, `requests`, `portalocker` and **`opencv-python`**, and every one of them is
reached only from `ncnn.model_zoo` and `ncnn.utils`, neither of which the package `__init__`
touches — it is two lines long, `from .ncnn import *` and a `__version__`. Checked in a fresh
interpreter: `import ncnn` adds exactly `ncnn`, `ncnn.ncnn` and `atexit` to `sys.modules`, with
`numpy`, `cv2` and `requests` all still absent; `import ncnn.model_zoo` is what pulls numpy and cv2
in. Resolving
the way `flet build` does (`pip download --only-binary=:all: --extra-index-url
https://pypi.flet.dev/ --platform … --abi cp314`) that costs:

| target | wheels | total | of which opencv-python | of which ncnn |
| --- | --- | --- | --- | --- |
| Android arm64-v8a | 11 | 23.98 MB | 13.76 MB | 2.57 MB |
| Android armeabi-v7a | 11 | 20.96 MB | 12.22 MB | 1.65 MB |
| Android x86_64 | 11 | 32.07 MB | 16.66 MB | 6.43 MB |
| iOS device arm64 | 10 | 22.34 MB | 13.26 MB | 2.08 MB |

Nothing at the `pyproject.toml` level removes them — `Requires-Dist` is baked into the wheel. An
app that writes or ships its own model pays ~20 MB for helpers it never imports; if that matters,
[`opencv-python`](../opencv-python) at least earns its place the moment you decode an image.
On Android an eleventh wheel, `flet-libcpp-shared`, is pulled in behind ncnn and needs no entry of
its own (see [Android notes](#android-notes)).

No [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is needed.
Both conditions hold: there is no `__file__`, `importlib.resources`, `pkg_resources`, `pkgutil` or
`getsource` anywhere in the wheel's Python layer, and no data file to find — 34 files per wheel, of
which 28 are `.py`, one is the extension and five are metadata — and the Android extension carries
a CPython ABI tag (`ncnn/ncnn.cpython-314.so`), which is what lets Android's zipped site-packages
find it. The iOS one is plain `ncnn/ncnn.so`.

**`Requires-Python` in the wheel is `>=3.5` and imposes nothing**, but the resolved set does:
pypi.flet.dev publishes numpy only for cp312/cp313/cp314, and the numpy that resolves (2.4.6)
declares `>=3.11`. So if you pin ncnn with `==`, raise `requires-python` to at least `>=3.11`
alongside it — and check it the way a consumer meets it, by copying the `pyproject.toml` alone into
an empty directory and running `uv lock` there.

## Storage

A model is two ordinary files and `Net` takes paths:

```python
directory = os.getenv("FLET_APP_STORAGE_DATA", ".")
net = ncnn.Net()
net.load_param(os.path.join(directory, "net.param"))
net.load_model(os.path.join(directory, "net.bin"))
```

Put a model you downloaded or generated in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, included in backups, never auto-deleted. Never in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) unless you can cheaply fetch it again. To ship a model with the
build, put the pair in your app's `src/assets/` and read them from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir), which
is read-only and replaced on every app update.

**No file at all is also supported.** `net.load_param_mem(param_text)` returns `0` and
`net.load_model_mem(weight_bytes)` returns `None` — the memory variants are `void` where the file
ones return an `int` — and the graph then runs exactly as if it had been loaded from disk (verified
against a hand-written model: same output, to the last bit). A model held in a database column, a
preferences blob, or generated at startup never has to touch the filesystem.

**`ncnn.model_zoo` is a network path and cannot work in a self-contained app.**
`model_zoo/model_store.py` downloads from `https://github.com/nihui/ncnn-assets/raw/master/models/`
at call time into `os.path.expanduser("~/.ncnn/models")`, via `requests.get` in
`utils/download.py`. It is also the only reason `cv2`, `requests`, `tqdm` and `portalocker` are
dependencies. Convert your model on a laptop and ship or write it instead.

Inference itself writes nothing.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`written-model`](examples/written-model) — a conv net written by the app at runtime, run on
  device and checked against numpy.

## Threading

**`ex.extract(...)` holds the GIL for its whole computation.** That is the opposite of
[`onnxruntime`](../onnxruntime#threading), and it changes what a worker thread buys you. Measured
with a canary thread recording the longest gap between its own iterations while the call runs — a
canary that never gets a turn is a UI thread that never gets a frame — with ncnn pinned to one
thread so CPU contention could not be mistaken for the GIL. The first two rows are the harness
checking itself. Median of five, desktop CPython 3.12 on a 10-core host:

| call | duration | longest canary stall | stall ÷ call |
| --- | --- | --- | --- |
| `hashlib.sha256` of 600 MB (releases) | 230 ms | 5.9 ms | 0.03 |
| `sum(range(30_000_000))` (holds) | 218 ms | 212.9 ms | 0.98 |
| one `ex.extract` of a 102 GFLOP conv stack | 183 ms | 175.0 ms | **0.96** |
| `load_param` + `load_model` of an 84 MB `.bin` | 18 ms | 16.0 ms | **0.91** |

Both ncnn calls sit with the control that holds. The bindings confirm it: there is not one
`gil_scoped_release` or `call_guard` in `python/src/main.cpp`.

[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is still the
right shape — it keeps the handler from blocking Flet's event dispatch, and it is where the
disable-the-control-while-it-runs pattern lives — but it is **not** a responsiveness guarantee
here. Size the work so a single `extract` is tens of milliseconds, and set the spinner and the
disabled states *before* starting the work rather than expecting the UI to keep updating during
it. Whether Flutter's own render thread keeps animating while the Python GIL is held is not
something this page can answer; the example is built so you can watch it on a device.

The two standing Flet caveats apply either way: `run_thread` never retrieves the worker's future,
so an exception raised inside one surfaces nowhere at all — wrap the body in
`try/except Exception` — and auto-update does not reach background threads, so end the handler with
an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**`opt.num_threads` is the one knob, and its default is already the right answer.** Upstream's
`src/option.cpp` sets it to `get_physical_big_cpu_count()`, which is where the curve peaks. A 25
GFLOP conv stack, desktop M4 with 4 performance and 6 efficiency cores, median of a 1.5 s loop:

| `num_threads` | 1 | 2 | 3 | 4 | 6 | 8 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| median | 43.2 ms | 25.0 ms | 23.0 ms | 22.5 ms | 22.5 ms | 28.8 ms | 92.8 ms |
| vs 1 thread | 1.00x | 1.73x | 1.88x | 1.92x | 1.92x | 1.50x | **0.47x** |

Past the big-core count it goes backwards, and at one thread per logical core it is **worse than
single-threaded** — the shape you would expect from a lock-step parallel region spread across cores
that finish at very different speeds, which is what a phone is too. On this host `get_cpu_count()`
is 10, `get_big_cpu_count()` 4, `get_little_cpu_count()` 6, `get_physical_big_cpu_count()` 4, and a
fresh `ncnn.Net().opt.num_threads` reads back 4. The example times whichever setting you pick
against one thread, so you can walk the same curve on your own handset instead of trusting this
one.

**How much work the knob shares out is the same on both platforms; how many OS threads that costs
is not**, because the two ship different OpenMP runtimes. Android's statically linked LLVM libomp
gives you `num_threads` threads and no more — `ps -M` on the desktop wheel, which links that same
runtime, counts exactly `num_threads` at every setting. iOS's `NCNN_SIMPLEOMP` sizes its pool off
the machine instead: `KMPGlobal::init()` in upstream's `src/simpleomp.cpp` spawns
`ncnn::get_cpu_count() - 1` workers at the **first** parallel region and keeps them for the life of
the process, and `opt.num_threads` then decides how many of them a region wakes. Lowering it on iOS
makes fewer threads *work*; it does not make fewer threads *exist*. Nothing here has run that on a
phone — it is read off the source and off the `pthread_once`/`pthread_create` imports that put
`simpleomp.cpp` in the binary (see [iOS notes](#ios-notes)) — but budget for a full-width pool
there if you are counting threads or stacks.

**`OMP_NUM_THREADS` does nothing, on either platform.** Every one of ncnn's 3,306 parallel regions
carries an explicit `num_threads(opt.num_threads)` clause and not one is bare, and that clause
outranks the environment. Checked against the libomp runtime with the variable set to 1, 2 and 8:
the wall clock and the OS thread count both tracked `opt.num_threads` alone and ignored it every
time. The string is in the Android binaries and not the iOS ones only because libomp links its own
env-var table; that means libomp parses the name, not that ncnn obeys it. `opt.num_threads` is the
knob, and it is the only one.

`ncnn.set_cpu_powersave(0 | 1 | 2)` — all cores, little clusters only, big clusters only — is
present on every slice and is process-global rather than per-`Net` (it returned `0` and read back
through `get_cpu_powersave()` at each setting), but upstream's `src/cpu.h` says the affinity
binding behind it is *only implemented on android at the moment*, and warns that switching it is
expensive and not thread-safe.

## Android notes

The extension's `DT_NEEDED` is `libpython3.xx.so`, `libandroid.so`, `libjnigraphics.so`,
`liblog.so`, `libm.so`, **`libc++_shared.so`**, `libdl.so` and `libc.so`, identical on all three
ABIs, with `BIND_NOW` and no `RPATH` or `RUNPATH`. The C++ runtime is why the Android wheels carry
an extra `Requires-Dist: flet-libcpp-shared (>=27.2.12479018)` that the iOS wheels do not; it rides
along on its own and needs no configuration. The three Android-specific libraries come from
upstream's `src/CMakeLists.txt`, which adds `mat_pixel_android.cpp` and links `android jnigraphics
log` on every Android build — that is ncnn's Android `Bitmap` conversion path, and the Python
bindings expose none of it (`android` appears zero times in `python/src/main.cpp`), so from a Flet
app those three are link-time weight and nothing more.

**The full LLVM OpenMP runtime is statically linked into the extension.** `llvm-nm -D` on the
arm64-v8a slice lists 1,313 exported symbols, of which 910 are `__kmp*`, 97 `omp_*` and 8 `ompt_*`,
with no `libomp.so` in `DT_NEEDED` and no undefined `omp_` symbols at all. That runtime is what
gives Android the `num_threads`-and-no-more thread count described in [Threading](#threading), and
it brings its own environment-variable table with it — `OMP_NUM_THREADS` is a string in all three
Android slices and in none of the iOS ones for that reason alone, and setting it still changes
nothing.

**`import ncnn` sets two environment variables**, and this is the platform where they matter.
`KMP_AFFINITY=disabled` and `KMP_DUPLICATE_LIB_OK=1` are set from a library constructor — upstream
`src/cpu.cpp`, `ncnn_kmp_env_initializer()`, guarded by `#if defined(_OPENMP) && (__clang__ || …)`,
with both strings present in every mobile slice. Upstream's own comments say why: LLVM's OpenMP
aborts when `sched_getaffinity` fails, which happens on Android when a core goes offline in
powersave mode, and it also aborts when it detects a second statically linked OpenMP. The second
setting is what lets ncnn coexist with another OpenMP-using wheel rather than killing the app.

All three `PT_LOAD` segments are 16 KB-aligned (`align 0x4000`) on every ABI, which Android 15
requires. Runtime CPU dispatch reads the kernel: `/proc/cpuinfo`, `/proc/self/auxv` and
`/sys/devices/system/cpu/cpu%d/{cpufreq/cpuinfo_max_freq, regs/identification/midr_el1,
topology/core_cpus_list, cache/index%d/*}` are all in the binary.

| slice | wheel | unpacked | the `.so` alone |
| --- | --- | --- | --- |
| arm64-v8a | 2,693,794 | 6,798,392 | 6,657,232 |
| armeabi-v7a | 1,731,753 | 3,908,522 | 3,767,360 |
| x86_64 | 6,737,305 | 17,489,478 | 17,348,320 |

**armeabi-v7a has NEON but no armv8.2 fp16 path**, so `use_fp16_arithmetic` has far less behind it
there. Upstream gates that kernel family (`NCNN_ARM82`) on aarch64 only, and the binaries agree:
760 `asimdhp` strings on arm64-v8a against 1 on armeabi-v7a, and 1,041 `fp16s` source strings
against 150. x86_64 is the odd one out in the other direction — 1,190 `avx512` strings and a `.so`
2.6x the arm64 one, so an APK size measured on an emulator badly overstates what ships to a phone.

## iOS notes

**The extension needs no fixing up.** `otool -hv` on the device slice reads `MH_MAGIC_64 ARM64
DYLIB` with `NOUNDEFS DYLDLINK TWOLEVEL WEAK_DEFINES BINDS_TO_WEAK MH_HAS_TLV_DESCRIPTORS`, which
is the filetype Flet's iOS packaging needs, so the `MH_BUNDLE` conversion other recipes on this
index depend on never engages. Its whole linkage is `/usr/lib/libSystem.B.dylib` and
`/usr/lib/libc++.1.dylib` plus its own install name — the OS's own C++ runtime, where Android needs
`flet-libcpp-shared` — and Python symbols resolve through dyld: 167 of the 381 undefined symbols
are CPython API, and the device slice exports exactly two — `_PyInit_ncnn` and one pybind11 error
helper.

**iOS uses ncnn's own minimal OpenMP**, `NCNN_SIMPLEOMP`, which implements the LLVM OpenMP ABI on
pthreads (`src/simpleomp.cpp`); upstream's `src/CMakeLists.txt` compiles the pragmas with
`-Xpreprocessor -fopenmp` on Apple platforms and links no runtime at all. The binary carries no
`__kmp*` exports and 17 undefined `pthread_*` symbols instead, and `OMP_NUM_THREADS` is absent from
its string table. **It is real threading, not a serial stub** — unlike the `flet-libomp`
arrangement [`faiss-cpu`](../faiss-cpu) documents — and the proof is that two of those imports are
`pthread_once` and `pthread_create`: across all of upstream's `src/`, `pthread_once` appears only
in `simpleomp.cpp` and the only `ncnn::Thread` ever constructed is the worker pool at
`simpleomp.cpp:222`. A build with the pragmas compiled out would import neither. What it does
*not* mean is that the thread accounting matches Android's — that pool is `get_cpu_count() - 1`
wide whatever `opt.num_threads` says, see [Threading](#threading) — and nothing here has measured
the scaling on an actual iPhone; the example is the way to do that.

**The arm kernels are the same as Android's**, which is a real contrast with
[`onnxruntime`](../onnxruntime#things-to-know), where the iOS slices carry no i8mm at all. Counting
mnemonics in `llvm-objdump -d` output on the two arm64 slices (Mach-O spells it `fmla.8h`, ELF
`fmla v0.8h`, so both spellings were counted): fp16 `fmla` 7,397 on iOS against 7,403 on Android,
fp32 `fmla` 27,663 against 27,631, `sdot`/`udot` 760 against 646, `smmla`/`ummla` 110 against 110,
`bfmmla` 216 against 216.

Runtime CPU dispatch goes through sysctl instead of the kernel filesystem: `hw.cpufamily`,
`hw.ncpu`, `hw.nperflevels`, `hw.physicalcpu_max`, `hw.perflevel0.{logicalcpu_max, l2cachesize,
l3cachesize, cpusperl2}` and `hw.optional.arm.FEAT_{BF16, DotProd, FHM, FP16, I8MM}`.

**The binary is stripped**: `nm -a` returns 384 entries against `nm -u`'s 381 plus two defined
globals, i.e. the dynamic table and nothing else. The Android one is stripped too (`llvm-readelf
-S` shows `.dynsym`/`.dynstr`/`.shstrtab` and no `.symtab` or debug sections), so the 1.8 MB the
Android arm64 slice carries over this one is code rather than symbols — the embedded OpenMP runtime
being the obvious candidate. Either way the iOS slices here are the *smaller* ones, which is the
opposite of onnxruntime, whose iOS extension ships unstripped.

| slice | wheel | unpacked | the `.so` alone |
| --- | --- | --- | --- |
| arm64 (device) | 2,178,323 | 4,938,020 | 4,769,952 |
| arm64 (simulator) | 2,095,358 | 4,740,843 | 4,572,768 |
| x86_64 (simulator) | 6,246,517 | 14,590,749 | 14,422,672 |

`LC_BUILD_VERSION` is not the same across the three despite the `ios_13_0` in every filename:
device and x86_64 simulator say minos 13.0, the arm64 simulator says **14.0**. It bites nothing on
a phone Flet supports, and it is recorded here because a slice comparison that opens one binary and
generalises will get it wrong — the same discrepancy [`faiss-cpu`](../faiss-cpu#ios-notes) documents.

## Things to know

- **`ncnn.Mat(array)` does not keep `array` alive, and reading a dead one is silent.** The
  constructor takes no reference — `sys.getrefcount` on the source is unchanged across it — so the
  Mat is left pointing at a buffer Python is free to reuse. Measured: build a Mat inside a function
  from a local array, return it, collect, allocate 5,000 same-sized arrays, and the Mat reads
  something else in **5 of 5 trials**; keeping a reference to the source made it 0 of 5. The
  realistic shape of this is one expression:
  `ex.input("x", ncnn.Mat(np.ascontiguousarray(frame, np.float32)))` — the temporary dies before
  `extract` ever runs, and the output was literally the junk value that landed in the freed buffer,
  with a `0` return code. Bind the array to a name and keep it alive across the whole call. The
  same question runs the other way for outputs, and the answer differs by call: on the Mat that
  `extract` returns, `mat.numpy()` and `np.asarray(mat)` are views of the same buffer — mutating
  one changes what the other reads — while `np.array(mat)` copies. That buffer belongs to the
  `Net`'s own pool allocator (`use_local_pool_allocator` defaults to true in `src/option.cpp`, and
  a `pool allocator destroyed too early` diagnostic ships in all six slices), so take the
  `np.array(...)` copy before you release the `Net`, and keep the `Net` in an attribute for the
  app's lifetime rather than rebuilding it per tap.
- **Anything that is not float32 is accepted and then goes wrong.** `ncnn.Mat` reports
  `elemsize` 8 for a float64 array, 4 for int32 and 1 for uint8, all without complaint, and then
  reads the bytes as float32. Running one `InnerProduct` over each: float64 **kills the process**
  (killed by a signal — exit status 138, i.e. SIGBUS on macOS — with no Python exception to
  catch), int32 and uint8 both return nonsense with a `0` return code — zeros, NaN or plausible
  finite garbage depending on the values, so there is no signature to test for. numpy's
  default float dtype *is* float64, so
  `np.zeros(n)`, `np.array([...])` and most arithmetic produce exactly the array that crashes —
  `np.ascontiguousarray(x, dtype=np.float32)` on the way in is not optional.
- **The defaults do fp16 arithmetic, so ncnn does not agree with float32 numpy out of the box.**
  Upstream sets `use_fp16_packed`, `use_fp16_storage` and `use_fp16_arithmetic` to true in
  `src/option.cpp`. Against a numpy float32 reference for the same graph, relative to the largest
  output: a 3-layer 3x3 conv stack over 1x128x128 differs by **5.6e-02** at 32 channels and
  6.8e-02 at 64 with the defaults, and by 7.5e-06 with the three flags off; a 3-layer MLP differs
  by ~1e-03 against ~1e-07. Turning them off costs RAM as well as speed: staged RSS for the same
  84 MB float32 `.bin` was **+56.7 MB** on `load_model` with fp16 on and **+96.3 MB** with it off.
- **The fp16 flags are a load-time decision and changing them later is not a slower path, it is a
  broken one.** Set them before `load_param`. Setting them *after* `load_model` was measured in
  isolated processes: turning them **off** there poisons the output with NaN — every element in one
  graph, 14% of them in another — and still returns `0`, so a partial answer can look survivable;
  and turning them **on** there kills the process with SIGSEGV. Build one `Net` per configuration
  and keep it, rather than re-tuning one that has already loaded its weights.
- **CPU only, on both platforms — there is no GPU path, not even a disabled one.** Diffed the
  desktop wheel of the same version against every mobile slice: of 185 public API names (68
  top-level plus the members of `Net`, `Mat`, `Extractor`, `Option`, `Layer`, `Blob`, `ParamDict`,
  `DataReader`, `ModelBin`), exactly 20 are absent from all six, and every one is Vulkan —
  `GpuInfo`, `VulkanDevice`, the seven `Vk*Allocator`/`Vk*Memory` types, `create_gpu_instance`,
  `destroy_gpu_instance`, `get_gpu_count`, `get_gpu_device`, `get_gpu_info`,
  `get_default_gpu_index`, `Net.set_vulkan_device`, `Net.vulkan_device` and the three
  `Option.*_vkallocator` fields. The other 165 are present on every slice. Corroborating: zero
  `libvulkan` strings, no `vkCreateInstance`, nothing in `DT_NEEDED`, and the only four
  case-insensitive `vulkan` matches anywhere are the pybind field names `support_vulkan`,
  `support_vulkan_any_packing`, `support_vulkan_packing` and `use_vulkan_compute`. That last one is
  still a settable bool and setting it does nothing — there is no machinery behind it.
- **All 110 upstream layer types are compiled in, on every slice.** Taking the canonical registry
  names out of the sdist (`ncnn_add_layer(...)` in `src/CMakeLists.txt`, 110 of them) and testing
  each as an exact string, every slice has 110/110 with nothing missing, and the desktop wheel's
  `layer_to_index` resolves all 110. That includes the modern set — `Gemm`, `MatMul`,
  `MultiHeadAttention`, `SDPA`, `LayerNorm`, `RMSNorm`, `GroupNorm`, `GRU`, `LSTM`, `RotaryEmbed`,
  `Einsum`, `GridSample`, `DeformableConv2D`, `Spectrogram`, `InverseSpectrogram`. Nothing was
  trimmed for size.
- **Nothing raises. Every failure is a negative return code and a message on stderr — and the
  natural next line then crashes the app.** `load_param` on a missing file is `-1`; on a file whose
  magic is not `7767517` it is `-1` with *param is too old, please regenerate*; `load_model` on a
  missing file is `-1`; a typo'd blob name gives `ret == -1`, and an `extract` whose input was
  never set gives `-100`. Both failures hand back an **empty** Mat — `dims`, `w`, `h`, `c` and
  `elemsize` all zero — and `np.array(that)` **segfaults the process**, while `that.numpy()` at
  least raises `RuntimeError: Convert ncnn.Mat to numpy.ndarray. Support only elemsize 1, 2, 4;
  but given 0`. So the return code is not optional bookkeeping: check it *before* you touch the
  Mat. On device the stderr messages land in logcat or `console.log` where a user never sees them,
  so put the code on screen too.
- **In a `.param` line the first name is the layer and the names after the two counts are blobs**,
  and `ex.input()`/`ex.extract()` take blob names. `Input in 0 1 x` declares a layer called `in`
  producing a blob called `x`; asking for `in` fails and ncnn even prints the name it wanted. Print
  `net.input_names()` and `net.output_names()` after `load_param` — they return the blob names and
  are the authoritative answer, and the example puts both on screen.
- **`ncnn.__version__` is the date the extension was compiled, not the version you installed.**
  Every mobile slice reports `1.0.20260714` while the distribution is `1.0.20260526`; the desktop
  wheel of the same release reports the release date for both. Upstream's `CMakeLists.txt` derives
  the version from `string(TIMESTAMP … "%Y%m%d")` and passes it through `-DVERSION_INFO` into
  `m.attr("__version__")`, while the recipe's patch pins only the version `setup.py` names the
  wheel with. Read `importlib.metadata.version("ncnn")` when you need the installed version, and do
  not gate anything on `ncnn.__version__`.
- **Budget about 10.5 MB of RSS for `import ncnn` itself**, before any model. Staged on desktop
  (indicative only, not device evidence): 17.5 MB baseline → 28.5 after `import numpy` → 38.9 after
  `import ncnn` → 39.1 after `load_param` → 95.8 after `load_model` of an 84 MB `.bin` → 95.9 after
  one inference. Weights dominate, and with fp16 on they cost roughly half the file.

## Build notes (maintainers)

`patches/pin-version-date.patch` explains itself in its own preamble and `meta.yaml` comments its
own non-obvious settings, so what is left here is shape and the bump checklist.

The shape is the plain pybind11 one: upstream's `setup.py` drives CMake itself, so the recipe only
has to feed it `EXTRA_CMAKE_ARGS`, which `setup.py` appends *after* its own list — that is what
lets `-DNCNN_VULKAN=OFF` win over the `-DNCNN_VULKAN=ON` hardcoded on line 103 of it. One
extension, no companion `flet-lib*` recipe, no `host_build` chain, one patch. The two deliberate
asymmetries are `-DNCNN_SIMPLEOMP=ON` on iOS only and the 16 KB max-page-size linker flags on
Android only.

One cosmetic defect worth knowing so a metadata audit does not chase it: **the Android wheels'
`METADATA` lost the long description** when forge appended the `flet-libcpp-shared` requirement.
It is 1,585 bytes and ends at `Requires-Dist:` with no body, where the iOS `METADATA` of the same
build is 28,501 bytes and carries upstream's full README. Nothing on device reads it.

A bump can falsify everything above without the build going red. What to re-verify:

- **The patched version date.** `pin-version-date.patch` freezes the date segment `setup.py`
  generates; a new sdist means a new date, and if the patch is not updated the wheel version stops
  matching `meta.yaml`. Note that the *extension's* `__version__` is a separate value, comes from
  CMake's `string(TIMESTAMP)` and is not pinned by anything — it will keep reporting the build day.
- **`NCNN_VULKAN=OFF`.** Upstream's `setup.py` forces it on and the override only wins because of
  argument order. The 20-name diff in [Things to know](#things-to-know) is the check, and it needs
  the desktop wheel of the same version as its control — without one, a scan that finds nothing
  proves nothing.
- **The layer count.** 110 today, straight out of `src/CMakeLists.txt`; upstream adds layers
  regularly, and the claim that nothing was trimmed is the thing being checked, not the number.
- **The `Option` defaults.** `num_threads = get_physical_big_cpu_count()` and the three fp16 flags
  come from upstream's `src/option.cpp`, and both the [Threading](#threading) advice and the fp16
  agreement figures rest on them.
- **The two thread-accounting facts, which no test covers and no measurement here can see.**
  [Threading](#threading) says `OMP_NUM_THREADS` is inert because every parallel region names
  `num_threads(opt.num_threads)` (`grep -c 'pragma omp parallel for num_threads'` over `src/`
  against the bare-pragma count: 3306 and 0 today), and that iOS holds a `get_cpu_count() - 1`
  pool whatever `num_threads` says (`KMPGlobal::init()` in `src/simpleomp.cpp`). Both are read
  out of upstream C++, so a bump can flip either with a green build and no failing test.
- **`Requires-Dist`.** Five packages, `opencv-python` the largest by far. If upstream ever splits
  the model-zoo extras behind a marker the whole install-size table changes — and it would be worth
  reconsidering whether the recipe should strip them, since nothing on the import path uses any of
  them.
- **The sizes, the resolve totals and the per-slice tables**, all measured from the cp314 build-2
  wheels and a `pip download` against pypi.flet.dev. Re-measure rather than adjusting by eye.
- **Every behavioural figure on this page** — the GIL table, the thread sweep, the fp16 agreement,
  the RSS staging, the dangling-`Mat` and dtype failures — came off a desktop install of exactly
  `ncnn==1.0.20260526` from PyPI, not off a device. What carries over is the code, not the clock:
  the shipped `.py` files are byte-identical across all six mobile slices, one C++ tree builds
  every one of them, and the two things that genuinely differ (the OpenMP runtime and the 32-bit
  fp16 gap) are called out where they matter. The [`written-model`](examples/written-model)
  example exists so the numbers can be read off a phone instead, which makes it the thing to run
  after a bump.
- **`tests/test_ncnn.py` covers three things and this page claims a dozen.** It proves the Mat
  round trip, one weightless graph, and `get_cpu_count() >= 1`. Nothing there covers the fp16
  agreement, the dtype trap, the dangling-`Mat` lifetime, the fp16-flag-after-load failure, or the
  return codes — all consumer-facing claims a bump could break silently, and all cheap to assert.
  `test_cpu_info` is also the one test in the file without a docstring, against this repo's own
  convention; worth fixing at the next touch.
