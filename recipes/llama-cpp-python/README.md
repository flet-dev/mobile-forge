# llama-cpp-python

[`llama-cpp-python`](https://llama-cpp-python.readthedocs.io/en/latest/) runs a GGUF language
model inside your own process. You point
[`Llama(model_path=...)`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/) at a
`.gguf` file and get [llama.cpp](https://github.com/ggml-org/llama.cpp) behind a Python API:
`tokenize`/`generate`/`detokenize` for a raw token stream, `llm(prompt)` and
`create_chat_completion` for a completion or a chat turn, `embed` for vectors instead of text.

On a phone that is the difference between an app that needs a server and one that does not. No
API key, no round trip, no per-token bill, no prompt leaving the handset — a model file plus this
wheel is the entire stack. Whether the model you want *fits* is the real question, and
[Model files](#model-files) is the section for it.

What it is **not** here is a route to the phone's GPU or NPU. One ggml backend is compiled in —
the CPU one — on both platforms, and the ARMv8.2 dot-product kernels that quantised models are
designed around are absent from the device builds. Read [Things to know](#things-to-know) before
you promise anyone a token rate.

Neighbours on this index cover the jobs this one does not: [`onnxruntime`](../onnxruntime),
[`tflite-runtime`](../tflite-runtime) and [`ncnn`](../ncnn) run models somebody else exported,
[`faiss-cpu`](../faiss-cpu) searches the vectors an embedding model produces, and
[`safetensors`](../safetensors) memory-maps a large side table that is not a GGUF.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "llama-cpp-python",
]
```

**Set `requires-python = ">=3.11"` if you pin any of this with `==`.** The floor is not this
package's — its own `Requires-Python` is `>=3.8` — it comes from what resolves for mobile
alongside it. `flet create` writes `>=3.10`, and uv resolves for every version in the declared
range rather than only the interpreter in use, which is how a floor you did not set turns into
*No solution found when resolving dependencies for split*. Check it the way a consumer meets it:
copy the `pyproject.toml` alone into an empty directory and run `uv lock` there.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`hand-built-gguf`](examples/hand-built-gguf) — a GGUF language model written by the app,
  loaded and generated from on device, with llama.cpp's logits checked against a numpy
  forward pass.

## Usage in a Flet app

Build the model once and keep it; generation is what you do per tap:

```python
import flet as ft
import llama_cpp

LLM = llama_cpp.Llama(
    model_path=path,
    n_ctx=512,
    n_batch=32,
    n_threads=2,
    n_gpu_layers=0,
    verbose=False,
)

answer = ft.Text()

def reply(prompt: str):
    tokens = LLM.tokenize(prompt.encode())
    produced = [t for _, t in zip(range(64), LLM.generate(tokens, temp=0.8))]
    answer.value = LLM.detokenize(produced).decode("utf-8", "replace")
    page.update()
```

Every constructor argument is written out because its default is decided in Python and is wrong
on a handset: `n_threads` defaults to half the cores and `n_threads_batch` to all of them
([Threading](#threading)), and `n_batch` defaults to 512, which buys a float32 logits buffer
measured in hundreds of megabytes before llama.cpp allocates anything
([Model files](#model-files)). `n_gpu_layers=0` is already the default but stops the next reader
assuming a GPU is in play, and `verbose=False` keeps llama.cpp's load log out of the app's
output. The `zip(range(64), ...)` is the hard bound on length — `max_tokens` on the higher-level
`llm(prompt)` and `create_chat_completion` is not one, see [Things to know](#things-to-know).

**Neither the constructor nor the generation loop belongs on the UI thread**, for two different
reasons — see [Threading](#threading).

### Storage

A GGUF is one ordinary file and `Llama` takes a path, so the only question is where it comes
from.

**Downloaded on device** is the normal case, because a useful model is hundreds of megabytes and
does not belong in an app bundle. Write it to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "model.gguf")
```

Do not park a multi-hundred-megabyte download in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches) unless re-fetching it is cheap.
`Llama.from_pretrained(repo_id, filename)` fetches from Hugging Face for you at the cost of
`huggingface-hub`, which resolves only at an older release since newer ones need `hf-xet` and
`hf-xet` has no mobile wheel. **That resolve is not device-tested**; plain `urllib`/`httpx`
against a URL you control is the boring alternative.

**Shipped with the app** works if the model is small enough to be an asset: put the `.gguf` in
`src/assets/` and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).
Assets are read-only and replaced on every app update.

**Written at runtime** is also supported — a valid GGUF is a header, a metadata block, a tensor
table and padded tensor data, all of which `struct` and numpy can produce — and
`llama_model_quantize` is exported, so an app can shrink a GGUF it holds. Inference writes
nothing.

### Threading

**The llama.cpp work releases the GIL** — the bindings are `ctypes.CDLL`, and ctypes drops the
lock around every foreign call. But `eval` and `generate` are not one foreign call each: they are
Python loops with foreign calls inside, and the Python between the calls holds it, in bursts of
tens of milliseconds. Model construction is the clean case — the opposite arrangement from
[`onnxruntime`](../onnxruntime), where session construction holds the lock outright.

Measured on desktop with a canary thread recording the longest gap between its own iterations
while the call runs; a canary that never gets a turn is a UI thread that never gets a frame.
Median of five, CPython 3.12 on a 10-core host, a 3.0 MB F32 model. The first three rows are the
harness checking itself.

| call | duration | longest canary stall | stall ÷ call |
| --- | --- | --- | --- |
| idle main thread (floor) | 311 ms | 0.3 ms | 0.00 |
| `hashlib.sha256` of 268 MB (releases) | 130 ms | 0.3 ms | 0.00 |
| `sum(range(60_000_000))` (holds) | 528 ms | 522.0 ms | 0.99 |
| `Llama(model_path=...)` | 444 ms | 0.4 ms | 0.00 |
| `llm.eval(...)`, 64 then 256 tokens | 93 / 188 ms | 8.2 / 26.3 ms | 0.09 / 0.14 |
| `llm.generate(...)`, 8 then 32 tokens | 440 / 597 ms | 23.0 / 18.4 ms | 0.05 / 0.03 |

Construction sits on the 0.3 ms floor. `eval` and `generate` hold the lock in bursts of 8–26 ms,
and the same two rows on a 1.6 MB Q4_0 model gave 26.9 / 42.9 ms and 12.4 / 23.6 ms. Those bursts
are the Python around each `llama_decode`, not llama.cpp. Flutter renders client-side, so they do
not drop its frames — they stall whatever Python was going to do next, which is every handler and
every `page.update()`. Durations move with machine load; the ratio column is the stable part.

So put loading and generation in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread). Two standing
Flet caveats apply: it never retrieves the worker's future, so an exception raised inside one
surfaces nowhere at all — wrap the body in `try/except Exception` — and auto-update does not reach
background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**One `Llama` object is not safe to drive from two threads at once.** `Llama.eval` mutates
`self.n_tokens`, `self.input_ids` and `self.scores` around each `llama_decode` with one llama.cpp
context behind all of it, and `run_thread` submits to a shared pool, so two quick taps really are
two writers on the same state. Hold a `threading.Lock`, or disable the control that starts the
work until it finishes, which is what the example does.

