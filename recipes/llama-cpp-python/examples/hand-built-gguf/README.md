# llama-cpp-python hand-built GGUF

One screen that writes a complete GGUF language model **inside the app**, loads it with
`Llama(...)`, generates tokens from it on the device, and checks llama.cpp's logits against
the same forward pass recomputed in numpy. No download, no asset, no `gguf` package — the
only thing shipped is the app's own code, and the model file is rebuilt on every run.

The model is a one-block llama-architecture network: token embeddings, RMS-normed attention
with RoPE and four heads, a SwiGLU feed-forward twice the embedding width, a final norm and
an output projection — float32 throughout, with a 267-entry SentencePiece vocabulary (three
control tokens, all 256 `<0xNN>` byte tokens, eight word pieces). About a hundred lines of
`struct` and numpy emit the GGUF v3 header, metadata block, tensor table and 32-byte-aligned
tensor data.

A slider picks the embedding width — 32, 64, 128, 256 or 512 — and releasing it rebuilds,
reloads and re-runs everything. Widths and the files they produce:

| width | parameters | GGUF file |
| --- | --- | --- |
| 32 | 27,424 | 116,992 B |
| 64 | 75,328 | 308,608 B |
| 128 (default) | 232,576 | 937,600 B |
| 256 | 792,832 | 3,178,624 B |
| 512 | 2,896,384 | 11,592,832 B |

Even the top position is cheap: driven through the app's own handlers on a desktop it takes
24 ms to write the file, 3 ms to load, 1 ms to evaluate the prompt, 5 ms for the numpy
cross-check and 6 ms to generate 24 tokens, with the process's peak RSS climbing from
97.6 MB after the smallest width to 147.3 MB after the largest. Those are desktop numbers
and say nothing about a handset's speed, but the shape of the workload is what makes the
default position safe on a low-RAM emulator.

**The weights are random, so the generated tokens are noise.** The screen says so. What is
being demonstrated is that the whole pipeline — write, load, tokenize, evaluate, sample,
detokenize, quantise — runs on the device and computes the right numbers, not that a
1-block random model has anything to say.

What it demonstrates:

- **A model file produced by the app.** GGUF is a documented container and nothing exotic
  is needed to write one. The footer prints the size predicted from the tensor table beside
  `os.path.getsize`, and the load row prints `llama_model_size()` beside
  `llama_model_n_params()` — which for an all-float32 model has to be exactly four times the
  parameter count. Both pairs matched exactly at every slider position: they are the cheap
  check that the file layout is right, before anything harder is claimed.
