# thinc tiny net

Three interleaved spiral arms, 780 points, and a network small enough to train while you
watch. The app reads a `.cfg` file out of its assets, resolves it into a chained Relu/Softmax
model, an [Adam](https://thinc.ai/docs/api-optimizers#adam) optimizer and a loss object, trains
for thirty epochs on the device, then writes the weights out, reads them back and checks the
predictions still match. The first block of the table names the backend that did the
arithmetic; the slider rebuilds the model at a new hidden width.

What it demonstrates:

- **Which backend a phone actually gets.**
  [`get_current_ops()`](https://thinc.ai/docs/api-backends#get_current_ops) answers `NumpyOps`
  here — there is no CUDA and no Metal to select — but `use_blis` is on, so a float32
  [`ops.gemm`](https://thinc.ai/docs/api-backends#gemm) leaves NumPy entirely and runs BLIS's
  kernels. The panel prints what it found rather than asserting it.
- **A config file that is an app asset, not package data.**
  [`Config().from_disk`](https://thinc.ai/docs/api-config#config-from_disk) reads
  `src/assets/model.cfg` through
  [`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
  — the table says which copy it used, since the module falls back to a built-in string when
  that variable is unset — and
  [`registry.resolve`](https://thinc.ai/docs/api-config#registry-resolve) turns its five
  `@`-prefixed sections into live objects. The same file inside a Python package would be
  inside a zip on Android and unreadable.
- **The canonical training loop.**
  [`begin_update`](https://thinc.ai/docs/api-model#begin_update) returns predictions and a
  callback, the callback pushes the loss gradient back through the layers, and
  [`finish_update`](https://thinc.ai/docs/api-model#finish_update) hands the result to the
  optimizer — batched by [`ops.multibatch`](https://thinc.ai/docs/api-backends#multibatch).
- **A trained model is about a kilobyte.**
  [`to_disk`](https://thinc.ai/docs/api-model#to_disk) writes msgpack, and
  [`from_disk`](https://thinc.ai/docs/api-model#from_disk) needs a model already built from the
  same config — which is why the reload resolves the config a second time before loading.
- **A benchmark that does not travel.** The last two rows time `ops.gemm` against NumPy's own
  matmul on identical float32 matrices. On a laptop NumPy wins by more than an order of
  magnitude because it is linked against a tuned BLAS; the mobile NumPy wheel has no BLAS at
  all, so read the device's two numbers rather than the ones from your desktop run.
- **Compute off the UI thread.** Training runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind a
  spinner, wrapped so an exception reaches the status line instead of leaving the button
  disabled, and ending with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end), so one
  drag trains one model.

Pull the slider down to 8 units and accuracy settles just above half; at 128 it usually lands
in the mid-nineties, though ten desktop runs spread from 87% to 99% — the weight init and the
dropout mask are not seeded, so the same width does not give the same answer twice. The
saved-model row moves with the width too, from roughly 0.7 kB to 3.6 kB, and so does the
training time: capacity, file size and milliseconds are all on the same screen.

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
