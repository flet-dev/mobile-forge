# ncnn written model

One screen that writes a complete ncnn model **inside the app**, loads it back with `ncnn.Net`,
runs it on the device, and checks the answer against the same arithmetic in numpy. There is no
model asset, no pretrained weights and no network access of any kind: `src/assets/` does not exist,
and the two files the app reads are the two it just wrote — a `.param` of about 230 bytes and a
`.bin` of 5 KB to 300 KB depending on the slider.

The model is a 3-layer 3x3 convolution stack (ReLU, ReLU, linear) over a 1x128x128 input, with the
weights drawn from a fixed-seed `numpy.random.default_rng`, so the numpy reference and the ncnn
model are provably the same numbers. Writing it is thirty lines: the `.param` is text — a magic
number, the layer and blob counts, then one line per layer — and the `.bin` is each layer's weights
and bias as raw little-endian float32 with a single 4-byte flag word in front of every weight blob.

Two sliders drive it, both recomputing on release: the channel count (8 to 64, default 32) sets how
much arithmetic one inference is, and the thread count (1 to `ncnn.get_cpu_count()`, or 2 on a
single-core emulator, defaulting to `ncnn.get_physical_big_cpu_count()`, which is ncnn's own
default) is ncnn's one performance knob. It shares out the same amount of work on both
platforms; how many OS threads that costs is *not* the same, and
[Threading](../../README.md#threading) has the split.

What it demonstrates:

- **A model with no model file.** `.param` and `.bin` are written into
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  and their byte counts go on screen, next to what ncnn made of them: `net.layers()`,
  `net.blobs()`, `net.input_names()` and `net.output_names()`. Those last two are the authoritative
  answer to the trap in [Things to know](../../README.md#things-to-know) — in a `.param` line the
  first name is the *layer* and the names after the counts are *blobs*, and `ex.input()` wants a
  blob name.
- **That ncnn's defaults are not float32.** Two of the three runs differ only in
  `use_fp16_packed`/`use_fp16_storage`/`use_fp16_arithmetic`, and the table puts their agreement
  with numpy side by side. On an M4 that is 5.6e-02 with the defaults against 7.5e-06 with fp16
  off, relative to the largest output. A cross-check written against a float32 expectation will
  look broken when nothing is wrong, which is the whole point of showing both — and the verdict
  line fails visibly if the fp16-off run drifts past 1e-4, so a build where the graph quietly did
  the wrong thing shows FAIL rather than a plausible-looking number.
- **What `opt.num_threads` is worth on this SoC.** The third run repeats the default configuration
  at one thread, so the table's last column is a real speedup measured on the handset in your hand.
  The desktop result it is there to test — a peak at the big-core count and 0.47x at one thread per
  logical core — is in [Threading](../../README.md#threading).
- **What the round cost, in time and in memory.** The footer reports the whole round's wall
  clock, how much of that was the numpy cross-check rather than ncnn, and the process's peak RSS.
  The split is the point on device: the [`numpy`](../../../numpy) wheels on this index are built
  with no BLAS, so the reference costs far more there than on a laptop, and without the split its
  seconds would read as ncnn's.
- **That there is no GPU here.** The header prints `ncnn.Option().use_vulkan_compute` and whether
  `ncnn.get_gpu_count` exists at all. On a phone that reads `False` and `False`; on the desktop
  wheel of the same version the second one is `True`. The flag survives as a settable bool with
  nothing behind it.
- **Which version you are actually running.** The header prints
  `importlib.metadata.version("ncnn")` and `ncnn.__version__` together, because on mobile they
  disagree — the extension reports the day it was compiled.
- **The float32 rule, applied.** Every array that reaches ncnn goes through one `as_float32`
  helper. A float64 array is accepted by `ncnn.Mat` and then takes the process down with SIGBUS,
  and numpy's default float dtype is float64.
- **Return codes checked before the Mat is touched.** `load_param`, `load_model` and `extract`
  report failure with a negative int and a line on stderr, never an exception, and the empty Mat a
  failed `extract` hands back segfaults `np.array`. Each code is checked first, and a failure
  becomes a red line on screen instead of a dead app.
- **Compute off the UI thread, with the spinner set first.** The work runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) started from
  each slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end), with both
  sliders disabled and the spinner shown *before* the thread starts — `extract` holds the GIL, so
  a state change made inside the worker would not reach the screen until the work was over. The
  body is wrapped in `try/except` because `page.run_thread` discards whatever it raises, and it
  ends with the explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
  a background thread needs.

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

`pyproject.toml` pins `flet` and `ncnn`, which is the combination that was verified, and sets
`requires-python = ">=3.11"` to match the numpy that pypi.flet.dev resolves behind ncnn — the ncnn
wheel's own `Requires-Python` is `>=3.5` and asks for nothing. Copying that `pyproject.toml` alone
into an empty directory and running `uv lock` there resolves cleanly, which is how a consumer meets
it. No `[tool.flet.android] target_arch` entry is needed: ncnn publishes all three Android ABIs.
