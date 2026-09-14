# soundfile codec round-trip

A two-second chord, generated in numpy when the app starts, then encoded into every container
this build of libsndfile supports and decoded straight back. Each row reports the encoded
size, how that compares with the raw float64 samples, how long the round trip took, and how
far the decoded audio drifted from the original.

What it demonstrates:

- **Which formats you actually get on a phone.** The rows are not a table copied from
  documentation — each one is a real `sf.write()` followed by a real `sf.read()` on the
  device. FLAC, Ogg Vorbis, Opus and MP3 appear because `flet-libsndfile` links libFLAC,
  libvorbis, libopus, libmpg123 and LAME; if a codec were missing from a build, its row
  would show the error libsndfile raised instead of a size.
- **The size decision, with numbers.** Two seconds of audio is 128 kB as raw float64 and
  around 3 kB as MP3. The compression column is the argument for not storing WAV on a device
  with a user's storage quota — and the error column is what that costs.
- **Lossless is not lossy-free.** FLAC and ALAC come back with a small error rather than
  zero, because both are 16-bit integer formats and the source is float64. It is
  quantisation, not codec loss — a distinction worth seeing once.
- **Encoding in memory, with no file at all.** Every round trip goes through
  `io.BytesIO`, which exercises libsndfile's virtual I/O. That is the path an app takes for
  audio it downloaded or bundled as an asset, where there may be no real file to open.
- **Compute off the UI thread.** The sweep runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, ending in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. libsndfile releases the GIL while coding, so this is real parallelism.

The two waveform strips are peak envelopes: the generated source, and the audio recovered
from the MP3 — near enough to look identical at this scale, which is the point of a lossy
codec.

The audio is generated rather than bundled, so the example ships no asset.

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
