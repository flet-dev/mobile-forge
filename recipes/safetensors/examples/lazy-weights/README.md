# safetensors lazy weights

One screen that writes a 50 MB weights file into app storage with numpy, then reads it three
ways and prints what each read costs in time and in peak resident memory. A fourth button
damages a copy. The claim being tested is the reason to use
[safetensors](https://huggingface.co/docs/safetensors/index) on a phone at all: a file is
memory-mapped, so reading its header and one row of one tensor costs nothing, while loading
all of it costs twice the file.

Nothing is downloaded and nothing is bundled — the tensors are generated in-app from a fixed
seed, which is also what makes the app a regression test of a recipe bump.

What it demonstrates:

- **The header is free.** `safe_open` plus every tensor's name, shape and dtype takes well
  under a millisecond and moves resident memory by a fraction of a megabyte, on a file that
  declares 50 MB of tensor data. The same line reports the identical header read done with
  nothing but `struct.unpack` and `json.loads`, because a model picker listing candidate
  files needs no more than that.
- **One row out of a 4.2 MB tensor is free too** — `get_slice(name)[0:1]` on the block a
  [`Slider`](https://flet.dev/docs/controls/slider/) picks, driven from
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture is one read.
- **A full [`load_file`](https://huggingface.co/docs/safetensors/api/numpy#safetensors.numpy.load_file)
  is not free**, and the peak memory printed next to it is the argument for reading lazily.
- **Truncation raises, bit rot does not.** The last button writes two damaged copies of a
  small file: one with its tail cut off, which fails at `safe_open` with
  `SafetensorError: … incomplete metadata, file not fully covered`, and one with a single bit
  flipped inside a tensor, which opens perfectly and hands back the wrong number.
- **Nothing is trusted to describe itself.** Before writing, the app keeps a sha256 of every
  block and of its first row; every value read back is checked against those, which is how
  the bit-flipped copy gets caught at all.
- Every read runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the control disabled and a spinner up, wrapped in `try/except` because `run_thread`
  discards whatever a worker raises, and ending in an explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

Three things to read correctly on screen. `ru_maxrss` is a **peak**, so the reading never
falls back — the 50 MB the app allocated to build the file is already in the baseline that
stages 2 and 3 are compared against, and only stage 4 pushes past it. `ru_maxrss` also counts
**bytes on Darwin kernels and kilobytes on Linux ones**, so iOS and Android disagree by a
factor of 1024 about the same number; `peak_mb()` settles that with `os.uname().sysname`
rather than `platform.system()`, which reports different things for different Python builds.
And the file stays in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
between launches, as a weights file should; delete the app's data to reclaim the 50 MB.

The memory readings use `resource`, which is POSIX-only — fine on Android, iOS, macOS and
Linux, not on Windows.

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
