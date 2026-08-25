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
12–18 MB of native code per slice, on top of numpy. Budget for that before you commit.
Every CPU index upstream ships is here; no GPU support of any kind is. See
[Other considerations](#other-considerations) for where else this build parts company
with the desktop wheel you prototype against.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "faiss-cpu",
]
```

**Raise `requires-python` to `>=3.11`.** The faiss wheel's own `Requires-Python` is
upstream's `>=3.10`, but the numpy it resolves against on mobile declares `>=3.11`, and
uv resolves for every version in the declared range — so a project left at the `>=3.10`
that `flet create` writes has a 3.10 split with nothing to satisfy it, and `flet build`
stops with *your project's requirements are unsatisfiable*. The usual check does not
catch this one: copying the `pyproject.toml` into an empty directory and running
`uv lock` succeeds at `>=3.10`, because PyPI's desktop numpy still covers 3.10 where the
mobile wheel does not.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`nearest`](examples/nearest) — 20,000 embeddings indexed three ways, graded against a
  numpy answer, with the index saved and mmap-reloaded from app storage.

## Usage in a Flet app

Build an index once and keep it; `search` is the call you make per tap. It returns two
`(queries, k)` arrays — distances and ids — and the ids index straight back into whatever
metadata you are holding:

```python
index = faiss.IndexFlatIP(dim)     # exact search, inner product
index.add(vectors)                 # (n, dim), C-contiguous float32

distances, ids = index.search(query, 10)
hits.controls = [ft.Text(titles[i]) for i in ids[0] if i >= 0]
page.update()
```

`hits` is an ordinary [`ft.Column`](https://flet.dev/docs/controls/column/). The `i >= 0`
filter is not decoration: a search asking for more neighbours than the index holds pads
the result with id `-1`, and `titles[-1]` quietly returns your last title instead of
raising.

### Storage

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

Never keep an index in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches). Ordinary paths are all it wants — a path with a space and
a non-ASCII character in it round-tripped fine — and the file is exactly as large as
`faiss.serialize_index()` on the same index, so the formulas under
[Choosing an index](#choosing-an-index) size the file as well as the memory.

**There are two mmap flags and each covers different indexes.** `IO_FLAG_MMAP` maps an
IVF index's inverted lists; `IO_FLAG_MMAP_IFC` maps the codes of anything derived from
`IndexFlatCodes`, which means Flat and HNSW. Both are exported by these wheels. Peak RSS
in decimal MB as `after read_index → after five searches`, each cell a fresh process on a
desktop install, run twice (the two runs agreed to under 1 MB; one is shown). To take the
same reading on a device, use `ru_maxrss` from
[`resource.getrusage`](https://docs.python.org/3/library/resource.html#resource.getrusage)
— kilobytes on Android, bytes on iOS, and only if `resource` imports on your build. Nothing
here establishes it is present in Flet's mobile Python, and this index has been bitten by
exactly that gap before (`_posixshmem` on iOS), so check before designing around it:

| index | file | flags=0 | `IO_FLAG_MMAP` | `IO_FLAG_MMAP_IFC` |
| --- | --- | --- | --- | --- |
| IndexFlatL2 | 51 MB | 100.3 → 110.0 | 100.7 → 110.3 | **49.4** → 109.8 |
| IndexFlatL2 | 205 MB | 254.3 → 263.9 | 254.2 → 263.9 | **49.1** → 263.3 |
| IndexHNSWFlat | 66 MB | 113.8 → 119.6 | 114.0 → 120.0 | **63.6 → 96.8** |
| IndexHNSWFlat | 197 MB | 245.3 → 253.1 | 245.4 → 253.2 | **94.8 → 141.5** |
| IndexIVFFlat | 52 MB | 103.0 → 108.2 | **49.7 → 55.7** | 49.2 → 55.3 |
| IndexIVFFlat | 208 MB | 260.1 → 265.4 | **49.3 → 58.6** | 50.2 → 59.5 |

Ids came back identical in every cell, which is the trap: `read_index` accepts either
flag on any index and returns the same answers, so a flag that did nothing looks exactly
like one that worked. **Never treat matching results as evidence that a mapping engaged —
watch memory instead.** The other thing the table says is that an exhaustive `IndexFlat`
search reads every vector, so mmap makes the *load* free and leaves the pages file-backed
and reclaimable but does not lower the peak during a search, where HNSW and IVF touch a
fraction of the data and keep the saving the whole way through. Passing both flags at
once raises `RuntimeError: … mmap only supported for File objects` on an IVF index.

### Threading

**Every wrapped call releases the GIL — search, add and train alike.** A pure-Python
canary thread ran at full speed through `IndexFlatL2.search`, `IndexIVFFlat.train`,
`IndexIVFFlat.add` and `IndexHNSWFlat.add`, indistinguishable from the same canary
against `time.sleep` and roughly fifty times faster than against a Python busy loop that
does hold it.

So [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
buys real concurrency here, which matters because building an index is exactly the kind
of multi-second job that freezes a phone. The two standing Flet caveats apply:
`run_thread` never retrieves the worker's future, so an exception raised inside one
surfaces nowhere at all — wrap the body in `try/except Exception` — and auto-update does
not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**What happens inside one call differs by platform, and the difference is total.** On
Android the extension links the NDK's OpenMP runtime, so faiss's `#pragma omp parallel`
regions really run across cores and `faiss.omp_set_num_threads()` really works. On iOS
the whole `omp_*` API is a serial stub compiled into the extension:
`omp_get_max_threads()` returns 1 and `omp_set_num_threads()` is a no-op. iOS is
single-threaded faiss, permanently. Same API, same answers, different wall clock — do not
size an iOS feature from an Android measurement.

