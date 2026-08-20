# jiter partial JSON

A chat-completion response is replayed onto the screen five bytes at a time, the way it
would arrive from a socket. Two parsers watch the same buffer: `jiter` in the partial mode
you pick, and the standard library. The field list fills in as the bytes land; the
`json.loads` line just above it stays red until the very last byte. When the stream ends,
the app times three parsers on 221 KB of repetitive JSON on the device itself.

What it demonstrates:

- **Decoding a document that has not finished arriving** —
  [`from_json(..., partial_mode=...)`](https://github.com/pydantic/jiter/tree/main/crates/jiter-python#handling-partial-json)
  is the whole point of the package. The
  [`SegmentedButton`](https://flet.dev/docs/controls/segmentedbutton/#flet.SegmentedButton.selected)
  switches between `off`, `on` and `trailing-strings`, so you can watch a half-arrived
  string be rejected, dropped, or kept, on the same bytes.
- **The trap hiding in a truncated number** — a cut-off string is dropped or flagged by the
  mode you chose, but a cut-off number is simply parsed as far as it is valid. This
  document's `created` field, 1766217600, goes past as 17, then 1766217, then its real
  value, and nothing in the result marks the first two as provisional.
- **What the string cache is really for** — the default `cache_mode='all'` returns one
  shared Python string for every repeat of the same text. The table counts distinct
  objects behind 3000 identical `status` values: one, against 3000 with the cache off.
  Memory, not microseconds, is the mobile argument.
- **An honest speed comparison** — `json`, [`ujson`](../../../ujson) and `jiter` parse the
  same payload, timed on the device instead of quoted from a benchmark. On desktop the three
  finish within a whisker of each other on this payload; the device ordering is the number
  worth having, and this is how you get it.
- **Compute off the UI thread** — the replay runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, and each frame ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a background
  thread needs. The loop re-parses the entire buffer on every chunk, which is honest at 324
  bytes and quite wrong at a megabyte — the work per chunk grows with the buffer.

Set the mode to `off` and both panels start saying the same thing: a parse error, repeated
64 times, until the closing brace arrives. That is the case for the package on one screen.
Against the standard library jiter is a little quicker; against the standard library at
byte 200 of 324, it is the only one of the two that has an answer at all.

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
