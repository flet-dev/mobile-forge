# faiss-cpu

[faiss](https://github.com/facebookresearch/faiss/wiki) is Meta's similarity-search
library: give it a pile of dense float32 vectors and it answers *which of these are
closest to this one* — exactly, or approximately and much faster. That is the retrieval
half of semantic search, RAG, deduplication and "more like this", and on a phone it is
the half you can actually own: embeddings that never leave the device, answered with no
server and no network. The other half is whatever turns text or images into those
vectors, which on this index is [`onnxruntime`](../onnxruntime); if the vectors arrive as
a file rather than being computed, [`safetensors`](../safetensors) memory-maps one.

The wheel is **one** extension module with everything static-linked into it — libfaiss
and its BLAS both — so nothing else has to be found at runtime. What it is not is small:
12–18 MB of native code per slice, on top of numpy. Budget for that before you commit,
and read [Things to know](#things-to-know) for what this build leaves out (all GPU
support) and what it silently converts (anything that is not a contiguous float32 array).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "faiss-cpu",
]
```

Nothing else to configure. `numpy` and `packaging` are declared in the wheel's
`Requires-Dist` and both are **import-time** dependencies rather than optional
companions: `faiss/loader.py` does `from packaging.version import Version` at module top
and reads numpy's private `numpy._core._multiarray_umath.__cpu_features__` before it
loads the extension, so neither is skippable. numpy resolves to 2.4.6, the newest on
pypi.flet.dev; `packaging` is a pure-Python wheel from PyPI.

On Android two further distributions come along and neither needs an entry of its own:
`flet-libomp` (pinned `==27.3.13750724`) and `flet-libcpp-shared` (`>=27.2.12479018`),
which carry the NDK's `libomp.so` and `libc++_shared.so` — both are in the extension's
`DT_NEEDED`. The iOS wheel declares neither. Resolving the way `flet build` does (`pip
install --dry-run --only-binary=:all: --platform … --extra-index-url
https://pypi.flet.dev/`, py3.12) that is **5 wheels and about 12.8 MB** for Android
arm64-v8a against **3 wheels and about 10.2 MB** for iOS device.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed: the package ships no data file and nothing in its Python layer builds a
path from `__file__` (the only two mentions of it are comments), and the extension
carries a CPython ABI tag on Android (`faiss/_swigfaiss.cpython-312.so` and so on), so
Android's zipped site-packages handles it as-is.

Wheels exist for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64)
and all three iOS slices (device, and both simulator architectures), on Python 3.12,
3.13 and 3.14 — nothing is missing on either platform, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is forced on you. `Requires-Python` in the wheel is upstream's `>=3.10`; the
numpy that resolves for mobile needs 3.11.

## Storage