One consequence matters before you compare two runs: **HNSW graph construction is not
reproducible when OpenMP is active.** The same 20,000-vector `IndexHNSWFlat(M=32)` built
four times over identical input gave recall@10 between 0.919 and 0.959 at `efSearch=64`,
where pinning it to one thread gave 0.948 three times out of three. So a recall
difference between two Android runs may be the graph, not your change; on iOS it cannot
be. IVF is reproducible either way — `ClusteringParameters.seed` defaults to 1234, so
k-means training is seeded unless you change it.

### Choosing an index

**Nothing was dropped in the cross-build except GPU.** The `Index*` and `IDSelector*`
class list is byte-for-byte identical on Android and iOS, `faiss.index_factory` builds
the usual strings, and
[Guidelines to choose an index](https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index)
applies here unchanged apart from its GPU advice.

**Index memory is exactly predictable, so size it before you build it.** These are
formulas, not rules of thumb — each was checked against `faiss.serialize_index()` at
several shapes, to the byte. `IndexFlat` is `N*d*4` plus a 45-byte header. `IndexIVFFlat`
is `N*(d*4+8) + nlist*d*4`, plus exactly `nlist*8 + 139` bytes of list-size header
whatever `N` and `d` are. `IndexHNSWFlat(M)` is the flat cost plus `N*(8*M+16)` bytes of
graph, independent of `d` — 272 B/vector at M=32, 144 at M=16. `IndexIVFPQ` with `m`
8-bit sub-quantizers is `N*(m+8) + nlist*d*4 + m*256*(d/m)*4`, which over 20,000
96-dimensional vectors comes out **12.8× smaller** than the flat index over the same
vectors.

