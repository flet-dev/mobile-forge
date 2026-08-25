# tflite-runtime threads and delegates

One screen that runs a real `.tflite` model on the device, proves the answer against numpy,
shows which delegate the interpreter actually attached, and times per-invoke milliseconds at
1, 2 and 4 threads — so the thread answer is read off your own handset rather than off a page.

The model is embedded in `src/model.py` as a single base64 blob: 1,032 bytes, the same
`tests/dense_relu.tflite` this recipe's on-device test uses — one `FULLY_CONNECTED` taking 4
features to 3, plus a bias, followed by relu. A FlatBuffer's offsets and alignment make it
impractical to write out by hand, so embedding a converted one is the honest route. It is
decoded with
[`base64.b64decode`](https://docs.python.org/3/library/base64.html#base64.b64decode) and handed
to `Interpreter(model_content=…)`, so there is no `src/assets/` directory, no asset wiring in
`pyproject.toml`, and nothing touches the filesystem.

A slider drives the batch size through `resize_tensor_input(index, [N, 4])` +
`allocate_tensors()`, so the same 1 KB model scales from trivial to heavy: 4,096, 32,768,
**262,144 (the default)** and 1,048,576 rows. The top position is the only one worth care on a
low-RAM handset, so the caption states the cost of the selected position *before* you release
the slider: one input array plus one retained output per thread count, which is 0.2 MB, 1.7 MB,
13.6 MB and 54.5 MB across the four stops. Peak RSS runs higher than that, because the live
interpreter and the numpy cross-check each hold another copy — sampled on desktop while the
app's own handlers ran, the cold round at the default cost +22 to +30 MB over the process
baseline and the top stop a further +80 to +110 MB, the two stops below the default nothing
measurable. A backgrounded Android app that asks for too much is killed rather than slowed.

What it demonstrates:

- **A cross-check that duplicates no constants.** After `allocate_tensors()` the app reads the
  model's *own* weight and bias tensors back out with `get_tensor(1)` and `get_tensor(2)` —
  which works even with the XNNPACK delegate attached — and computes
  `np.maximum(x @ W.T + b, 0.0)` in numpy. The verdict line reports `max|tflite - numpy|`
  against a 1e-5 tolerance with the actual figure beside it, so a build where the interpreter
  quietly did the wrong thing shows FAIL rather than a plausible number. Measured 4.77e-07 at
  the smallest batch and 7.15e-07 at the other three on desktop, and confirmed to report FAIL
  when the answer is perturbed. Read it for what it is: because both sides start from the
  *same* weights, it judges the interpreter's arithmetic, not the model's integrity — a model
  whose bytes were altered is reproduced faithfully and still passes. A model that will not
  parse at all fails earlier and differently, with `ValueError: The model is not a valid
  Flatbuffer buffer` on the verdict line.
- **Whether XNNPACK really attached here.** The footer prints the op names from
  `interpreter._get_ops_details()` — a private, experimental method, which is why it is
  labelled as such in the source. A delegated graph reads `['FULLY_CONNECTED', 'DELEGATE']`,
  and that trailing `DELEGATE` is XNNPACK, the only delegate this build has. Reading it from
  Python is the portable answer: the C++ banner that announces the same thing goes to logcat on
  Android rather than to the app's console, and somewhere else again on iOS. See
  [Android](../../README.md#android).
- **What `num_threads` is worth on this SoC.** Three interpreters are built per run, at 1, 2
  and 4 threads, each timed over the same batch as the median of five invokes after a discarded
  warm-up. That table is the only way to see the answer, because `num_threads` cannot be read
  back and cannot be changed after construction — and the only way to see that more is not
  always better, which on a big.LITTLE phone can turn over at a different batch size than
  anywhere else. Run it twice before believing any single figure; the spread between runs is
  wide enough that the shape of the curve is the thing to read. The `load` column covers
  `Interpreter(...)` + `resize_tensor_input(...)` + `allocate_tensors()` together, and on the
  very first run of a process the 1-thread row carries one-time initialisation as well (10–11
  ms against 0.1–0.2 ms afterwards), so it reads high once and settles on the next slider move.
- **Compute off the UI thread, where it genuinely helps.** The work runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  slider disabled and a spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. `invoke()` releases the GIL for its whole duration — see
  [Threading](../../README.md#threading) — so the UI keeps its frames. The worker body is
  wrapped in `try/except` because `page.run_thread` discards whatever it raises, and it clears
  the panels on the way out so the previous run's numbers cannot sit under this run's error.
  Each run builds its own interpreters and never shares one across threads, which is its own
  trap: see [Things to know](../../README.md#things-to-know).
- **The deprecation warning, silenced.** `warnings.filterwarnings(...)` at the top of
  `src/model.py` keeps the LiteRT notice out of `console.log`; every `Interpreter()`
  construction emits it otherwise.

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

**`flet run` on your desktop will not compute anything, and that is expected.** No
`tflite-runtime` wheel exists that a desktop Python could install — upstream's last macOS and
Windows files were 2.5.0's, for cp35–cp38, and there has never been an sdist — so the import is
guarded in `src/model.py` and the screen says so instead of crashing. This is also why
`pyproject.toml` declares the package under `[tool.flet.android]` and `[tool.flet.ios]` rather
than in `project.dependencies`: a top-level entry makes `uv lock` (and therefore `uv run`) fail
outright with *there is no version of tflite-runtime …*. See
[Install](../../README.md#install).

`pyproject.toml` pins `flet`, `numpy` and `tflite-runtime`, which is the combination that was
verified, and sets `requires-python = ">=3.12"` because only cp312, cp313 and cp314 wheels are
published — that value is what `flet build` uses to pick the bundled Python, so it is
load-bearing rather than decoration. Checked the way a consumer meets it, by copying that
`pyproject.toml` alone into an empty directory and running `uv lock` there. All three Android
ABIs resolve, so no `[tool.flet.android] target_arch` entry is needed.
