# soxr resample tone

Ten seconds of a 440 Hz sine at 48 kHz, generated when the app starts. Tap a target rate and
soxr converts it, reporting how many frames went in and came out, how long the conversion
took, and how far ahead of realtime that is. The footer shows which libsoxr engine each
quality setting selects on this device.

What it demonstrates:

- **The conversion every on-device audio pipeline needs.** Recorders hand you 44.1 or
  48 kHz; speech models want 16 kHz.
  [`soxr.resample`](https://python-soxr.readthedocs.io/en/stable/soxr.html#soxr.resample)
  is the whole of that step — an array in, an array out, no file and no model runtime.
- **How fast that actually is on a phone.** The timing is printed as a realtime multiple, so
  the number means something: a value well above 1x is the headroom you have for doing the
  conversion inside a live capture loop rather than as a batch step.
- **Which engine you got.** libsoxr compiles several resampling cores and picks one per
  quality setting; `cr32s` is the SIMD core. The footer reads it back through
  `stream._csoxr.engine()` — a private attribute, used here because it is the only way to
  see the choice, and because seeing it is the point. Note `VHQ` selects a *double-precision*
  core, which has no ARM SIMD implementation, so on a phone it reads `cr64` and is the slow
  option rather than the good one.
- **Compute off the UI thread.** Each conversion runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, ending in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. soxr releases the GIL while resampling, so this is real parallelism, not
  just a responsive handler loop.

The tone is generated rather than bundled, so the example ships no audio asset.

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
