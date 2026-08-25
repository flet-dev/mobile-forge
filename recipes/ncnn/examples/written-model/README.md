# ncnn written model

One screen that writes a complete ncnn model **inside the app**, loads it back with `ncnn.Net`,
runs it on the device, and checks the answer against the same arithmetic in numpy. There is no
model asset, no pretrained weights and no network access of any kind: `src/assets/` does not
exist, and the two files the app reads are the two it just wrote.

The model is a 3-layer 3x3 convolution stack (ReLU, ReLU, linear) over a 1x128x128 input, with the
weights drawn from a fixed-seed `numpy.random.default_rng`, so the numpy reference and the ncnn
model are provably the same numbers. Two sliders drive it, both recomputing on release: the
channel count sets how much arithmetic one inference is, and the thread count is `opt.num_threads`,
ncnn's one performance knob.

What it demonstrates:

- **A model with no model file.** The `.param` is text — a magic number, the layer and blob counts,
  then one line per layer — and the `.bin` is each layer's weights and bias as raw little-endian
  float32 with a 4-byte flag word in front of every weight blob. Both are written into
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  and their byte counts go on screen, next to what ncnn made of them: `net.layers()`, `net.blobs()`,
  `net.input_names()` and `net.output_names()`. Those last two matter because a `.param` line names
  the *layer* first and its *blobs* after the two counts, and `ex.input()` wants a blob name.
- **That ncnn's defaults are not float32.** Two of the three runs differ only in
  `use_fp16_packed`/`use_fp16_storage`/`use_fp16_arithmetic`, and the table puts their agreement
  with numpy side by side — on an M4, 5.6e-02 with the defaults against 7.5e-06 with fp16 off,
  relative to the largest output. A cross-check written to a float32 expectation looks broken when
  nothing is wrong. The verdict line fails visibly if the fp16-off run drifts past 1e-4, so a build
  where the graph quietly did the wrong thing reads FAIL rather than a plausible number.
- **What `opt.num_threads` is worth on this SoC.** The third run repeats the default configuration
  at one thread, so the last column is a real speedup measured on the handset in your hand. On a
  desktop M4 the curve peaks at the big-core count and falls to 0.47x at one thread per logical
  core — worth confirming before raising it above ncnn's default.
- **What the round cost, in time and memory.** The footer reports the whole round's wall clock, how
  much of it was the numpy cross-check rather than ncnn, and the process's peak RSS. The split is
  the point on device: the [`numpy`](../../../numpy) wheels on this index are built with no BLAS, so
  the reference costs far more there than on a laptop, and without the split its seconds would read
  as ncnn's.
- **The traps, applied rather than described.** Every array reaching ncnn goes through one
  `as_float32` helper, because `ncnn.Mat` accepts a float64 array and then takes the process down
  with SIGBUS. Each return code is checked before its Mat is touched, because a failed `extract`
  hands back an empty Mat that segfaults `np.array`. And the work runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  sliders disabled and the spinner shown *before* the thread starts — `extract` holds the GIL, so a
  state change made inside the worker would not reach the screen until the work was over.

`src/main.py` is the screen and imports neither `ncnn` nor `numpy`; `src/model.py` is the model,
the numpy reference and the timing harness.

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

`pyproject.toml` pins the combination that was verified, and sets `requires-python = ">=3.11"` to
match the numpy that pypi.flet.dev resolves behind ncnn. Copying it alone into an empty directory
and running `uv lock` there resolves cleanly, which is how a consumer meets it.
