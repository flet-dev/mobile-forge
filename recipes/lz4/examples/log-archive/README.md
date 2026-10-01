# lz4 log archive

About 4 MB of app log, generated on the first tap. Each button streams it into an `.lz4`
file at one compression level, reads the file back, and reports the size on disk, the
ratio, how long each direction took, and whether the bytes came back intact. The footer
shows the liblz4 version the wheel compiled in.

What it demonstrates:

- **The level trade, measured on the device.** `Fast` is LZ4's default codec; `HC 9` and
  `HC 16` are LZ4-HC. On a log like this HC buys roughly a third more compression for
  20–70 times the write time, while the read time barely moves — which is why HC suits
  data written once and read often, and the default suits data written constantly.
- **Streaming to a file.**
  [`lz4.frame.open`](https://python-lz4.readthedocs.io/en/stable/lz4.frame.html#lz4.frame.open)
  compresses as it writes, the way you would archive a log too large to want in memory
  twice. The file lands under
  [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
  and is a standard LZ4 frame: copy it off the device and `lz4 -d` reads it.
- **Compute off the UI thread.** Each run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, ending in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. lz4 releases the GIL while it compresses, so the UI stays responsive even at
  `HC 16`.

The log is generated rather than bundled, so the example ships no asset.

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