**Set both thread counts explicitly.** The defaults are chosen in Python, not by llama.cpp:
`n_threads = max(multiprocessing.cpu_count() // 2, 1)` for generation and
`n_threads_batch = multiprocessing.cpu_count()` — *all* cores — for prompt processing (a default
`Llama(...)` on a 10-core host reports 5 and 10). On a big.LITTLE phone that reaches the little
cores too, and a backgrounded app that grabs every core is throttled or killed rather than merely
slowed. `n_threads=2, n_threads_batch=4` — or `max(1, os.cpu_count() // 4)` — is the saner start;
the only way to know what it buys is to time it on the handset.

### Model files

This section decides whether your app is possible. Three terms grow: the weights, the KV cache,
and a float32 buffer numpy holds on the Python side.

**Weights are `params × bits-per-weight / 8`.** Every quantisation type is present, and the type
names in the mobile `libggml-base` match a desktop build of the same ggml one for one — `nvfp4`,
`q1_0`, `mxfp4`, `tq1_0` and the IQ family included. Bits per weight, read out of
`ggml_blck_size`/`ggml_type_size` in the shipped binaries rather than from documentation: q4_0
and q4_K 4.500, iq4_xs 4.250, q5_K 5.500, q6_K 6.562, q8_0 8.500, q3_K 3.438, q2_K 2.625,
iq2_xxs 2.062, tq1_0 1.688, iq1_s 1.562, f16 16, f32 32. So a 1B model is 562 MB at Q4, 328 MB at
Q2_K and 1,062 MB at Q8_0; 1.5B is 844 MB at Q4, 3B is 1,688 MB, 7B is 3,938 MB. Real `_K_M`
files run above the pure-type figure because they mix types — a Q4_K_M of a hand-built model came
out at 5.29 bits per weight over the whole file against Q4_K's 4.5.