- **A cross-check that can fail visibly.** A model that loads and generates still tells you
  nothing about whether it computed what you meant, so the app re-reads the GGUF it just
  wrote and recomputes the last token's logits in float64 numpy — RMS norm, RoPE, causal
  attention, SwiGLU, output projection — sharing no code with llama.cpp. The verdict line
  reports whether the top token agrees and what `max|difference|` is as a fraction of the
  logit range, against a 1e-4 tolerance. On desktop that fraction ran between 1.0e-07 and
  2.6e-07 across the five widths — float32 epsilon, which is the only honest answer for an
  f32 model — with the top token agreeing at every one. The check needs `logits_all=True`:
  without it `llm.scores` is never written and reading it gives uninitialised memory — see
  [Things to know](../../README.md#things-to-know).

  It really does fail. Perturbing one weight tensor by 0.01% before the numpy side sees it
  turns the verdict red (6.1e-05 → 1.0e-04 of the logit range); so does adding 0.05 to a
  single element of `attn_q`. Between the residual and the tolerance there are ~385x at the
  tightest slider position and ~1000x at the loosest, so the margin is for a device whose
  kernels round differently, not for a fault.

  The tolerance can be that tight only because the app asks for an **f32 KV cache**
  (`type_k`/`type_v`), rather than llama.cpp's f16 default. At the default, the KV cache
  alone accounts for the entire disagreement — 4.1e-04 of the logit range at width 256,
  three orders of magnitude above the f32 floor — and a tolerance loose enough to admit
  that would also admit a real arithmetic fault. See
  [Things to know](../../README.md#things-to-know) for what that costs in memory.
- **What this device's llama.cpp was actually built with.** The header prints
  `llama_print_system_info()`, which on an arm64 phone should read `CPU : NEON = 1 |
  ARM_FMA = 1 | REPACK = 1` and conspicuously not `DOTPROD`; on an Apple Silicon Mac the same
  line reports Metal *and* `DOTPROD`, which is exactly why a desktop run proves nothing about
  the device. The `REPACK = 1` is a compile-time flag, not a capability: without `DOTPROD`
  nothing is ever repacked — see [Things to know](../../README.md#things-to-know).
  Beside it: `llama_supports_mmap()`, `llama_supports_gpu_offload()`, `os.cpu_count()` and
  the thread count in use.
- **Which library the loader settled on.** The header prints
  `llama_cpp.llama_cpp._lib._name`, the name ctypes ended up opening. On Android that should
  be the bare soname `libllama.so`, since the bundled libraries are not files on disk there;
  on iOS, a path inside a code-signed framework. It is the quickest way to confirm the loader
  story in [Android notes](../../README.md#android-notes) and
  [iOS notes](../../README.md#ios-notes) on a device you have.
- **What the run cost in memory, in the three terms it is actually made of.** The footer
  prints the weights (`llama_model_size()`), the KV cache (`n_ctx × blocks × width`, K and
  V, at the cache's type) and the float32 logits buffer numpy holds on the Python side —
  1,048,576 B of KV cache against 11,585,536 B of weights at the largest width. The
  absolute numbers are a toy's; the decomposition is not, and it is the one that catches
  people out, because the KV term scales with `n_ctx` rather than with the model and
  llama.cpp allocates all of it up front. Multiply through with the bits-per-weight figures
  below for a real model.
- **Quantisation on device.** `llama_model_quantize` is exported, so the app quantises the
  F32 model it just wrote to Q8_0 and Q4_0 and reports the real file sizes and the bits per
  weight they work out to over the whole file. That figure sits above the pure-type one —
  4.63 against Q4_0's 4.500 at width 512, and further above at smaller widths — because the
  header, the vocabulary and the F32 norms are a bigger share of a small file, and because
  llama.cpp promotes the output tensor to a wider type. It is the same arithmetic that
  decides whether a real 1B or 3B model fits on the handset.
- **A hard bound on generation.** `max_tokens` is not one — see
  [Things to know](../../README.md#things-to-know) — so the app drives the low-level
  generator with `zip(range(NEW_TOKENS), llm.generate(...))`, which returns exactly the
  number asked for.
- **Compute off the UI thread.** The work runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the slider disabled and a spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run. The llama.cpp work releases the GIL, but the Python around it holds
  the lock in bursts long enough to drop frames — see
  [Threading](../../README.md#threading) — so the thread is not optional here. The
  worker body is wrapped in `try/except` because `page.run_thread` discards whatever it
  raises, it clears the panels on the way out so a previous run's numbers cannot sit under
  this run's error, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. The `Llama` object is closed in a `finally`, so nothing accumulates across
  slider moves.

The GGUF and its two quantised copies are written to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which the header prints; at the largest width that is about 16 MB of app-private storage,
overwritten on every run.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

`pyproject.toml` pins `flet` and `llama-cpp-python`, which is the combination that was
verified. `requires-python = ">=3.11"` goes with the pin: the numpy that resolves for mobile
declares that floor, and uv resolves for every version in the declared range rather than
only the interpreter in use. Checked the way a consumer meets it, by copying that
`pyproject.toml` alone into an empty directory and running `uv lock` there.

Nothing else in the file is load-bearing — no `[tool.flet.android] target_arch` narrowing is
needed, because wheels exist for all three Android ABIs and all three iOS slices.

**A simulator run is not a device run for this package.** The iOS arm64 simulator slice is
the one build that has the dot-product kernels the phone does not; see
[iOS notes](../../README.md#ios-notes).
