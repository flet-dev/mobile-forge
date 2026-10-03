# lz4 log archive

About 4 MB of app log, generated on the first tap. Each button writes it to an `.lz4` file
at one compression level, reads the file back, and reports the size on disk, the ratio, how
long each direction took, and whether every byte came back intact. The footer shows the
liblz4 version the wheel compiled in.

What it demonstrates:

- **The level trade, measured on the device.** `Fast` is LZ4's default codec; `HC 9` and
  `HC 12` are LZ4-HC, and 12 is its ceiling. On a log like this HC files come out about 30%
  smaller for roughly 15 to 150 times the write time, `HC 12` being the slow end, while
  reading back stays fast at every level.
- **Writing and reading in pieces.**
  [`lz4.frame.open`](https://python-lz4.readthedocs.io/en/stable/lz4.frame.html#lz4.frame.open)
  returns a file object that compresses as it is written to, so the log goes to disk a
  megabyte at a time and is checked back the same way. The file lands under
  [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
  and is a standard LZ4 frame: the app shows its path, and once it is pulled off a
  simulator or a rootable emulator, `lz4 -d` reads it.
- **Compute off the UI thread.** Each run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  level buttons locked and a spinner up, ending in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. Locking matters: every level writes the same file, and two overlapping runs
  corrupt each other's read-back. Disabling the buttons is not enough on its own — a second
  tap already in flight arrives before the disabled state does — so the handler also takes
  a non-blocking lock and drops any tap that finds it held.

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