**Approximate is a real trade, and both families need clustered data.** On the
[`nearest`](examples/nearest) example's 20,000 clustered 96-dimensional vectors,
recall@10 climbs with effort, and where it stops climbing is the decision:
`IVF256,Flat` goes 0.672 → 0.909 → 0.993 → 1.000 as `nprobe` doubles 1 → 2 → 4 → 8, so the
last doubling buys 0.007 and `nprobe=4` is where to stop paying; `HNSW32` goes
0.804 → 0.861 → 0.905 → 0.948 → 0.978 → 0.988 as `efSearch` doubles 8 → 256, single-threaded. Change nothing but the base distribution —
`rng.random(...)` in place of the cluster draw, which is what a demo built on `rand()`
gives you — and IVF falls to 0.06 at `nprobe=1` and only reaches 0.53 at 32, where HNSW
starts at 0.28 and does recover with effort — 0.937 against IVF's 0.530 at the top of each
sweep, which is the whole reason to prefer HNSW on unclustered data. So benchmark on your own embeddings, not on
noise. HNSW pays for that recovery in memory (at M=32 the graph adds 71% on top of the
flat vectors); product quantisation is the opposite bargain, `IVF256,PQ12x8` being a
twelfth of the flat index's size with recall that plateaus at 0.47 however far `nprobe`
is raised. Wrap it in `IndexRefineFlat` if you need both, or stay on `IVF,Flat` until
`N*d*4` actually hurts.

**Only Android arm64-v8a has NEON kernels compiled in.** faiss gates them on a CMake
processor test that the NDK toolchain sets and the iOS cross-build does not, so
armeabi-v7a, x86_64 and all three iOS slices run faiss's emulated-SIMD implementation
instead. Correctness is unaffected, and it is the FastScan families
(`IndexPQFastScan`, `IndexIVFPQFastScan`, `IndexRaBitQFastScan`) where the difference
shows most. `faiss.get_compile_options()` reports the compiled-in level and names nothing
at all when there is none, which makes it the cheapest tell of which slice you are on —
the [`nearest`](examples/nearest) example prints it.

### App size

The wheel is approximately 3.5–5.1 MB compressed and 13.0–19.4 MB unpacked per slice, of
which the single extension is 92–95%. Installing `faiss-cpu` also brings numpy, which is
most of the remainder. There is nothing worth removing with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup):
`faiss/contrib` is the only removable package and it is under 1% of the unpacked wheel.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) to
the ABIs you actually ship. armeabi-v7a is the one to drop first: it is the
least-exercised of the six slices, it gets no NEON, and a 32-bit address space caps total
index size well below what `N*d*4` suggests. Dropping it costs nothing else — 64-bit has
been mandatory for Play Store uploads since 2019:

