# tflite-runtime threads and delegates

One screen that runs a real `.tflite` model on the device, proves the answer against numpy,
shows which delegate the interpreter actually attached, and times per-invoke milliseconds at
1, 2 and 4 threads — so the thread answer is read off your own handset rather than off this
page.

The model is embedded in `src/main.py` as a single base64 blob: 1,032 bytes, 1,376
characters of source, the same `tests/dense_relu.tflite` this recipe's on-device test uses —
one `FULLY_CONNECTED` taking 4 features to 3, plus a bias, followed by relu. A FlatBuffer
cannot be written out by hand the way the [sibling onnxruntime
example](../../../onnxruntime/examples/hand-built-mlp) writes protobuf, so embedding it is
the honest route. It is decoded with
[`base64.b64decode`](https://docs.python.org/3/library/base64.html#base64.b64decode) and
handed to `Interpreter(model_content=…)`, so there is no `src/assets/` directory, no asset
wiring in `pyproject.toml`, and nothing touches the filesystem.

A slider drives the batch size through
`resize_tensor_input(index, [N, 4])` + `allocate_tensors()`, so the same 1 KB model scales
from trivial to heavy: 4,096, 32,768, **262,144 (the default)** and 1,048,576 rows.
The top position is the only one worth care on a low-RAM handset, so the caption states the
cost of the selected position *before* you release the slider: one input array plus one
retained output per thread count, `rows x (4 + 3 x 3) x 4` bytes, which is 0.2 MB, 1.7 MB,
13.6 MB and 54.5 MB across the four stops. Peak RSS runs higher than that because the live
interpreter and the numpy cross-check each hold another copy — sampled on desktop while the
example's own handlers run, the cold round at the default costs +22 to +30 MB over the
process baseline and the top stop a further +80 to +110 MB, the two stops below the default
nothing measurable. A backgrounded Android app that asks for too much is killed rather than
slowed.

What it demonstrates:

- **A cross-check that duplicates no constants.** After `allocate_tensors()` the app reads
  the model's *own* weight and bias tensors back out with `get_tensor(1)` and
  `get_tensor(2)` — which works even with the XNNPACK delegate attached — and computes
  `np.maximum(x @ W.T + b, 0.0)` in numpy. The verdict line reports `max|tflite - numpy|`
  against a 1e-5 tolerance with the actual figure beside it, so a build where the
  interpreter quietly did the wrong thing shows FAIL rather than a plausible number.
  Measured 4.77e-07 at the smallest batch and 7.15e-07 at the other three on desktop, and
  confirmed to report FAIL when the answer is perturbed. Read it for what it is: because
  both sides start from the *same* weights, it judges the interpreter's arithmetic, not the
  model's integrity — a model whose bytes were altered is reproduced faithfully and still
  passes. A model that will not parse at all fails earlier and differently, with
  `ValueError: The model is not a valid Flatbuffer buffer` on the verdict line.
- **Whether XNNPACK really attached here.** The footer prints the op names from
  `interpreter._get_ops_details()` — a private, experimental method, which is why it is
  labelled as such in the source. A delegated graph reads `['FULLY_CONNECTED', 'DELEGATE']`,
  and that trailing `DELEGATE` is XNNPACK — the only delegate this build has. Reading it from
  Python is the portable answer: the C++ banner that announces the same thing is written
  through `__android_log_vprint`, so on Android it goes to logcat rather than to the app's
  console. See [Android notes](../../README.md#android-notes).
- **What `num_threads` is worth on this SoC.** Three interpreters are built per run, at 1, 2
  and 4 threads, each timed over the same batch as the median of five invokes after a
  discarded warm-up. That table is the only way to see the answer: `num_threads` cannot be
  read back and cannot be changed after construction. It is also the only way to see that
  more is not always better — over repeated runs of this app on a 10-core desktop host, four
  threads landed *below* 1× at batch 4,096 (0.46–0.93×, i.e. slower than one thread, the
  scheduling costing more than the work) and between 1.3× and 2.1× at batch 1,048,576. The
  spread between runs is wide enough that the shape of the curve, not any single figure, is
  the thing to read. Directly comparable to the onnxruntime example's `intra_op` table.
  The `load` column covers `Interpreter(...)` + `resize_tensor_input(...)` +
  `allocate_tensors()` together. On the very first run of a process the 1-thread row carries
  one-time initialisation as well (10–11 ms against 0.1–0.2 ms afterwards), so it reads high
  once and settles on the next slider move.
- **Compute off the UI thread, where it genuinely helps.** The work runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the slider disabled and a spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. `invoke()` releases the GIL for its whole duration — see
  [Threading](../../README.md#threading) — so the UI keeps its frames. The worker body is
  wrapped in `try/except` because `page.run_thread` discards whatever it raises, and it
  clears the panels on the way out so the previous run's numbers cannot sit under this run's
  error. Each run builds its own interpreters and never shares one across threads, which is
  its own trap: see [Things to know](../../README.md#things-to-know).
- **The deprecation warning, silenced.** `warnings.filterwarnings(...)` at the top of the
  module keeps the LiteRT notice out of `console.log`; every `Interpreter()` construction
  emits it otherwise.

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

**`flet run` on your desktop will not compute anything, and that is expected.** Nobody
publishes a `tflite-runtime` wheel a desktop Python this project can use would install —
upstream's last macOS and Windows files were 2.5.0's, for cp35–cp38, and there has never been
an sdist — so the import is guarded and
the screen says so instead of crashing. This is also why `pyproject.toml` declares the
package under `[tool.flet.android]` and `[tool.flet.ios]` rather than in
`project.dependencies` — a top-level entry makes `uv lock` (and therefore `uv run`) fail
outright with *there is no version of tflite-runtime==2.21.0*. See
[Install](../../README.md#install).

`pyproject.toml` pins `flet`, `numpy` and `tflite-runtime`, which is the combination that
was verified, and sets `requires-python = ">=3.12"` because only cp312, cp313 and cp314
wheels are published — that value is what `flet build` uses to pick the bundled Python, so
it is load-bearing rather than decoration. Checked the way a consumer meets it, by copying
that `pyproject.toml` alone into an empty directory and running `uv lock` there. No
`[tool.flet.android] target_arch` entry is needed: all three Android ABIs resolve, which is
the opposite of the sibling onnxruntime example.