**Architecture coverage is not reduced.** The binaries carry 112 distinct
`llama.cpp/src/models/*.cpp` paths, an identical set on Android and iOS, every architecture name
present in both — llama, the qwen2/qwen3 family, gemma through gemma3, phi, mistral, falcon,
bert, deepseek, granite, rwkv6, mamba/mamba2, gpt-oss and the rest. What you cannot run is a
*multimodal* model ([Things to know](#things-to-know)).

**`n_ctx` is rounded up to a multiple of 256, and `n_ctx=0` means the model's training context.**
Asking for 1, 64, 200 or 256 all give 256; 300 and 512 give 512; 513 gives 768. It matters because
`n_ctx` drives the KV cache: `n_ctx × n_layer × (n_embd_k + n_embd_v) × 2` bytes at f16, all
allocated up front. Predicted +58.7 MB going from `n_ctx` 256 to 2048 on an 8-layer, 1024-wide
model; measured +64.0 MB of peak RSS on desktop, the difference being larger compute buffers.

**`n_batch` costs a float32 buffer in Python before llama.cpp allocates anything.**
`Llama.__init__` builds `np.ndarray((n_batch, n_vocab), dtype=np.single)` — at the default
`n_batch=512` that is 65.5 MB for a 32k vocabulary, 262.7 MB for a Llama-3 128,256 one and
311.2 MB for a Qwen 151,936 one. Verified against `llm.scores.nbytes` on a 267-token vocabulary:
32 × 267 × 4 = 34,176 at `n_batch=32`. Pass `n_batch=32` or `64` explicitly; it costs
prompt-processing throughput and nothing else, and takes that buffer to 16.4 MB at a 128,256
vocabulary. (`logits_all=True` swaps `n_batch` for `n_ctx` in that shape, usually larger.)

**mmap does not lower peak RSS, so it is not a way to run a model bigger than RAM.** llama.cpp
touches every weight page while loading either way. Desktop `ru_maxrss` on a 337.8 MB F32 model at
`n_ctx=256`: 424.2 MB with `use_mmap=True` against 429.1 MB without, from a 48.2 MB baseline
(16.6 bare Python → 29.0 after numpy → 48.2 after `llama_cpp`) — the file plus 86 MB. Size the
model against that sum and the device's real budget. Leave `use_mmap=True` on anyway: mapped pages
are clean and file-backed, so the OS can evict them under pressure where anonymous pages cannot.

### App size

Roughly 1.7–2.0 MB of compressed wheel and 4.1–5.8 MB unpacked per slice. Decimal MB throughout:

| slice | wheel | unpacked |
| --- | ---: | ---: |
| Android arm64-v8a | 1.90 MB | 5.33 MB |
| Android armeabi-v7a | 1.74 MB | 4.15 MB |
| Android x86_64 | 2.00 MB | 5.78 MB |
| iOS arm64 (device) | 1.70 MB | 5.19 MB |
| iOS arm64 (simulator) | 1.77 MB | 5.24 MB |
| iOS x86_64 (simulator) | 1.90 MB | 5.61 MB |

All six slices are published, so
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) is a choice
rather than a constraint: narrow it, or use an app bundle or split APKs, when the app does not
need every ABI. These figures describe the package payload, not the amount added to the final APK
or IPA; packaging and compression determine that.

**The wheel is not the download, though.** Resolving the way `flet build` does, an Android
arm64-v8a target pulls about 9.4 MB and 6.85 MB of that is numpy, which `import llama_cpp` needs.
Nothing at the `pyproject.toml` level takes it out. The model file you ship or fetch is a
different order of magnitude again — see [Model files](#model-files).

### Android

The four bundled libraries are not files on disk on device. Flet ships site-packages as a zip and
serious-python relocates them into the APK's `jniLibs`, so the loader resolves them by bare soname
rather than by path: `llama_cpp.llama_cpp._lib._name` should print `libllama.so` rather than something under
`llama_cpp/lib/`. That is the healthy answer, and the example puts it on screen.

### iOS

The library loads out of a code-signed framework, so `llama_cpp.llama_cpp._lib._name` should print a
path inside one. That is the healthy answer here.

**Do not benchmark this package on the arm64 simulator.** It is the one shipped slice built with
`DOTPROD` and `FP16_VA`, so its `libggml-cpu` has the int8 dot-product kernels the device slice
does not have at all — see the feature table in [Things to know](#things-to-know). It is also the
only slice on which `GGML_CPU_REPACK` can engage, since the repack selector is gated on `DOTPROD`.
A simulator number overstates a phone by whatever those two are worth together.

### Other considerations

**`flet run` on your desktop does not use these wheels.** They are Android/iOS platform-tagged, so
a desktop resolve takes PyPI's sdist and builds llama.cpp locally with whatever your machine
supports. On an Apple Silicon Mac `llama_print_system_info()` then reports
`MTL : EMBED_LIBRARY = 1 | CPU : NEON = 1 | ARM_FMA = 1 | FP16_VA = 1 | DOTPROD = 1 | REPACK = 1`
— Metal *and* the dot-product kernels the phone does not have. A desktop run tells you your code
is correct and nothing about what the device will do. Validate memory footprint, and anything
resembling a token rate, on the handset.

## Things to know

- **The two loader readings above are inferred, not observed.** They come from the APK and
  IPA layouts plus the recipe's patch; nothing has loaded a model on a device yet, as
  Coverage gaps says. Both are one line to confirm in the example's header the first time
  anyone runs it.

- **CPU only, on both platforms — no Metal, no Vulkan, no OpenCL, no CUDA, no BLAS, no Accelerate
  and no OpenMP.** `ggml_backend_cpu_reg` is the only backend-registration symbol in `libggml`;
  the `blas`/`cuda`/`metal`/`opencl`/`vulkan` strings beside it are the search list
  `ggml_backend_load_all` uses for *dynamically* loaded backends, and none is built. Leave
  `n_gpu_layers` at 0. `llama_supports_gpu_offload()` is a runtime registry query, not a constant —
  it looks for a GPU device, then an accelerator, then a backend named `RPC`, and finds none.

- **The shipped device builds have no ARMv8.2 dot-product kernels, which is the most consequential
  fact on this page.** `ggml_cpu_has_dotprod` and `ggml_cpu_has_matmul_int8` both return a hard 0
  on Android arm64-v8a and on the iOS device slice, and neither carries a single `sdot` or `smmla`
  instruction. Those kernels are exactly what llama.cpp's quantised matmuls dispatch to, so a
  quantised model here runs its int8 arithmetic on plain NEON multiply-accumulate instead. **What
  that costs on a real handset with a real GGUF has not been measured — do not assume a number.**
  The compiled feature set, read off the constant-return stubs rather than inferred:

  | slice | features compiled in |
  | --- | --- |
  | Android arm64-v8a | NEON, ARM_FMA |
  | Android armeabi-v7a | NEON |
  | Android x86_64 | SSE3, SSSE3 |
  | iOS arm64 (device) | NEON, ARM_FMA |
  | iOS arm64 (simulator) | NEON, ARM_FMA, FP16_VA, **DOTPROD** |
  | iOS x86_64 (simulator) | SSE3, SSSE3 |

  `llama_print_system_info()` reports this at runtime and the example puts it on screen; it is the
  first thing to read on a device you have not tried.

- **`REPACK = 1` in that banner is not a capability.** The repack kernels are in the binaries, but
  the traits selector inside `libggml-cpu` guards every non-null return on `avx2`, `avx512`,
  `dotprod` or `matmul_int8`, and by the table above none is set on any slice except the iOS arm64
  simulator. `neon` or `sse3` alone never selects a traits object, so on a phone every tensor
  reports *"cannot be used with preferred buffer type CPU_REPACK, using CPU instead"* and nothing
  is repacked. `REPACK` is pushed into the feature list at compile time, unguarded by any
  `ggml_cpu_has_*` call, so the banner advertises it regardless. `GGML_LLAMAFILE` is genuinely not
  built.

- **An uncatchable C++ abort is a real failure mode, and no `try/except` reaches it.** Model
  *loading* is wrapped and raises an ordinary `ValueError` for a missing path, a non-GGUF file or a
  truncated GGUF. The paths *after* loading are not. A GGUF whose SPM vocabulary omits the 256
  `<0xNN>` byte tokens loads fine and then dies on the first `llm.tokenize(b"hello")` with
  `libc++abi: terminating due to uncaught exception of type std::out_of_range: unordered_map::at:
  key not found` — exit 134, with the following `except BaseException` never reached, and on
  Android no Python traceback at all. Validate model files before you use them, and treat a crash
  with no traceback as coming from here.

- **`max_tokens` is not a hard bound on generation.** The completion loop `continue`s past its own
  `len(completion_tokens) >= max_tokens` check whenever the trailing bytes look like an incomplete
  UTF-8 sequence, so a model emitting raw byte tokens keeps going. Measured on desktop on the
  example's random-weights models: `max_tokens=1` always gave 1, but across five widths and two
  seeds `max_tokens=4` gave anything from 4 to 12 and `max_tokens=32` gave 32 to 39, all with
  `finish_reason` `length`. How far it overruns depends on the model and the sampled tokens, so
  treat it as unbounded. For a hard bound drive the low-level generator yourself:
  `zip(range(n), llm.generate(prompt_tokens, temp=0.0))` returns exactly `n`.

- **`llm.scores` is uninitialised memory unless you passed `logits_all=True`.** `Llama.__init__`
  builds it with `np.ndarray(...)`, which allocates without writing, and at the default
  `logits_all=False` `Llama.eval` stores no logits at all, since sampling moved inside llama.cpp's
  sampler. Reading `llm.scores[llm.n_tokens - 1]` then gives plausible-looking floats that are not
  this model's logits: on a hand-built model they put their argmax on a different token from an
  independent numpy forward pass, where the same code with `logits_all=True` agreed to 2e-07.
  Nothing warns. The flag also changes the buffer's first dimension from `n_batch` to `n_ctx`.

- **The f16 KV cache is the dominant error term, well above float32 rounding.** The cache defaults
  to `GGML_TYPE_F16` for K and V, and on an all-float32 model that single choice accounts for
  essentially the whole gap between llama.cpp and an exact forward pass. Measured against a
  float64 numpy recomputation on hand-built models of 27k–2.9M parameters: **4.1e-04** of the logit
  range at the default, against **2.6e-07** with
  `type_k=llama_cpp.GGML_TYPE_F32, type_v=llama_cpp.GGML_TYPE_F32` — a thousandfold, and the f32
  figure is float32 epsilon. Redoing the reference pass in float32 rather than float64 moved it by
  only 2.6e-07, so this is the cache and not the compute. Pay the doubled KV memory when you are
  comparing logits or computing perplexity; leave it at f16 when you are generating text.

- **Multimodal is not built.** `llama_cpp/mtmd_cpp.py` and `llava_cpp.py` ship in every wheel but
  there is no `libmtmd`/`libllava` to load, so any multimodal chat handler raises
  `FileNotFoundError: Shared library with base name 'mtmd' not found`. The import is lazy, so plain
  text use is unaffected. A multimodal path is a recipe change, not an app-side fix.

- **`llama_cpp/server/` is packaged and is the wrong shape on a phone.** It is a FastAPI
  application, and `llama-cpp-python[server]` does resolve for mobile, so nothing stops you — but
  an HTTP server inside your own app process buys nothing the in-process `Llama` API does not, at
  several times the download. Nothing imports it unless you do.

- **`LLAMA_CPP_LIB_PATH` overrides where the loader looks** (and `MTMD_CPP_LIB` for the multimodal
  library), which is how you point it at a library you staged yourself. `llama_cpp._ggml`, the
  internal handle on `libggml`, honours neither — and it is the only route to a ggml symbol like
  `ggml_type_size`, since `libllama` re-exports none. Two more values that look like device reports
  and are not: `llama_max_devices()` is 16 and `llama_max_parallel_sequences()` is 256, both
  disassembling to a constant.

## Build notes (maintainers)

`patches/mobile.patch` enumerates its five changes in its own preamble and `meta.yaml` comments
its `CMAKE_ARGS` inline. What is left is shape, hazards, and what a green run does not prove.

### Recipe shape

**The wheel contains no compiled Python extension at all.** It is pure ctypes: `import llama_cpp`
dlopens four bundled shared libraries — `libllama` plus `libggml`, `libggml-cpu` and
`libggml-base` — out of `llama_cpp/lib/`. Same shape as [`pyzbar`](../pyzbar) and
[`python-magic`](../python-magic), except that here the libraries travel inside this wheel rather
than in a companion `flet-lib*` one.

The build is a plain scikit-build-core sdist build with every backend switched off. The structural
decision worth recording is that the four libraries stay **shared** and bundled rather than
static-linked into one object or split into a `flet-libllama` recipe. That is what forces all the
loader work in the patch, and why this is Pattern H rather than the self-contained single extension
[`onnxruntime`](../onnxruntime) is. No native recipe sits under this one because the libraries have
no consumer other than this wheel.

Two platform consequences. On Android none of the four carries `RUNPATH` or `RPATH`; they resolve
each other purely by `DT_NEEDED` and soname, plus `libc++_shared`, `libm`, `libdl` and `libc`.
That absence is what makes the `jniLibs` delivery work, and that `libc++_shared` is why the Android
wheels carry `Requires-Dist: flet-libcpp-shared (>=27.2.12479018)` and the iOS ones do not. On iOS
all twelve dylibs are already `MH_DYLIB` marked `NOUNDEFS` (`otool -hv`), so forge's
`MH_BUNDLE`-to-`MH_DYLIB` conversion in `fix_wheel` never engages.

No [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is needed,
for a non-obvious reason: the loader *does* build paths from `__file__`, and on Android every one
of those probes misses inside the zipped site-packages — only the patch's bare-soname fallback
carries it. Verified by opening the example's APK: all four libraries sit in `lib/<abi>/` at
byte-for-byte the wheel's sizes, and `llama_cpp/lib/` inside `assets/sitepackages.zip` holds only
text files with no `.soref` marker. Compile-to-`.pyc` is safe: no `importlib.resources`,
`pkg_resources`, `pkgutil` or `getsource` anywhere in the package.

### Upgrade hazards

- **The loader.** `llama_cpp/_ctypes_extensions.py` is the file the patch rewrites, and the first
  thing to break if upstream restructures loading. The failure is
  `FileNotFoundError: Shared library with base name 'llama' not found` at import on device, from a
  wheel that built green.
- **The CPU feature set.** `meta.yaml` passes `-DGGML_NATIVE=OFF` and no `GGML_CPU_ARM_ARCH`, so
  each toolchain's own default baseline is what gets compiled; why that lands differently on the
  iOS device and iOS arm64 simulator slices is not something the binaries explain. If somebody
  wants the int8 kernels back, the levers are `GGML_CPU_ARM_ARCH=armv8.2-a+dotprod` (which drops
  pre-2017 devices) or a runtime-dispatch multi-variant build; either changes the feature table in
  [Things to know](#things-to-know), the device/simulator asymmetry [iOS](#ios) warns about, and —
  because the repack traits selector is gated on exactly these flags — whether `GGML_CPU_REPACK`
  does anything at all.
- **The backend set.** The `GGML_*=OFF` switches are in `meta.yaml`, but a backend upstream starts
  defaulting ON would land silently and falsify the first bullet of
  [Things to know](#things-to-know).
- **The dependency list and `Requires-Python`.** Four unconditional, import-time dependencies today
  — `typing-extensions`, `numpy`, `diskcache` and `jinja2` — and through them stdlib `sqlite3` and
  `multiprocessing`, so a Flet Python build missing `_sqlite3` or `_multiprocessing` fails at
  *import*, not at first use. Both ship in Flet's runtimes today. The `>=3.11` floor in
  [Install](#install) and in the example's `pyproject.toml` comes from mobile numpy, not from this
  package, so it moves when the index's numpy moves.
- **`LC_BUILD_VERSION` is not uniform across the iOS slices** despite the `ios_13_0` in every
  filename: device (platform 2) and x86_64 simulator say 13.0, the arm64 simulator says 14.0. It
  bites nothing Flet supports; it is here so a slice comparison that opens one binary does not
  generalise.
- **Dead weight worth trimming.** The wheel writes 20 C headers (270,583 B) into `include/` at the
  *site-packages root* — payload nobody needs, under a directory name any other wheel shipping
  headers would collide with. `llama_cpp/lib/` also carries four `cmake/` files and a
  `pkgconfig/llama.pc` (~20 KB) that leaks the CI machine's build directory, and
  `llama_cpp/server/` adds 69,755 B. Together about 0.36 MB of the ~5.2 MB unpacked, none of it
  reachable by an app.

### Re-verification checklist

- **The backend set:** `llvm-strings libggml.so | grep -E '^ggml_backend_[a-z0-9_]*_reg$'` —
  `ggml_backend_cpu_reg` plus `ggml_backend_dev_backend_reg` (the accessor, not a backend) is the
  passing answer. Corroborating negatives: zero
  `MTLDevice`/`Metal`/`vDSP`/`cblas_`/`Accelerate`/`CoreML` strings in the four iOS device dylibs,
  zero `vulkan`/`opencl`/`cuda` in the Android libraries outside that search list, and no
  `omp_`/`GOMP`/`__kmpc_` anywhere.
- **The dot-product claim:** `llvm-objdump -d | grep -cw sdot` (and `smmla`) over all four Android
  arm64-v8a `.so` files and all four iOS device dylibs must return 0 for every one of the eight,
  while the iOS arm64 simulator's `libggml-cpu.dylib` carries 897 `SDOT`. Read the feature table
  off the constant-return stubs, not off the build flags.
- **The repack claim:** 217 exported symbols matching `repack` on Android arm64-v8a and 261 in the
  iOS device dylib's table, 178 of the iOS ones demangling to
  `ggml::cpu::repack::tensor_traits<...>` — all present, all unreachable. Re-disassemble the traits
  selector rather than trusting the symbol count, and A/B two desktop builds with a real Q4_0 GGUF:
  a `DOTPROD = 1` build repacks seven tensors and allocates `CPU_REPACK model buffer size =
  1.41 MiB`, a device-shaped one allocates none. `ggml_cpu_has_dotprod`/`ggml_cpu_has_matmul_int8`
  disassemble to `mov w0, wzr; ret` on the device slices.
- **Android 16 KB alignment.** Every `PT_LOAD` segment of all twelve Android `.so` files must stay
  16 KB (`0x4000`) aligned.
- **Every size on the page** was measured off the cp314 build-2 wheels and a `pip download` against
  pypi.flet.dev. They are decimal MB, so re-measure from byte counts rather than with `du -h`.
- **Every behavioural figure on this page is desktop.** The GIL table, the KV-cache and `n_ctx`
  measurements, the `max_tokens` sweep and the mmap RSS staging all came off a desktop install
  built from PyPI's sdist — which, per [Other considerations](#other-considerations), is a
  *different build* with Metal and `DOTPROD`. What carries over is the Python layer, which is
  identical, and the shapes of the formulas; what does not is any clock or any throughput.

### Coverage gaps

`tests/test_llama_cpp_python.py` never loads a GGUF. It calls `llama_print_system_info`,
`llama_max_devices`, `llama_supports_mmap` and a backend init/free round-trip, so a green
mobile-test leg proves the four libraries load, the import chain resolves on device and the C ABI
is callable — and proves nothing about inference.

- **Nothing loads a model, generates or quantises in CI.** The
  [`hand-built-gguf`](examples/hand-built-gguf) example exercises all three; rebuild and run it on
  a bump. A test that builds a tiny GGUF in-process and asserts a token comes out would be cheap.
- **Nothing exercises the failure modes.** The uncatchable abort, the `max_tokens` overrun and the
  uninitialised `llm.scores` are reproduced on desktop only.
- **Tokens per second for a real quantised GGUF on a handset is measured nowhere in this recipe**,
  and the example deliberately does not claim to supply it. Anything on this page that reads like
  an inference rate is not one.