```toml
[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

These figures describe the package payload, not the exact amount added to the final APK
or IPA; packaging and compression determine that result.

### Other considerations

A desktop `flet run` uses PyPI's wheel and the Python API is the same, but the build is
not, in two ways that mislead anyone who prototypes there.

**It has GPU support and this one has none.** `faiss.get_num_gpus()` is compiled as
`return 0` here, and the shipped `faiss/swigfaiss.py` is missing exactly the three names
the same-version PyPI macOS wheel has: `StandardGpuResources`, `index_cpu_to_gpu` and
`index_gpu_to_cpu`. Neither mobile wheel carries the `MetalDistance.metallib` or the
separate `libfaiss.dylib` that the macOS one ships. `faiss.gpu_wrappers` is pure Python
and still imports, so a GPU path written on a laptop fails at the first
`StandardGpuResources()` rather than at import.

**Nothing links Accelerate or vecLib on iOS.** `sgemm_`, `dgemm_` and `sgemv_` are
defined *inside* the extension, from the same static OpenBLAS the Android slices use.
That is what makes the arithmetic identical across every slice; it is also why iOS gets
no benefit from Apple's tuned BLAS, and why a latency budget taken on a Mac does not
transfer to a phone.

Every behavioural figure on this page — the GIL result, the mmap table, the memory
formulas, the recall series, the `TimeoutGuard` timings — was measured on a desktop
install of the version this recipe builds, not on a device. What carries over is the
code, not the clock. The [`nearest`](examples/nearest) example exists so the numbers that
matter can be read off a phone instead.

## Things to know

- **A failed extension load calls `sys.exit(1)`, not `raise`.** The last block of
  `faiss/loader.py` catches `ModuleNotFoundError` around `from .swigfaiss import *`, logs
  a long message about `FAISS_OPT_LEVEL`, and exits. In a Flet app that is a `SystemExit`
  coming out of an import, which `except ImportError` does not catch. Import faiss at
  module top so it fails at launch rather than inside a handler.
- **Do not set the `FAISS_OPT_LEVEL` environment variable.** When it is set the loader
  makes it the *only* instruction set it considers and tries `faiss.swigfaiss_avx2` /
  `_avx512` / `_avx512_spr` / `_sve`, none of which is in these wheels — they contain a
  single `faiss/_swigfaiss*.so`. The `ImportError` is caught and it falls back, so the
  cost is a confusing log line and there is nothing to gain. The loader takes that same
  fallback on its own whenever numpy's CPU-feature report names AVX2, AVX-512 or SVE, so
  a log line about a missing `faiss.swigfaiss_avx2` is expected rather than a problem.
- **Anything that is not a C-contiguous float32 array is silently converted.** A float64
  query array and a Fortran-ordered one both return the same ids as the float32 original,
  with no warning — `faiss/class_wrappers.py` runs
  `ascontiguousarray(..., dtype='float32')` for you. The cost is a transient copy per
  call, and the same conversion at `add()` time means a float64 array built by
  `np.random.rand(...)` is briefly resident three times over: the original, faiss's
  float32 conversion, and the index's own copy (`add()` really does copy — mutating the
  source array afterwards changed nothing). Generate or load embeddings as float32 from
  the start.
- **Two failure shapes read as a Flet crash with no explanation.** A wrong-width array
  passed to `add()` or `search()` raises a bare `AssertionError` whose message is the
  empty string; searching for more neighbours than the index holds does not raise at all,
  it pads with id `-1` and distance `3.4028235e+38` (an `ntotal=3` index searched with
  `k=5` returns its three ids in distance order and then two `-1`s; an empty index
  returns nothing but `-1`). Check `x.shape[1] == index.d` and `x.dtype == np.float32`
  yourself, and filter `I[i] >= 0` before using ids as indices into your own metadata
  list. An unhandled exception in an event handler makes Flet send `SESSION_CRASHED`.
  Adding to an untrained IVF index does say what is wrong:
  `RuntimeError: Error in … IndexIVFFlat::add_core …`.
- **On Android, search a large `IndexFlat` in batches of at least
  `faiss.omp_get_max_threads()` queries.** Below that, with no `IDSelector`, more than
  one OpenMP thread and at least `max(10000, threads * 1024)` vectors in the database,
  `faiss/utils/distances.cpp` takes a parallel branch that calls `sgemm_` from inside
  `#pragma omp parallel` — against an OpenBLAS built without locking, whose
  scratch-buffer allocator is then an unguarded test-then-set. **This has never been
  observed failing on a device**, but every ingredient is in the shipped wheel and the
  failure mode of that race is wrong numbers rather than a crash. Batching is the free
  fix; otherwise use IVF or HNSW, since `IndexFlat` is the only index reaching those
  functions — `faiss.knn()` calls them directly whatever index you hold — or call
  `faiss.omp_set_num_threads(1)` at startup and give up multi-core faiss with it. iOS is
  immune: its `omp_get_max_threads()` is the serial stub's constant 1.
- **`faiss.TimeoutGuard` is not a way to bound a search.** It only fires at faiss's own
  interrupt checkpoints, which for a BLAS search means once per block of 4096 queries. A
  500-query search against 200,000 vectors ran to completion in 0.96 s under
  `TimeoutGuard(0.24)`; the same search with 20,000 queries did raise, after 1.35 s of a
  3.01 s baseline. It is not useless everywhere: an `IndexHNSWFlat.add` of 50,000 vectors
  under `TimeoutGuard(0.3)` did raise, after 0.43 s — the checkpoints exist outside a BLAS
  search. Size the work instead of trying to abort it, and keep it in `page.run_thread`.
- **`faiss.contrib` ships and nearly all of it imports with nothing extra.** Only
  `torch_utils` fails outright (`No module named 'torch'`), and `clustering` prints
  `scipy not accessible, Python k-means will not work` at import — pypi.flet.dev carries
  a [`scipy`](../scipy) if you want that path.

## Build notes (maintainers)

