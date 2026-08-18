# llama-cpp-python

[`llama-cpp-python`](https://llama-cpp-python.readthedocs.io/en/latest/) runs a GGUF
language model inside your own process. You point
[`Llama(model_path=...)`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/)
at a `.gguf` file and get the whole of
[llama.cpp](https://github.com/ggml-org/llama.cpp) behind a Python API: `llm(prompt)` for a
completion, `create_chat_completion` for a chat turn, `generate` for a raw token stream,
`tokenize`/`detokenize`, and `embed` when you want vectors instead of text.

On a phone that is the difference between an app that needs a server and one that does not.
No API key, no round trip, no per-token bill, and no prompt leaving the handset — a model
file plus this wheel is the entire stack. Whether the model you want *fits* is the real
question, and that is what [Things to know](#things-to-know) is for.

**The wheel contains no compiled Python extension at all.** It is pure ctypes: `import
llama_cpp` dlopens four bundled shared libraries — `libllama` plus `libggml`, `libggml-cpu`
and `libggml-base` — out of `llama_cpp/lib/`. That is the same shape as
[`pyzbar`](../pyzbar) and [`python-magic`](../python-magic), ctypes over a native library,
except that here the libraries travel inside this wheel instead of in a companion
`flet-lib*` one. So everything interesting about how it loads lives in
[Android notes](#android-notes) and [iOS notes](#ios-notes) rather than in an extension
module.

What it is **not** here is a route to the phone's GPU or NPU. One ggml backend is compiled
in — the CPU one — on both platforms, and the ARMv8.2 dot-product kernels that quantised
models are designed around are absent from the device builds. Read
[Things to know](#things-to-know) before you promise anyone a token rate.

Neighbours on this index cover the jobs this one does not:
[`onnxruntime`](../onnxruntime) runs a model somebody else exported — classifiers,
embedders, anything with an ONNX exporter — [`tflite-runtime`](../tflite-runtime) and
[`ncnn`](../ncnn) do the same for `.tflite` and `.param`/`.bin` graphs,
[`faiss-cpu`](../faiss-cpu) searches the vectors an embedding model produces, and
[`safetensors`](../safetensors) memory-maps a large side table when what you are storing is
not a GGUF.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "llama-cpp-python",
]
```

Nothing else to configure. Wheels exist for **every slice Flet targets** — the three Android
ABIs (`arm64-v8a`, `armeabi-v7a`, `x86_64`) and all three iOS slices (device, arm64
simulator, x86_64 simulator) — on Python 3.12, 3.13 and 3.14, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is forced on you the way it is for [`onnxruntime`](../onnxruntime). The index
lists 36 files: three Python versions × six slices × two build numbers.

**Four runtime dependencies, and every one of them is imported by `import llama_cpp`.**
`Requires-Dist` names `typing-extensions`, `numpy`, `diskcache` and `jinja2`, and none is
optional: `llama.py` imports `llama_chat_format` at module top, which imports `jinja2` and
`numpy` unconditionally, and `llama_cache` imports `diskcache`. Through those, stdlib
`sqlite3` and `multiprocessing` come in too — checked by listing `sys.modules` after a bare
`import llama_cpp`, which yields `ctypes, diskcache, jinja2, markupsafe, multiprocessing,
numpy, sqlite3, typing_extensions`. A Flet Python build missing `_sqlite3` or
`multiprocessing` would therefore fail at *import*, not at first use. Both ship in Flet's
3.12 runtimes today — `modules/_sqlite3.cpython-312.so` and
`modules/_multiprocessing.cpython-312.so` inside Android's `libpythonbundle.so`, and the
matching `.xcframework`s on iOS — so this is a thing to re-check on a runtime bump, not a
thing to work around.

Resolving the way `flet build` does (`pip download --only-binary=:all: --extra-index-url
https://pypi.flet.dev`, Python 3.14) that is:

| slice | wheels | download |
| --- | --- | --- |
| Android arm64-v8a | 7 | 9,396,424 B |
| Android armeabi-v7a | 7 | 8,782,767 B |
| Android x86_64 | 7 | 10,874,273 B |
| iOS device arm64 | 6 | 8,520,905 B |

numpy is 6.85 MB of the Android arm64-v8a figure and llama-cpp-python itself 1.90 MB;
`jinja2` also drags in a *native* `markupsafe` wheel from this index (11,877 B). Android
carries one wheel iOS does not, `flet-libcpp-shared` (see [Android notes](#android-notes)).

**`Requires-Python` in the wheel is `>=3.8`, but set `requires-python = ">=3.11"` anyway if
you pin with `==`.** The floor does not come from this package: the numpy that resolves for
mobile is 2.4.6, which declares `>=3.11`. `flet create` writes `>=3.10`, and uv resolves for
every version in the declared range rather than only the interpreter in use, which is how a
floor you did not set turns into *No solution found when resolving dependencies for split*.
Check it the way a consumer meets it — copy the `pyproject.toml` alone into an empty
directory and run `uv lock` there; the example's pins resolve 56 packages that way. (This
index carries numpy only for cp312, cp313 and cp314, which are the Python versions
`flet build` targets.)

No [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
needed, but for a non-obvious reason. The loader *does* build paths from `__file__`, and on
Android every one of those probes misses inside Flet's zipped site-packages; it works
because the recipe's patch adds a bare-soname fallback (see
[Android notes](#android-notes)). Compile-to-`.pyc` is safe: there is no
`importlib.resources`, `pkg_resources`, `pkgutil` or `getsource` anywhere in the package,
and `__file__` appears in exactly four modules, all of them loaders.

## Storage

A GGUF is one ordinary file and `Llama` takes a path, so the only question is where the
file comes from.

**Downloaded on device** is the normal case, because a useful model is hundreds of
megabytes and does not belong in an app bundle. Write it to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "model.gguf")
llm = llama_cpp.Llama(model_path=path, n_ctx=512, n_batch=32, n_threads=2)
```

Do not park a multi-hundred-megabyte download in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) unless re-fetching it is genuinely cheap.

`Llama.from_pretrained(repo_id, filename)` will fetch from Hugging Face for you, and it
needs `huggingface-hub`, which is not on pypi.flet.dev but does resolve from PyPI: 13 wheels
for Android arm64-v8a and the same 13 for iOS device, landing on `huggingface_hub` 0.31.4.
Newer releases require `hf-xet` on every 64-bit `platform_machine`, and `hf-xet` has no
mobile wheel (404 on this index), which is why pip backs off to that version. The import is
lazy — inside the method, with an explicit `ImportError` if it is missing — so nothing
happens to an app that never calls it. **This resolve has not been exercised on a device**;
plain `urllib`/`httpx` to a URL you control is the boring alternative and needs no extra
wheel.

**Shipped with the app** works if your model is small enough to be an asset: put the
`.gguf` in `src/assets/` and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).
Assets are read-only and replaced on every app update.

**Written at runtime** is also a supported shape, and it is what the example does: a
structurally valid GGUF is a header, a metadata block, a tensor table and padded tensor
data, all of which `struct` and numpy can produce. `llama_model_quantize` is exported too,
so an app can quantise a GGUF it holds and write out a smaller one.

Inference itself writes nothing. `use_mmap=True` is the default, so the weights are read
through the page cache rather than into anonymous memory — see
[Things to know](#things-to-know) for what that does and does not buy you.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`hand-built-gguf`](examples/hand-built-gguf) — a GGUF language model written by the app,
  loaded and generated from on device, with llama.cpp's logits checked against a numpy
  forward pass.

## Threading

**The llama.cpp work releases the GIL** — the bindings are `ctypes.CDLL`, and ctypes drops
the lock around every foreign call. But `eval` and `generate` are not one foreign call each:
they are Python loops with foreign calls inside, and the Python between the calls does hold
it, in bursts of tens of milliseconds. Model construction is the clean case, which is the
opposite arrangement from [`onnxruntime`](../onnxruntime), where session construction holds
the lock outright.

Measured with a canary thread recording the longest gap between its own iterations while the
call runs; a canary that never gets a turn is a UI thread that never gets a frame. Every row
is a median of five, interleaved in one process so machine load lands on all of them equally.
Desktop CPython 3.12 on a 10-core host, `n_gpu_layers=0`, 4 threads, a 3.0 MB F32 model. The
first three rows are the harness checking itself: an idle main thread and a call known to
release must sit near 0, one known to hold must sit near 1, or nothing below them means
anything.

| call | duration | longest canary stall | stall ÷ call |
| --- | --- | --- | --- |
| idle main thread (floor) | 311 ms | 0.3 ms | 0.00 |
| `hashlib.sha256` of 268 MB (releases) | 130 ms | 0.3 ms | 0.00 |
| `sum(range(60_000_000))` (holds) | 528 ms | 522.0 ms | 0.99 |
| `Llama(model_path=...)` | 444 ms | 0.4 ms | 0.00 |
| `llm.eval(...)`, 64 then 256 tokens | 93 / 188 ms | 8.2 / 26.3 ms | 0.09 / 0.14 |
| `llm.generate(...)`, 8 then 32 tokens | 440 / 597 ms | 23.0 / 18.4 ms | 0.05 / 0.03 |

**The harness's floor is 0.3 ms here**, so anything reported at that scale is noise and
anything in double digits is not. Model construction sits on the floor. `eval` and
`generate` do not: both hold the lock in bursts of 8–26 ms, and the same two rows on a
1.6 MB Q4_0 model gave 26.9 / 42.9 ms for `eval` and 12.4 / 23.6 ms for `generate`. Flutter
renders on the client side, so those bursts do not drop its frames — they stall whatever
Python was going to do next, which is every handler and every `page.update()`. The bursts
are Python, not llama.cpp: `Llama.eval` builds each batch in a loop and copies the returned
logits into `llm.scores`, and `Llama.generate` builds a sampler chain and runs a per-token
Python step around each `llama_decode`. Absolute durations move with machine load; the ratio
column is the stable part.

So put loading and generation in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and the
UI keeps its frames. Two standing Flet caveats apply: `run_thread` never retrieves the
worker's future, so an exception raised inside one surfaces nowhere at all — wrap the body
in `try/except Exception` — and auto-update does not reach background threads, so end the
handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**One `Llama` object is not safe to drive from two threads at once.** `Llama.eval` mutates
`self.n_tokens`, `self.input_ids` and `self.scores` around each `llama_decode`, and there is
one llama.cpp context behind all of it — so two overlapping calls on the same object are two
writers on the same state. `run_thread` submits to a shared thread pool, so two taps in
quick succession really do overlap. Serialise with a `threading.Lock` around the whole call,
or disable the control that starts the work until it finishes, which is what the example
does.

**Set both thread counts explicitly.** The defaults are chosen in Python, not by llama.cpp:
`llama.py` uses `n_threads = max(multiprocessing.cpu_count() // 2, 1)` for generation and
`n_threads_batch = multiprocessing.cpu_count()` — *all* cores — for prompt processing.
Verified on a 10-core host: a default `Llama(...)` reports `n_threads` 5 and
`n_threads_batch` 10. On a big.LITTLE phone that reaches the little cores as well, and a
backgrounded app that grabs every core is throttled or killed rather than merely slowed.
`n_threads=2, n_threads_batch=4` — or `max(1, os.cpu_count() // 4)` — is the saner starting
point, and the only way to know what it buys is to time it on the handset.

## Android notes

**None of the four libraries carries `RUNPATH` or `RPATH`.** They resolve each other purely
by `DT_NEEDED` and soname — `libllama` → `libggml` → `libggml-cpu` → `libggml-base`, each
with its own unversioned `SONAME` — plus `libc++_shared`, `libm`, `libdl` and `libc`. That
absence is what makes the delivery mechanism work. Flet 0.86 ships site-packages as a zip
and serious-python relocates the bundled `.so` files into the APK's `jniLibs`, so every
`Path.exists()` probe the loader makes against `llama_cpp/lib/` misses; the recipe's patch
then falls through to `ctypes.CDLL("libllama.so")` and the Android linker resolves the whole
chain from `jniLibs` by soname. Confirmed by opening the example's APK: `lib/<abi>/` carries
all four libraries under their bare sonames at byte-for-byte the wheel's sizes, while
`llama_cpp/lib/` inside `assets/sitepackages.zip` is left holding nothing but the `cmake/`
and `pkgconfig/` text files — and unlike every other native wheel in the same bundle, no
`.soref` marker is written for them. There is nothing in site-packages for a path-based
probe to find, on any of the three ABIs.

That `libc++_shared.so` in `DT_NEEDED` is why the Android wheels carry an extra
`Requires-Dist: flet-libcpp-shared (>=27.2.12479018)` that the iOS wheels do not. It rides
along on its own and needs no configuration.

Every `PT_LOAD` segment of all twelve Android `.so` files is 16 KB (`0x4000`) aligned, which
Android 15 requires.

| ABI | wheel | unpacked | the four libraries |
| --- | --- | --- | --- |
| arm64-v8a | 1,901,380 B | 5,330,528 B | 4,372,128 B |
| armeabi-v7a | 1,736,355 B | 4,147,218 B | 3,188,816 B |
| x86_64 | 1,996,321 B | 5,782,398 B | 4,824,048 B |

The Android wheels' `METADATA` is 2,351 bytes against iOS's 35,725 — upstream's long
description is stripped as a side effect of forge appending the `flet-libcpp-shared`
requirement. Cosmetic; the `Requires-Dist` lines are otherwise identical.

## iOS notes

**The dylibs need no fixing up.** All twelve are `MH_DYLIB` marked `NOUNDEFS` (`otool -hv`),
so the `MH_BUNDLE` → `MH_DYLIB` conversion other recipes on this index depend on never
engages here. `otool -L` lists only `/usr/lib/libc++.1.dylib` and
`/usr/lib/libSystem.B.dylib` beside the sibling `@rpath` references — iOS uses the system
C++ runtime where Android needs `flet-libcpp-shared`, which is the one wheel the iOS
closure does not carry.

**Loading is a two-step dance and both steps are in the patch.** Each dylib's install-id is
`@rpath/lib<name>.dylib` and its only `LC_RPATH` is `@loader_path`. serious-python
repackages every `*.so`/`*.dylib` under site-packages into a code-signed
`<name>.framework` and leaves a `lib<name>.fwork` text marker where the file was, so (a) the
loader reads the marker and walks up to the real framework binary the way CPython's
`AppleFrameworkLoader` does, and (b) it preloads `ggml-base` → `ggml-cpu` → `ggml` with
`RTLD_GLOBAL` before `llama`, so each already-loaded image's install-id satisfies the next
library's sibling `@rpath` reference. This is the same Pattern-H story [`pyzbar`](../pyzbar)
tells, with the `.fwork` resolution as the extra step.

| slice | wheel | unpacked | the four libraries |
| --- | --- | --- | --- |
| arm64 (device) | 1,695,343 B | 5,186,352 B | 4,194,392 B |
| arm64 (simulator) | 1,767,124 B | 5,235,935 B | 4,243,968 B |
| x86_64 (simulator) | 1,897,372 B | 5,607,225 B | 4,615,304 B |

**Do not benchmark this package on the arm64 simulator.** It is the one slice built with
`DOTPROD` and `FP16_VA`, and its `libggml-cpu.dylib` carries 897 `SDOT` instructions where
the device slice carries zero — see [Things to know](#things-to-know). It is also the only
shipped slice on which `GGML_CPU_REPACK` actually engages, since the repack traits selector
is gated on `DOTPROD`. A simulator number will overstate a phone by whatever those two are
worth together.

The `LC_BUILD_VERSION` minimum is not the same across the three despite the `ios_13_0` in
every filename: device (platform 2) and x86_64 simulator say 13.0, the arm64 simulator says
14.0. It bites nothing on a phone Flet supports, and is recorded so a slice comparison that
opens one binary does not generalise.

## Things to know

- **CPU only, on both platforms — no Metal, no Vulkan, no OpenCL, no CUDA, no BLAS and no
  Accelerate.** `ggml_backend_cpu_reg` is the only backend-registration symbol in
  `libggml`; the `blas`/`cann`/`cuda`/`hexagon`/`metal`/`opencl`/`sycl`/`vulkan` strings
  beside it are the search list `ggml_backend_load_all` uses for *dynamically* loaded
  backends, and
  nothing can be loaded because none is built. Corroborating negatives: zero
  `MTLDevice`/`Metal`/`vDSP`/`cblas_`/`Accelerate`/`CoreML` strings in any of the four iOS
  device dylibs, zero `vulkan`/`opencl`/`cuda` in the Android libraries other than that one
  search list, and no OpenMP anywhere (`omp_`, `GOMP`, `__kmpc_` all absent). Leave
  `n_gpu_layers` at its default of 0. `llama_supports_gpu_offload()` is a runtime registry
  query rather than a constant — it looks for a GPU device, then an accelerator device, then
  a backend named `RPC` — and this build registers none of the three.
- **The shipped device builds have no ARMv8.2 dot-product kernels, which is the most
  consequential fact on this page.** `llvm-objdump -d | grep -cw sdot` (and `smmla`) over
  all four Android arm64-v8a `.so` files and all four iOS device dylibs returns **0** for
  every one of the eight, and `ggml_cpu_has_dotprod` and `ggml_cpu_has_matmul_int8` both
  disassemble to `mov w0, wzr; ret`. Those kernels are precisely what llama.cpp's quantised
  matmuls are designed to dispatch to, so a quantised model here runs its int8 arithmetic on
  plain NEON multiply-accumulate instead. **How much throughput that costs on a real handset
  and a real GGUF has not been measured — do not assume a number, measure on the device you
  care about.** The compiled feature set, read off the constant-return stubs rather than
  inferred:

  | slice | features compiled in |
  | --- | --- |
  | Android arm64-v8a | NEON, ARM_FMA |
  | Android armeabi-v7a | NEON |
  | Android x86_64 | SSE3, SSSE3 |
  | iOS arm64 (device) | NEON, ARM_FMA |
  | iOS arm64 (simulator) | NEON, ARM_FMA, FP16_VA, **DOTPROD** |
  | iOS x86_64 (simulator) | SSE3, SSSE3 |

  `llama_print_system_info()` reports this at runtime and the example puts it on screen;
  it is the first thing to read on a device you have not tried.
- **`GGML_CPU_REPACK` is compiled in but can never engage on a device, and the runtime
  banner will still say `REPACK = 1`.** The kernels are physically there — 217 exported
  symbols matching `repack` on Android arm64-v8a and 261 in the iOS device dylib's table,
  `ggml_backend_cpu_repack_buffer_type` among them and 178 of the iOS ones demangling to
  `ggml::cpu::repack::tensor_traits<...>`. They are unreachable. Disassembling the traits
  selector inside `libggml-cpu` shows every one of its non-null returns guarded by
  `avx2`, `avx512`, `dotprod`, `matmul_int8`, or `sve && matmul_int8 && sve_cnt == 32` —
  and by the table above, not one of those is set on any slice except the iOS arm64
  simulator. `neon` or `sse3` alone never selects a traits object, so
  `extra_buffer_type::supports_op` returns false for every tensor and nothing is repacked.
  Confirmed by A/B on two desktop builds of this same version with a
  real Q4_0 GGUF: the one with `DOTPROD = 1` repacks seven tensors and allocates
  `CPU_REPACK model buffer size = 1.41 MiB`, while a build whose banner is exactly the
  device's — `CPU : NEON = 1 | ARM_FMA = 1 | REPACK = 1` — reports every tensor
  *"cannot be used with preferred buffer type CPU_REPACK, using CPU instead"* and allocates
  no such buffer at all. `REPACK` is pushed into the feature list at compile time,
  unguarded by any `ggml_cpu_has_*` call, so `llama_print_system_info()` advertises it
  regardless. **Do not read `REPACK = 1` on a handset as a capability.**
  `GGML_LLAMAFILE`, by contrast, is not compiled in at all: `ggml_cpu_has_llamafile`
  returns 0 and there is no `tinyBLAS`/`llamafile_sgemm` anywhere; the `LLAMAFILE` string
  in the binary is the name of that runtime query and proves nothing.
- **An uncatchable C++ abort is a real failure mode, and no `try/except` reaches it.** Model
  *loading* is wrapped and raises an ordinary `ValueError` for every bad input tried — a
  missing path gives `Model path does not exist: …`, a non-GGUF file and a truncated GGUF
  both give `Failed to load model from file: …`. The paths *after* loading are not wrapped.
  A GGUF whose SPM vocabulary omits the 256 `<0xNN>` byte tokens loads fine and then dies on
  the first `llm.tokenize(b"hello")` with `libc++abi: terminating due to uncaught exception
  of type std::out_of_range: unordered_map::at: key not found`; reproduced on desktop
  0.3.32, exit status 134 (SIGABRT), with the `except BaseException` branch and the
  following `print` never reached. On Android that is the same uncatchable `SIGABRT` shape
  the app catalogue records for kivy-era packages. Validate model files before you use them,
  and treat a crash with no Python traceback as coming from here.
- **`max_tokens` is not a hard bound on generation.** The completion loop `continue`s past
  its own `len(completion_tokens) >= max_tokens` check whenever the trailing bytes look like
  an incomplete UTF-8 sequence, so a model emitting raw byte tokens keeps going. Measured on
  desktop on the example's own random-weights models: `max_tokens=1` always gave 1, but across five
  widths and two seeds `max_tokens=4` gave anything from 4 to 12 and `max_tokens=32` gave
  32 to 39, all with `finish_reason` `length`. How far it overruns depends on the model and
  the sampled tokens, and no real GGUF was tried, so treat the number as unbounded. For a
  genuinely hard bound drive the low-level generator yourself —
  `for _, token in zip(range(n), llm.generate(prompt_tokens, temp=0.0)):` — which returns
  exactly `n`.
- **`llm.scores` is uninitialised memory unless you passed `logits_all=True`.**
  `Llama.__init__` builds it with `np.ndarray(...)`, which allocates without writing, and
  with `logits_all=False` — the default — `Llama.eval` stores no logits at all; the branch
  that used to is commented out in 0.3.32, since sampling moved inside llama.cpp's sampler.
  Reading `llm.scores[llm.n_tokens - 1]` then gives you plausible-looking floats that are
  not this model's logits: measured on a hand-built model, the "logits" read that way put
  their argmax on a different token from an independent numpy forward pass, while the same
  code with `logits_all=True` agreed to 2e-07 — see the KV-cache entry below for why that
  reads 3e-04 if you leave the cache at its default. Nothing warns. Pass `logits_all=True` when
  you want the numbers, and remember it changes the buffer's first dimension from `n_batch`
  to `n_ctx`.
- **`n_ctx` is rounded up to a multiple of 256, and `n_ctx=0` means the model's training
  context.** Asking for 1, 64, 200 or 256 all give 256; 300 and 512 give 512; 513 gives 768.
  It matters because `n_ctx` is the term that drives the KV cache:
  `n_ctx × n_layer × (n_embd_k + n_embd_v) × 2` bytes at f16. Predicted +58.7 MB going from
  `n_ctx` 256 to 2048 on an 8-layer, 1024-wide model; measured +64.0 MB of peak RSS on
  desktop, the difference being larger compute buffers.
- **The f16 KV cache is the dominant error term, well above float32 rounding.** The cache
  defaults to `GGML_TYPE_F16` for both K and V, and on an all-float32 model that single
  choice accounts for essentially the whole gap between llama.cpp and an exact forward
  pass. Measured on desktop against a float64 numpy recomputation on hand-built models of 27k–2.9M
  parameters: **4.1e-04** of the logit range at the default, against **2.6e-07** with
  `type_k=llama_cpp.GGML_TYPE_F32, type_v=llama_cpp.GGML_TYPE_F32` — a thousandfold, and
  the f32 figure is float32 epsilon, i.e. as close as the arithmetic can get. For
  comparison, redoing the whole reference pass in float32 instead of float64 moved it by
  only 2.6e-07, so this is the cache and not the precision of the compute. It is a fair
  default — it halves the term that grows with `n_ctx` — but it means a logit you read back
  is good to about four significant figures, not seven. Pay the doubled KV memory when you
  are comparing logits, checking a port, or computing perplexity; leave it at f16 when you
  are generating text.
- **`n_batch` costs you a float32 buffer in Python before llama.cpp allocates anything.**
  `Llama.__init__` builds `np.ndarray((n_batch, n_vocab), dtype=np.single)` — with the
  default `n_batch=512` that is 65.5 MB for a 32k vocabulary, 262.7 MB for a Llama-3 128,256
  one and 311.2 MB for a Qwen 151,936 one. Verified exactly against `llm.scores.nbytes` on a
  267-token vocabulary: 32 × 267 × 4 = 34,176 at `n_batch=32`. Pass `n_batch=32` or `64`
  explicitly; it costs prompt-processing throughput and nothing else, and takes that buffer
  to 16.4 MB at a 128,256 vocabulary. (`logits_all=True` swaps `n_batch` for `n_ctx` in that
  shape, which is usually larger.)
- **mmap does not lower peak RSS, so it is not a way to run a model bigger than RAM.**
  llama.cpp touches every weight page while loading either way. Desktop `ru_maxrss` on a
  337.8 MB F32 model at `n_ctx=256`: 424.2 MB with `use_mmap=True` against 429.1 MB with
  `use_mmap=False`, from a 48.2 MB baseline (16.6 bare Python → 29.0 after numpy → 48.2
  after `llama_cpp`). That is the file plus 86 MB, of which 48 MB is the interpreter and its
  imports; the KV cache and the `n_batch` buffer are what grow from there. Size the model
  against that sum and the device's real budget, not against "mmap will handle it". Leave
  `use_mmap=True` on anyway: mapped pages are clean and file-backed, so the OS can evict
  them under pressure where anonymous pages from a non-mmap load cannot be dropped. The
  numbers are desktop and indicative only; the mechanism is not.
- **Every quantisation type is present and the whole architecture set is compiled in.**
  `ggml` is 0.15.3 (`llama_cpp/lib/cmake/ggml/ggml-version.cmake` in the wheel) and the type
  names in the mobile `libggml-base` match a desktop build of the same version one for one,
  `nvfp4`, `q1_0`, `mxfp4`, `tq1_0` and the IQ family included. Bits per weight, read out of
  `ggml_blck_size`/`ggml_type_size` rather than from documentation: q4_0 and q4_K 4.500,
  iq4_xs 4.250, q5_K 5.500, q6_K 6.562, q8_0 8.500, q3_K 3.438, q2_K 2.625, iq2_xxs 2.062,
  tq1_0 1.688, iq1_s 1.562, f16 16, f32 32. So `params × bpw / 8` gives 562 MB for a 1B model
  at Q4, 328 MB at Q2_K, 1,062 MB at Q8_0; 844 MB for 1.5B at Q4; 1,688 MB for 3B at Q4;
  3,938 MB for 7B at Q4. Real `_K_M` files run above the pure-type figure because they mix
  types — a Q4_K_M of a hand-built model came out at 5.29 bits per weight over the whole
  file against Q4_K's 4.5. Model coverage is not reduced either: the binaries carry 112 distinct
  `llama.cpp/src/models/*.cpp` paths, an **identical** set on Android and iOS, and the
  architecture names themselves are all present in both — llama, qwen2/qwen3/qwen3moe,
  gemma/gemma2/gemma3, phi2/phi3, mistral, falcon, bert, stablelm, starcoder,
  deepseek/deepseek2, granite, olmo2, rwkv6, mamba/mamba2, glm4, exaone, nemotron, cohere2,
  gpt-oss and the rest.
- **Multimodal is not built.** `llama_cpp/mtmd_cpp.py` and `llava_cpp.py` ship in every
  wheel but there is no `libmtmd`/`libllava` to load, so any multimodal chat handler raises
  `FileNotFoundError: Shared library with base name 'mtmd' not found` — the loader's own
  last line, reproduced by importing `llama_cpp.mtmd_cpp`. The import is lazy, inside
  `MtmdChatHandler.__init__`, so plain text use is unaffected. Text only; a multimodal path
  is a recipe change, not an app-side fix.
- **`llama_cpp/server/` is packaged and is the wrong shape on a phone.** It is 69,755 bytes
  of FastAPI application. `llama-cpp-python[server]` does resolve for Android arm64-v8a — 25
  wheels and 12.7 MB against the base 7 and 9.4 MB — so nothing stops you, but an HTTP
  server inside your own app process buys nothing the in-process `Llama` API does not
  already give you. Nothing imports the package unless you do.
- **`LLAMA_CPP_LIB_PATH` overrides where the loader looks** (and `MTMD_CPP_LIB` for the
  multimodal library). Useful for pointing at a library you staged yourself; note that
  `llama_cpp._ggml`, the internal handle on `libggml`, honours neither.
- **`llama_max_devices()` is 16 and `llama_max_parallel_sequences()` is 256 on device.**
  Both disassemble to a constant (`mov w0, #0x10` / `mov w0, #0x100`). They are compile-time
  ceilings, not capability reports — do not read either as something the handset told you.
- **`libllama` re-exports no ggml symbol**, so a consumer wanting `ggml_type_size` has to go
  through `libggml`: a count of defined `ggml_*` text symbols in `libllama` is 0 on both
  platforms. `llama_cpp._ggml.libggml` is the package's own handle for that, and its
  docstring says "use at your own risk".
- **`flet run` on your desktop does not use these wheels.** They are Android/iOS
  platform-tagged, so a desktop resolve takes PyPI's sdist and builds llama.cpp locally —
  with whatever your machine supports. On an Apple Silicon Mac that means
  `llama_print_system_info()` reports `MTL : EMBED_LIBRARY = 1 | CPU : NEON = 1 | ARM_FMA =
  1 | FP16_VA = 1 | DOTPROD = 1 | REPACK = 1`, i.e. Metal *and* the dot-product kernels the
  phone does not have. A desktop run tells you your code is correct and nothing at all about
  what the device will do.

## Build notes (maintainers)

`patches/mobile.patch` enumerates its five changes in its own preamble and `meta.yaml`
comments its `CMAKE_ARGS` inline, so what is left here is shape and the bump checklist.

The shape is a plain scikit-build-core sdist build with every backend switched off, and the
only structural decision worth recording is that the four libraries stay **shared** and
bundled inside the wheel rather than being static-linked into one object or split out into
a `flet-libllama` recipe. That is what forces the loader work in the patch — the preload
chain, the `.fwork` resolution and the bare-soname fallback — and it is the reason this
recipe is Pattern H (ctypes + bundled libraries) rather than the self-contained single
extension [`onnxruntime`](../onnxruntime) is. It is also why there is no separate native
recipe under this one: the libraries have no consumer other than this wheel.

A bump can falsify most of the page without the build going red. What to re-verify:

- **The loader.** `llama_cpp/_ctypes_extensions.py` is the file the patch rewrites, and it
  is the first thing to break if upstream restructures loading. The failure is an
  `ImportError`/`FileNotFoundError: Shared library with base name 'llama' not found` at
  import on device, from a wheel that built green, and `tests/test_llama_cpp_python.py` is
  what would catch it.
- **The CPU feature set and the `sdot`/`smmla` counts.** `meta.yaml` passes
  `-DGGML_NATIVE=OFF` and no `GGML_CPU_ARM_ARCH`, so each toolchain's own default baseline
  is what gets compiled; why that lands differently on the iOS device and iOS arm64
  simulator slices is not something the binaries explain, and the only reliable check is to
  disassemble each slice again. If somebody wants the int8 kernels back, the levers are
  `GGML_CPU_ARM_ARCH=armv8.2-a+dotprod` (which drops pre-2017 devices) or a runtime-dispatch
  multi-variant build; either changes the [Things to know](#things-to-know) table, the
  device/simulator asymmetry, and — because the repack traits selector is gated on exactly
  these flags — whether `GGML_CPU_REPACK` does anything at all.
- **The backend set.** The `GGML_*=OFF` switches are in `meta.yaml`, but a backend upstream
  starts defaulting ON would land silently. The check is
  `llvm-strings libggml.so | grep -E '^ggml_backend_[a-z0-9_]*_reg$'` — `ggml_backend_cpu_reg`
  and `ggml_backend_dev_backend_reg` (the accessor, not a backend) is the passing answer, and
  the `blas`/`cuda`/`metal`/… strings beside them are the dynamic-load search list, not
  evidence of anything built.
- **`tests/test_llama_cpp_python.py` never loads a GGUF.** It calls
  `llama_print_system_info`, `llama_max_devices`, `llama_supports_mmap` and a backend
  init/free round-trip, so a green mobile-test leg proves the four libraries load, the
  import chain (numpy, jinja2, diskcache, `sqlite3`, `multiprocessing`) resolves on device,
  and the C ABI is callable — and proves nothing about inference. The
  [`hand-built-gguf`](examples/hand-built-gguf) example is what exercises loading a model,
  generating from it and quantising; rebuild and run it on a bump. A test that builds a tiny
  GGUF in-process and asserts a token comes out would be cheap to add and would close that
  gap in CI.
- **The dependency list and `Requires-Python`.** Four unconditional dependencies today, all
  import-time. The `>=3.11` floor in the example's `pyproject.toml` comes from mobile numpy,
  not from this package, so it moves when the index's numpy moves.
- **Every size and download total on the page** was measured off the cp314 build-2 wheels
  and a `pip download` against pypi.flet.dev. Re-measure rather than adjusting by eye.
- **Every behavioural figure on this page is desktop.** The GIL table, the KV-cache and
  `n_ctx` measurements, the `max_tokens` sweep and the mmap RSS staging all came off a
  desktop install of 0.3.32 built from PyPI's sdist — which, per the last bullet of
  [Things to know](#things-to-know), is a *different build* with Metal and `DOTPROD`. What
  carries over is the Python layer, which is identical, and the shapes of the formulas; what
  does not is any clock or any throughput. The one number a consumer most wants — tokens per
  second for a real quantised GGUF on a handset — is measured nowhere in this recipe, and
  the [`hand-built-gguf`](examples/hand-built-gguf) example deliberately does not claim to
  supply it. Anything on this page that reads like an inference rate is not one.
- **Dead weight worth trimming.** The wheel writes 20 C headers (270,583 B) into `include/`
  at the *site-packages root* — not under `llama_cpp/` — which is both payload nobody needs
  and a directory name any other wheel shipping headers would collide with. `llama_cpp/lib/`
  also carries four `cmake/` files and one `pkgconfig/llama.pc` (~20 KB), and the `.pc`
  leaks the CI machine's build directory (`/tmp/tmpv7opmzwy/wheel/platlib` on Android,
  `/var/folders/…` on iOS). `llama_cpp/server/` adds another 69,755 B. Together that is
  about 0.36 MB of the ~5.2 MB unpacked, and none of it can be reached by an app.