An index is one ordinary file, and
[`write_index` / `read_index`](https://github.com/facebookresearch/faiss/wiki/Index-IO,-cloning-and-hyper-parameter-tuning)
are the whole API for it. Put it in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— app-private, included in backups, never auto-deleted — because rebuilding it is the
only other way to get it back:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "vectors.ivf")
faiss.write_index(index, path)
index = faiss.read_index(path)
```

Ordinary paths are all it wants: a path containing a space and a non-ASCII character
round-tripped fine, and the file is exactly as large as `faiss.serialize_index()` on the
same index. A reloaded index returned bit-identical ids to the one still in memory.
Never keep an index in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

**There are two mmap flags and each covers different indexes.** `IO_FLAG_MMAP` maps an
IVF index's inverted lists; `IO_FLAG_MMAP_IFC` maps the codes of anything derived from
`IndexFlatCodes`, which means Flat and HNSW. Both are exported by these wheels. Peak RSS
in MB as `after read_index → after five searches`, each cell a fresh process run twice
(the two runs agreed to under 1 MB; one is shown):

| index | file | flags=0 | `IO_FLAG_MMAP` | `IO_FLAG_MMAP_IFC` |
| --- | --- | --- | --- | --- |
| IndexFlatL2 | 51 MB | 100.3 → 110.0 | 100.7 → 110.3 | **49.4** → 109.8 |
| IndexFlatL2 | 205 MB | 254.3 → 263.9 | 254.2 → 263.9 | **49.1** → 263.3 |
| IndexHNSWFlat | 66 MB | 113.8 → 119.6 | 114.0 → 120.0 | **63.6 → 96.8** |
| IndexHNSWFlat | 197 MB | 245.3 → 253.1 | 245.4 → 253.2 | **94.8 → 141.5** |
| IndexIVFFlat | 52 MB | 103.0 → 108.2 | **49.7 → 55.7** | 49.2 → 55.3 |
| IndexIVFFlat | 208 MB | 260.1 → 265.4 | **49.3 → 58.6** | 50.2 → 59.5 |

Ids came back identical in every cell, which is the trap: `read_index` accepts either flag
on any index and returns the same answers, so a flag that did nothing looks exactly like
one that worked. The other thing the table says is that an exhaustive `IndexFlat` search
reads every vector, so mmap makes the *load* free and leaves the pages file-backed and
reclaimable but does not lower the peak during a search — where HNSW and IVF, which touch
a fraction of the data, keep the saving the whole way through. Passing both flags at once
raises `RuntimeError: … mmap only supported for File objects` on an IVF index.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`nearest`](examples/nearest) — 20,000 embeddings indexed three ways, graded against a
  numpy answer, with the index saved and mmap-reloaded from app storage.

## Threading

**Every wrapped call releases the GIL — search, add and train alike.** Measured with a
pure-Python spin loop in a second thread and two controls, `omp_set_num_threads(1)` so
CPU contention could not be mistaken for the GIL: the canary ran at 28.9 M iterations/s
against `time.sleep` (GIL free) and 0.59 M against a Python busy loop (GIL held), and
30.1 M during `IndexFlatL2.search`, 31.4 M during `IndexIVFFlat.train`, 32.7 M during
`IndexIVFFlat.add` and 31.6 M during `IndexHNSWFlat.add` — indistinguishable from free.
The mechanism is a single `%exception { Py_BEGIN_ALLOW_THREADS … }` block in
`faiss/python/swigfaiss.swig` covering every declaration between it and the bare
`%exception;` that closes it, and `PyEval_SaveThread` / `PyEval_RestoreThread` are
undefined symbols in both the Android and the iOS extension.

So [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
buys real concurrency here, which matters because building an index is exactly the kind
of multi-second job that freezes a phone. The two standing Flet caveats apply: `run_thread`
never retrieves the worker's future, so an exception raised inside one surfaces nowhere at
all — wrap the body in `try/except Exception` — and auto-update does not reach background
threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

What happens *inside* one call differs by platform, and the difference is total. On
Android the extension has a `DT_NEEDED` on `libomp.so` and 38 undefined OpenMP symbols
(27 `__kmpc_*` and 11 `omp_*`, `__kmpc_fork_call` among them), so faiss's
`#pragma omp parallel` regions really run across
cores and `faiss.omp_set_num_threads()` really works. On iOS there is not one `__kmpc_*`
symbol in the binary and the whole `omp_*` API is defined inside it by a serial stub
(`recipes/flet-libomp`) whose `omp_get_max_threads()` is `return 1` and whose
`omp_set_num_threads()` is a no-op — iOS is single-threaded, permanently. Same API, same
results, different wall clock. Do not size an iOS feature from an Android measurement.

One consequence is worth knowing before you compare two runs: **HNSW graph construction is
not reproducible when OpenMP is active.** Building the same 20,000-vector
`IndexHNSWFlat(M=32)` four times over identical input gave recall@10 of 0.919, 0.959,
0.928 and 0.938 at `efSearch=64`; pinned to one thread it gave 0.948 three times out of
three. IVF is reproducible either way — `ClusteringParameters.seed` already defaults to
1234, so k-means training is seeded unless you change it.

Every behavioural figure on this page was measured on a desktop install of exactly
`faiss-cpu==1.14.3` rather than on a device; what carries over is the code, not the clock.
The bridge is narrow but real — the shipped `.py` files are byte-identical on both
platforms, one C++ source tree builds every slice, and the two things that genuinely
differ (OpenMP and NEON) are called out where they matter. The
[`nearest`](examples/nearest) example exists so the numbers that matter can be read off a
phone instead.

## Android notes

`flet-libomp` and `flet-libcpp-shared` ride along automatically and add 961,440 and
1,292,904 bytes of `.so` on arm64-v8a. All three ABIs are built with 16 KB page
alignment (`PT_LOAD` alignment `0x4000`), which Android 15 requires.