`patches/swig-int64-wordsize.patch` explains the ABI split it corrects, and `meta.yaml`
comments its own non-obvious settings. What is left here is shape, hazards, and what a
green run does not prove.

### Recipe shape

**One static extension and nothing else.** `BUILD_SHARED_LIBS=OFF` folds libfaiss into
`_swigfaiss`, and `flet-libopenblas` — plus, on iOS, the `flet-libomp` serial stub — sit
under `requirements.host_build` so they link in without appearing in the consumer's
`Requires-Dist`. `unzip -l` on either wheel shows 33 files and no `opt/` directory. What
the Android wheel *does* declare, and the iOS wheel does not, is `flet-libomp` and
`flet-libcpp-shared`: the NDK's `libomp.so` and `libc++_shared.so` are both in the
extension's `DT_NEEDED`, and together they add about 2.3 MB of `.so` on arm64-v8a.

The one deliberate asymmetry is OpenMP: `-DOpenMP_CXX_FLAGS=-fopenmp` on Android against
a bare include path on iOS, which is what makes the pragmas compile to `__kmpc_*` calls
on one platform and to straight-line code on the other. Note also what the recipe does
*not* do — it does not reach for Accelerate on iOS, so both platforms link the same BLAS
sources rather than two different implementations, which is what keeps the arithmetic
identical across all six slices.

