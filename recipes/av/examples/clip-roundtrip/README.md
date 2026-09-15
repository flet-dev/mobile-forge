# av clip roundtrip

A one-screen app that writes a three-second MP4 into app storage with
[PyAV](https://pyav.basswood.io), reopens it to report what the container actually holds, and
seeks to four points to pull the frames back out as JPEGs.

What it demonstrates:

- **Muxing two streams** — synthetic video frames encoded with `mpeg4` and a 440 Hz tone
  encoded with FFmpeg's own `aac`, written into one MP4 in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data).
- **Building frames without numpy or Pillow** — `av.VideoFrame` planes are filled a row at a
  time, padded to each plane's `line_size`, which is what
  [`Plane.update`](https://pyav.basswood.io/docs/stable/api/video.html) expects.
- **Reading the file back** — container format, duration and per-stream codec, resolution and
  sample rate, all read off the reopened container rather than remembered from the write.
- **Getting a decoded frame onto the screen** — [`ft.Image`](https://flet.dev/docs/controls/image/)
  takes encoded bytes, not raw pixels, so each still is re-encoded as a JPEG through the
  `mjpeg` muxer. The timestamps under the strip are the frames PyAV actually landed on:
  `seek` moves to the nearest keyframe, so they are not evenly spaced.
- **Work off the UI thread** — the encode runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), which
  needs an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
  at the end.

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