**arm64-v8a is the only slice in either platform with NEON kernels compiled in.**
faiss gates them on `CMAKE_SYSTEM_PROCESSOR MATCHES "(aarch64|arm64|ARM64)"`, which the
NDK toolchain sets and the iOS cross-build does not: `SIMDLevel::ARM_NEON` appears 191
times in the arm64-v8a binary and **zero** times in armeabi-v7a, x86_64 and all three iOS
slices, which carry ~200 `SIMDLevel::NONE` instantiations instead.
`faiss.get_compile_options()` reports the compiled-in level and names nothing at all when
it is `NONE`, which makes it the cheapest tell of which slice you are on — the
[`nearest`](examples/nearest) example prints it. Correctness is unaffected; the FastScan
families (`IndexPQFastScan`, `IndexIVFPQFastScan`, `IndexRaBitQFastScan`) just run faiss's
emulated-SIMD implementation everywhere else.

**Searching a large `IndexFlat` with a handful of queries at a time takes a code path
this build has never been tested on.** `faiss/utils/distances.cpp` switches
`knn_L2sqr` / `knn_inner_product` to `knn_db_parallel_impl` when there is no `IDSelector`,
`omp_get_max_threads() > 1`, the query count is *below* the thread count and the database
holds at least `max(10000, threads * 1024)` vectors — and that function calls `sgemm_` from inside
`#pragma omp parallel`. Android compiles those pragmas for real, and the OpenBLAS linked
into the extension is built `USE_THREAD=0 NUM_THREADS=1` with no `USE_LOCKING`, which in
OpenBLAS 0.3.33 compiles every lock around `blas_memory_alloc`'s buffer-table scan out of
existence, leaving an unguarded test-then-set. **This has not been observed failing on a
device** — the recipe's only test uses 100 vectors, two orders of magnitude below the
threshold — but every ingredient is in the shipped wheel, and the failure mode of a
scratch-buffer race is wrong numbers rather than a crash. Three ways to stay off it, in
order of cost: search in batches of at least `faiss.omp_get_max_threads()` queries (the
example's 100-query batch is already above it); use an IVF or HNSW index, since
`IndexFlat.cpp` is the only index that calls these two functions at all — though
`faiss.knn()` calls them directly whatever index you hold; or call
`faiss.omp_set_num_threads(1)` once at startup, which switches the branch off and gives
up multi-core faiss with it. iOS is immune — `omp_get_max_threads()` is the stub's
constant 1.

| slice | wheel | unpacked | the `.so` alone |
| --- | --- | --- | --- |
| arm64-v8a | 5,071,994 | 19,424,195 | 18,346,240 |
| x86_64 | 4,606,978 | 17,552,208 | 16,474,256 |
| armeabi-v7a | 4,363,408 | 13,031,669 | 11,953,712 |

armeabi-v7a is the least-exercised slice: its 32-bit ABI is one of the two cases
`patches/swig-int64-wordsize.patch` exists for, it gets no NEON, and a 32-bit address
space caps total index size well below what `N * d * 4` suggests. Dropping it costs
nothing else — 64-bit has been mandatory for Play Store uploads since 2019:

```toml
[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

## iOS notes

**The extension needs no fixing up.** All three slices are already `MH_DYLIB` marked
`NOUNDEFS` (`otool -hv`), which is the filetype Flet 0.86's iOS packaging links, so the
`MH_BUNDLE` conversion other recipes on this index depend on never engages here. Its
whole linkage is `/usr/lib/libc++.1.dylib` and `/usr/lib/libSystem.B.dylib` — the OS's own
C++ runtime, where Android needs `flet-libcpp-shared` — plus its own install name, and
there is no companion wheel. The file is `faiss/_swigfaiss.so` with no ABI tag, where the
Android wheels carry one.

**The deployment target is not the same on all three slices.** `LC_BUILD_VERSION` reads
platform 2 (iOS) minos 13.0 on the device slice and platform 7 (iOS simulator) minos 13.0
on the x86_64 simulator, but **minos 14.0** on the arm64 simulator — above the `ios_13_0`
in every filename. It bites nothing on a phone Flet supports, and it is recorded here
because a slice comparison that opens one binary and generalises will get it wrong. Same
discrepancy as [`tokenizers`](../tokenizers) and [`protobuf`](../protobuf) document.

**iOS is single-threaded faiss** and has no NEON kernels; see
[Threading](#threading) and [Android notes](#android-notes) for both. Nothing links
Accelerate or vecLib either — `_sgemm_`, `_dgemm_` and `_sgemv_` are defined *inside* the
extension, from the same static OpenBLAS Android uses, and the strings `Accelerate.framework`
and `vecLib` appear zero times. That is what makes the arithmetic identical across every
slice; it is also why iOS gets no benefit from Apple's tuned BLAS.

| slice | wheel | unpacked | the `.so` alone |
| --- | --- | --- | --- |
| arm64 (device) | 3,493,401 | 14,459,545 | 13,381,696 |
| arm64 (simulator) | 3,671,076 | 14,685,808 | 13,607,952 |
| x86_64 (simulator) | 4,260,952 | 15,750,297 | 14,672,440 |

## Things to know

- **A failed extension load calls `sys.exit(1)`, not `raise`.** The last block of
  `faiss/loader.py` catches `ModuleNotFoundError` around `from .swigfaiss import *`, logs
  a long message about `FAISS_OPT_LEVEL`, and exits. In a Flet app that is a `SystemExit`
  coming out of an import, which `except ImportError` does not catch. Import faiss at
  module top so it fails at launch rather than inside a handler.
- **Do not set the `FAISS_OPT_LEVEL` environment variable.** When it is set the loader
  makes it the *only* instruction set it considers and tries `faiss.swigfaiss_avx2` /
  `_avx512` / `_avx512_spr` / `_sve` — none of which is in these wheels, which contain a
  single `faiss/_swigfaiss*.so`. The `ImportError` is caught and it falls back, so the
  only cost is a confusing log line, but there is nothing to gain. The loader takes that
  same fallback on its own whenever numpy's `__cpu_features__` reports AVX2, AVX-512 or
  SVE, so a log line about a missing `faiss.swigfaiss_avx2` is expected rather than a
  problem.
- **There is no GPU support at all, unlike upstream's desktop wheels.**
  `faiss.get_num_gpus()` is compiled as `return 0`, and the shipped `faiss/swigfaiss.py`
  is missing exactly the three names the same-version PyPI macOS wheel has —
  `StandardGpuResources`, `index_cpu_to_gpu`, `index_gpu_to_cpu` — a 23-line difference in
  a 650 KB file. `MAC_METAL` appears zero times in all six mobile binaries, and neither
  wheel carries the `MetalDistance.metallib` or the separate `libfaiss.dylib` that the
  macOS one ships. `faiss.gpu_wrappers` is pure Python and still imports, but all five
  functions in it need a `StandardGpuResources` you cannot construct here.
- **The CPU index family is all there — 109 `Index*` / `IDSelector*` classes**, byte-for-byte
  the same list on both platforms: Flat (L2 and IP), IVFFlat, IVFPQ, IVFScalarQuantizer,
  HNSW (Flat/PQ/SQ), PQ, ScalarQuantizer, LSH, NSG, RaBitQ, the FastScan variants,
  IDMap/IDMap2, IndexRefineFlat, IndexPreTransform, the binary indexes, and
  IDSelectorRange/Array/Batch/Bitmap/And/Or/Not. `faiss.index_factory` builds all the usual
  strings; `faiss.Kmeans`, `faiss.PCAMatrix` and `faiss.normalize_L2` are present.
  [Guidelines to choose an index](https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index)
  applies here unchanged apart from its GPU advice.
- **Index memory is exactly predictable, so size it before you build it.** Verified
  against `faiss.serialize_index()` at several shapes: `IndexFlat` is `N*d*4` plus a
  45-byte header (its `codes.size()` was 10,240,000 for N=20,000 d=128, to the byte);
  `IndexIVFFlat` is `N*(d*4+8) + nlist*d*4` (7,940,491 measured against 7,938,304
  predicted); `IndexIVFPQ` with `m` sub-quantizers at 8 bits is
  `N*(m+8) + nlist*d*4 + m*256*(d/m)*4` (598,836 against 596,608 — **12.8× smaller** than
  the flat index over the same vectors); and `IndexHNSWFlat(M)` is the flat cost plus
  exactly `N*(8*M+16)` bytes of graph, independent of `d` (measured at 272 B/vector for
  M=32 twice at different `d`, and 144 B/vector for M=16). On top of that an IVF file
  carries exactly `nlist*8 + 139` bytes of list-size header, whatever `N` and `d` are
  (2,187 at `nlist=256`, 8,331 at 1024), and an HNSW file carries its upper-level graph,
  which is 0.12–0.33 B/vector — under 0.1% either way.
- **Approximate is a real trade, and both families need clustered data.** On the
  [`nearest`](examples/nearest) example's 20,000 clustered 96-dimensional vectors,
  `IVF256,Flat` recall@10 climbs 0.672 → 0.909 → 0.993 → 1.000 as `nprobe` goes
  1 → 2 → 4 → 8, and `HNSW32` climbs 0.804 → 0.861 → 0.905 → 0.948 → 0.978 → 0.988 as
  `efSearch` goes 8 → 256, single-threaded. Change nothing but the base distribution —
  `rng.random(...)` in place of the cluster draw, same inner-product metric, same
  normalisation, same queries, which is what a demo built on `rand()` gives you — and IVF
  falls to 0.055 at `nprobe=1` and 0.530 at 32, HNSW to 0.275 at `efSearch=8`. HNSW
  recovers with effort where IVF does not (0.937 against 0.530 at the top of each sweep),
  but pays for it in memory: at M=32 the graph adds 71% on top of the flat vectors.
  Product quantisation is the opposite bargain —
  `IVF256,PQ12x8` over the clustered vectors is 598,836 bytes against the flat index's
  7,680,045, and its recall plateaus at 0.466 no matter how far `nprobe` is raised, where
  `IVF256,Flat` reaches 1.000 by `nprobe=8`. Wrap it in `IndexRefineFlat` if you need
  both, or stay on `IVF,Flat` until `N*d*4` actually hurts.
- **Anything that is not a C-contiguous float32 array is silently converted.** A float64
  query array and a Fortran-ordered one both return the same ids as the float32 original,
  with no warning — `faiss/class_wrappers.py` runs `ascontiguousarray(..., dtype='float32')`
  for you. The cost is a transient copy per call, and the same conversion at `add()` time
  means a float64 array built by `np.random.rand(...)` is briefly resident three times
  over: the float64 original, faiss's float32 conversion, and the index's own copy.
  Generate or load embeddings as float32 from the start. That `add()` copies was checked
  directly — mutating the source array afterwards changed nothing.
- **Two failure shapes read as a Flet crash with no explanation.** A wrong-width array
  passed to `add()` or `search()` raises a bare `AssertionError` whose message is the
  empty string; searching for more neighbours than the index holds does not raise at all,
  it pads with id `-1` and distance `3.4028235e+38` (an `ntotal=3` index searched with
  `k=5` returns its three ids in distance order and then two `-1`s; an empty index returns
  nothing but `-1`). Check `x.shape[1] == index.d` and `x.dtype == np.float32`
  yourself, and filter `I[i] >= 0` before using ids as indices into your own metadata list
  — a `-1` silently picks the last element. An unhandled exception in an event handler
  makes Flet send `SESSION_CRASHED`. Adding to an untrained IVF index does say what is
  wrong: `RuntimeError: Error in … IndexIVFFlat::add_core …`.
- **`faiss.TimeoutGuard` is not a way to bound a search.** It only fires at faiss's own
  interrupt checkpoints, which for a BLAS search means once per block of
  `distance_compute_blas_query_bs` (4096) queries. Measured: a 500-query search against
  200,000 vectors ran to completion in 0.96 s under `TimeoutGuard(0.24)`, while the same
  search with 20,000 queries did raise, after 1.35 s of a 3.01 s baseline. An
  `IndexHNSWFlat.add` of 50,000 vectors under `TimeoutGuard(0.3)` raised after 0.43 s.
  Size the work instead of trying to abort it, and keep it in `page.run_thread`.
- **`faiss.contrib` ships and nearly all of it imports with nothing extra.** `evaluation`,
  `exhaustive_search`, `factory_tools`, `inspect_tools`, `ivf_tools`, `ondisk`,
  `clustering`, `datasets`, `vecs_io`, `rpc`, `client_server` and `big_batch_search` all
  import; only `torch_utils` fails (`No module named 'torch'`), and `clustering` prints
  `scipy not accessible, Python k-means will not work` at import — pypi.flet.dev carries a
  [`scipy`](../scipy) if you want that path.
- **Size.** 3.49–5.07 MB to download and 13.0–19.4 MB unpacked, of which the extension is
  92–94% (per-slice tables in [Android notes](#android-notes) and
  [iOS notes](#ios-notes)). The remaining 1,077,955 bytes on Android arm64-v8a are
  `swigfaiss.py` at 650,107, `faiss/contrib/` at 142,571, `__init__.pyi` at 141,474, the
  rest of `faiss/*.py` at 116,501 and `dist-info` at 27,302 — and serious_python's mobile
  cleanup list carries `**.pyi` and `**.typed`, so the stub file and `py.typed` are
  dropped on the way into the app. The Python payload is byte-identical between the
  Android and iOS wheels. There is nothing worth trimming: `faiss/contrib` is the only
  removable package and it is 0.7% of the unpacked wheel.

## Build notes (maintainers)

`patches/swig-int64-wordsize.patch` explains the ABI split it corrects, and `meta.yaml`
comments its own non-obvious settings, so what is left here is shape and the bump
checklist.

The shape is: **one static extension and nothing else**. `BUILD_SHARED_LIBS=OFF` folds
libfaiss into `_swigfaiss`, and `flet-libopenblas` — plus, on iOS, the `flet-libomp`
serial stub — sit under `requirements.host_build` so they link in without appearing in the
consumer's `Requires-Dist`. `unzip -l` on either wheel shows 33 files and no `opt/`
directory. The one deliberate asymmetry is OpenMP: `-DOpenMP_CXX_FLAGS=-fopenmp` on
Android against a bare include path on iOS, which is what makes the pragmas compile to
`__kmpc_*` calls on one platform and to straight-line code on the other. Note also what
the recipe does *not* do — it does not reach for Accelerate on iOS, so both platforms link
the same BLAS sources rather than two different implementations.

**The one open item is `USE_LOCKING`.** `recipes/flet-libopenblas/build.sh` builds with
`USE_THREAD=0 NUM_THREADS=1` and no `USE_LOCKING`, which leaves faiss's Android build
calling `sgemm_` from inside an OpenMP parallel region against an allocator whose locks
are compiled out — see [Android notes](#android-notes). `USE_LOCKING=1` there is the clean
fix, and it would also touch that recipe's two other consumers, `numpy` and `scipy`.
Nothing has reproduced the race, so it has not been done. Anyone taking it on should also
give faiss a device test above the 10,000-vector, few-queries threshold, which is the
shape CI has never run.

On a bump — and everything above this section is a claim about one build that a bump can
falsify without the build failing:

- **`tests/test_faiss_cpu.py` is a single function** over 100 vectors in a `IndexFlatL2`.
  It proves the extension imports and that exact search works, and nothing else: no IVF,
  no HNSW, no PQ, no persistence, no OpenMP, no BLAS path of any size. A green CI run
  confirms almost none of this page. Worth adding, in rough order of value: a
  `write_index`/`read_index` round trip through `FLET_APP_STORAGE_DATA`, an IVF train +
  search, `get_num_gpus() == 0`, and a `IndexFlat` search over ≥10,000 vectors with one
  query, which is the only way the Android BLAS question gets an answer.
- **The GPU claim.** `FAISS_ENABLE_GPU=OFF` is in `meta.yaml`, but the consequence
  documented above — that `swigfaiss.py` differs from the desktop wheel by exactly the
  three GPU names — is a property of upstream's SWIG interface, which moves. Re-diff
  against the same-version PyPI wheel.
- **The NEON asymmetry.** It rests on faiss's `CMAKE_SYSTEM_PROCESSOR` test in
  `faiss/CMakeLists.txt`, not on anything this recipe sets, so a bump can turn iOS NEON on
  (good) or arm64-v8a NEON off (bad) with no build failure either way. `strings -a … |
  grep -c 'SIMDLevel::ARM_NEON'` on each of the six slices is the check.
- **Every behavioural figure above** — the GIL rates, the mmap RSS, the memory formulas,
  the recall series, the `TimeoutGuard` results — came off a desktop install of exactly
  `faiss-cpu==1.14.3`. The serialisation layout and the clustering defaults
  (`ClusteringParameters.seed = 1234`, `niter = 25`) are upstream's and can move. The
  [`nearest`](examples/nearest) example recomputes all of them on screen, which is why it
  is the thing to run after a bump — and its numpy cross-check is the only assertion
  anywhere that the BLAS in this wheel is producing correct arithmetic on a real device.
- **The install closure and the two Android runtime pins.** `flet-libomp` is pinned with
  `==` in the wheel's `Requires-Dist`, so a `flet-libomp` bump silently strands this recipe
  on the old one until it is rebuilt. Re-run the pip dry-run for one Android and one iOS
  slice.
- **The sizes, the file counts and the per-slice tables.** Re-measure from the wheels the
  bump produces rather than adjusting them by eye.
