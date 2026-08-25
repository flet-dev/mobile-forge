# faiss nearest

One screen that generates 20,000 synthetic 96-dimensional embeddings on device, indexes
them three ways, and shows what each index costs and what it gets wrong. No network, no
model file, nothing bundled — the vectors come from a fixed
[numpy](https://numpy.org/doc/stable/reference/random/generator.html) seed.

What it demonstrates:

- **A cross-check that can actually fail.** Before faiss is asked anything, the app
  computes the true top-10 for every query in numpy alone (`xq @ xb.T`, then
  `argpartition`). The
  [`IndexFlatIP`](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes) row is
  graded against that answer and the screen prints `PASS` only when recall@10 is exactly
  1.0000 *and* the largest distance difference is under 1e-4 — a live statement that the
  OpenBLAS compiled into this wheel is computing the right thing on this device. Both
  halves matter: corrupt the vectors and recall drops, scale the returned distances and
  recall stays perfect while the difference blows past the tolerance.
- **The exact-versus-approximate trade, measured on screen.** The same 100 queries go
  through `IndexFlatIP`, `IndexIVFFlat(nlist=256)` and `IndexHNSWFlat(M=32)`; a
  [`Slider`](https://flet.dev/docs/controls/slider/) drives `nprobe` and `efSearch`
  together, and every row is graded against that same numpy answer rather than against
  the row above it — so a wrong exact index shows up as a wrong exact row instead of
  quietly redefining what the approximate ones are measured by. Each row also prints the
  index's serialized size next to the arithmetic that predicts it, so you can size your
  own `N` before building anything. Expect the HNSW row's recall to move a little
  between runs on Android and to sit still on iOS — the graph build is
  OpenMP-nondeterministic, which the recipe's
  [Threading](../../README.md#threading) notes cover.
- **Recomputation on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end)**,
  which fires once on release rather than on every step, with the work in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) —
  slider disabled, spinner up, worker body wrapped in `try/except` because `run_thread`
  discards what it raises, and an explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) at the end.
- **Persistence, reported for what it is.** The IVF index is written to
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  with `faiss.write_index`, read back with `faiss.read_index(path, faiss.IO_FLAG_MMAP)`,
  then searched and compared against the copy still in memory. The line on screen claims
  only what that shows — a lossless round trip — and says outright that it is not proof
  the mapping engaged, because `read_index` accepts either mmap flag on any index and
  returns the same ids either way. Only memory can answer that one.
- **The build describing itself.** The header line prints
  `faiss.get_compile_options()`, `faiss.omp_get_max_threads()` and
  `faiss.get_num_gpus()`, which is the shortest way to see which slice you are running
  on — the SIMD level and the thread count both differ between Android and iOS.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

`pyproject.toml` pins `flet` and `faiss-cpu`, which is the combination that was verified.
`requires-python = ">=3.11"` is load-bearing even though neither pin forces it: the numpy that
`faiss-cpu` pulls in on mobile declares `Requires-Python: >=3.11`, so `flet build` has no
3.10 split to resolve without it. This is the one case where the usual check — copying the
`pyproject.toml` alone into an empty directory and running `uv lock` — gives a false
all-clear, because PyPI's desktop numpy still covers 3.10 and the lock succeeds at `>=3.10`.