**The one open item is `USE_LOCKING`.** `recipes/flet-libopenblas/build.sh` builds with
`USE_THREAD=0 NUM_THREADS=1` and no `USE_LOCKING`, which in OpenBLAS 0.3.33 compiles
every lock around `blas_memory_alloc`'s buffer-table scan out of existence. That is the
allocator behind the Android batching advice in [Things to know](#things-to-know).
`USE_LOCKING=1` is the clean fix, and it would also touch that recipe's two other
consumers, `numpy` and `scipy`. Nothing has reproduced the race, so it has not been done.

### Upgrade hazards

- **`faiss/loader.py` reads two private things before the extension loads.** It does
  `from packaging.version import Version` at module top and inspects numpy's
  `numpy._core._multiarray_umath.__cpu_features__`. Both are import-time dependencies
  rather than optional companions, and the numpy attribute is private — a numpy that
  renames or drops it breaks the import outright, not just the `FAISS_OPT_LEVEL`
  behaviour documented above.
- **`flet-libomp` is pinned with `==` in the Android wheel's `Requires-Dist`**, so a
  `flet-libomp` bump silently strands this recipe on the old one until it is rebuilt.
- **The NEON asymmetry** rests on faiss's own `CMAKE_SYSTEM_PROCESSOR MATCHES
  "(aarch64|arm64|ARM64)"` test in `faiss/CMakeLists.txt`, not on anything this recipe
  sets, so a bump can turn iOS NEON on (good) or arm64-v8a NEON off (bad) with no build
  failure either way.
- **The GPU claim.** `FAISS_ENABLE_GPU=OFF` is in `meta.yaml`, but the consequence
  documented in [Other considerations](#other-considerations) — that `swigfaiss.py`
  differs from the desktop wheel by exactly three GPU names — is a property of upstream's
  SWIG interface, which moves.
- **`Requires-Python` is upstream's `>=3.10`** while the mobile numpy needs 3.11. That
  gap is the whole of the [Install](#install) warning and is load-bearing for the
  example's `pyproject.toml`; upstream raises its floor without ceremony.
- **`LC_BUILD_VERSION` is not uniform across the iOS slices**, despite the `ios_13_0` in
  every filename: platform 2 minos 13.0 on device, platform 7 minos 13.0 on the x86_64
  simulator, and **minos 14.0** on the arm64 simulator. It bites nothing on a phone Flet
  supports; it is recorded because a slice comparison that opens one binary and
  generalises will get it wrong.
- **The serialisation layout and the clustering defaults** (`ClusteringParameters.seed =
  1234`, `niter = 25`) are upstream's and can move, which invalidates both the memory
  formulas and the reproducibility claim.

### Re-verification checklist

- **The sizes and file counts**, re-measured from the wheels the bump produces rather
  than adjusted by eye. Decimal bytes:

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 5,071,994 | 19,424,195 | 18,346,240 |
  | Android x86_64 | 4,606,978 | 17,552,208 | 16,474,256 |
  | Android armeabi-v7a | 4,363,408 | 13,031,669 | 11,953,712 |
  | iOS arm64 (device) | 3,493,401 | 14,459,545 | 13,381,696 |
  | iOS arm64 (simulator) | 3,671,076 | 14,685,808 | 13,607,952 |
  | iOS x86_64 (simulator) | 4,260,952 | 15,750,297 | 14,672,440 |

  The Python payload is byte-identical between the Android and iOS wheels; on arm64-v8a
  it is 1,077,955 bytes, of which `swigfaiss.py` is 650,107 and `faiss/contrib/` 142,571.
  serious_python's mobile cleanup list carries `**.pyi` and `**.typed`, so the 141,474-byte
  stub file and `py.typed` are dropped on the way into the app.
- **The install closure.** Resolving the way `flet build` does (`pip install --dry-run
  --only-binary=:all: --platform … --extra-index-url https://pypi.flet.dev/`) gives 5
  wheels and about 12.8 MB for Android arm64-v8a against 3 wheels and about 10.2 MB for
  iOS device. Re-run it for one slice of each platform.
- **The NEON asymmetry.** `strings -a … | grep -c 'SIMDLevel::ARM_NEON'` on each of the
  six slices: 191 on arm64-v8a today and zero everywhere else, with ~200
  `SIMDLevel::NONE` instantiations in their place.
- **The GIL claim.** The mechanism is a single
  `%exception { Py_BEGIN_ALLOW_THREADS … }` block in `faiss/python/swigfaiss.swig`
  covering every declaration between it and the bare `%exception;` that closes it; the
  tell in a built wheel is that `PyEval_SaveThread` and `PyEval_RestoreThread` are
  undefined symbols in both extensions. A declaration moved outside that block loses the
  release silently.
- **Android package layout.** Test from zipped site-packages. Today the extension carries
  a CPython ABI tag (`faiss/_swigfaiss.cpython-312.so`), the package ships no data file
  and nothing in its Python layer builds a path from `__file__`, so no
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
  needed. Add one to consumer guidance only if a real runtime filesystem read makes it
  mandatory, and include the failure symptom.
- **Android 16 KB alignment.** All three ABIs must keep `PT_LOAD` alignment `0x4000`.
- **iOS mach-o shape.** All three slices must stay `MH_DYLIB` marked `NOUNDEFS`
  (`otool -hv`), which is why forge's `MH_BUNDLE`-to-`MH_DYLIB` conversion in `fix_wheel`
  never engages here. Their whole linkage is `/usr/lib/libc++.1.dylib` and
  `/usr/lib/libSystem.B.dylib` plus their own install name, and the file is
  `faiss/_swigfaiss.so` with no ABI tag.
- **Every behavioural figure above the Build notes** came off a desktop install of the
  version being bumped from, not a device. The [`nearest`](examples/nearest) example
  recomputes the ones that matter on screen, which is why it is the thing to run after a
  bump — and its numpy cross-check is the only assertion anywhere that the BLAS in this
  wheel is producing correct arithmetic on a real device.

### Coverage gaps

`tests/test_faiss_cpu.py` is a single function over 100 vectors in an `IndexFlatL2`. It
proves the extension imports and that exact search works, and nothing else: no IVF, no
HNSW, no PQ, no persistence, no OpenMP, no BLAS path of any size. A green CI run confirms
almost none of this page.

Worth adding, in rough order of value: a `write_index`/`read_index` round trip through
`FLET_APP_STORAGE_DATA`; an IVF train plus search; `get_num_gpus() == 0`; and an
`IndexFlat` search over at least 10,000 vectors with a single query, which is both the
shape CI has never run and the only way the Android BLAS question in
[Things to know](#things-to-know) gets an answer.
