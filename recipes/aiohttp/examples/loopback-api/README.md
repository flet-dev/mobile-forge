# aiohttp loopback API

An [aiohttp web application](https://docs.aiohttp.org/en/stable/web_quickstart.html) serving
four endpoints on `127.0.0.1`, and aiohttp's own
[client](https://docs.aiohttp.org/en/stable/client_quickstart.html) calling them — both in
Flet's event loop, in one process, on the phone. A slider sets how many rows each response
carries; let it go and the six checks run again.

Nothing leaves the device: no external host, no DNS lookup, no TLS, no bundled asset and
nothing written to storage. So what the screen reports is the HTTP stack itself working, not
a network.

The six checks are chosen so that all four of aiohttp's compiled extensions are on the
critical path rather than inferred: `_http_parser` parses in both directions at once — the
server reads every request, the client reads every response — `_http_writer` serialises every
header block, and `_websocket/mask` plus `_websocket/reader_c` handle the frames in the last
one.

What it demonstrates:

- **A server inside Flet's loop, via the runner API.**
  [`web.AppRunner`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.AppRunner)
  and [`web.TCPSite`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.TCPSite)
  bound to port `0`, set up in an `async def main` that then **returns** — Flet awaits `main`
  to completion before its first post-`main` update, so parking the coroutine to keep the
  server alive would strand the render. The bound address is printed in the header, read back
  off `site.name`. [`web.run_app`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.run_app)
  is not usable here at all: it drives the loop itself.
- **Whether the C accelerators are actually live**, also in the header, as
  `C speedups 4/4 (parser, writer, ws-mask, ws-reader)`. aiohttp exposes no public flag for
  this. For the parser, the writer and the mask the app compares against the private name the
  pure-Python twin would be bound to. For `ws-reader` that does not work — the wheel ships a
  pure-Python `_websocket/reader_c.py` beside the compiled `reader_c` extension, so a fallback
  binds the same class out of the same module name and `WebSocketReader.__module__` says
  `aiohttp._websocket.reader_c` either way — so the app asks the import system what loaded that
  module instead, and accepts only an `ExtensionFileLoader`. A slice that fell back to pure
  Python would pass all six checks with byte-for-byte identical results, and (see the WebSocket
  bullet) would not reliably be slower on any figure this app prints, so this line is the only
  thing that reports it.
- **Transparent gzip, with the size gap to prove it happened.** The server forces
  [`enable_compression(force=web.ContentCoding.gzip)`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.StreamResponse.enable_compression);
  the client inflates the body before `read()` returns and the check confirms the rows came
  back identical to the uncompressed request's. At 2,000 rows that is 8,781 B on the wire
  against 46,384 B decoded. The check also prints the `Accept-Encoding` the client actually
  sent, which is `gzip, deflate, zstd` on Python 3.14 and `gzip, deflate` on 3.12 and 3.13.
- **A POST whose answer the app verifies.** The rows from the first check go back as JSON, the
  server totals their `v` field, and the app compares that against a sum it computes itself —
  `server 2,998,000 = client 2,998,000` at 2,000 rows. The rows are generated from `i`, so the
  figure is the same on every install and two devices can be compared directly.
- **A chunked response read without a Content-Length**, one JSON object per line, through
  [`response.content.iter_chunked(8192)`](https://docs.aiohttp.org/en/stable/streams.html#aiohttp.StreamReader.iter_chunked).
  The check counts both the chunks that arrived and the lines in them, and requires the line
  count to equal the row count — 2,000 lines in 44,384 B. How many chunks that arrives as is
  the transport's business and moves from run to run.
- **A 404 that is a status, not an exception**, from a path with no route.
- **A [WebSocket](https://docs.aiohttp.org/en/stable/client_quickstart.html#websockets) echo**
  — one text frame back reversed, then a 12,288 B binary frame back unchanged. The binary frame
  is deliberately large so `ws-mask` and `ws-reader` run over a real payload — a client masks
  every frame it sends — but do not read the timing as a fallback detector: aiohttp's
  pure-Python masker is four `bytes.translate` calls, about 0.01 ms on 12 KiB, and forcing it
  left this check's median unchanged at 0.9–1.0 ms. The header line is the detector.
- **Recomputation from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end)**, so one
  gesture means one run, with `on_change` only rewriting the caption. The run goes through
  [`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task) — not
  `run_thread`, which has no event loop for aiohttp to use and discards whatever its worker
  raises — and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a task needs,
  because Flet's auto-update only fires around event handlers and around `main`. The handler
  disables the slider itself and reads that back as its own re-entrancy guard, rather than
  leaving the disable to the task: `run_task` only *schedules*, so a `disabled` set inside the
  coroutine has not happened yet when the handler returns and Flet pushes the slider's state.
  Two releases landing in that window queue two runs, and two runs sharing one result column
  interleave into twelve rows under a footer that counts six.

Each check is timed on its own and its own failure is contained, so one broken endpoint shows
as one red row instead of hiding the other five. The footer adds the six figures exactly as
displayed, so the total it reports is the sum of the six millisecond figures on the screen
above it rather than a separately measured number.

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

The line to read first on device is the second one in the header. A port in
`serving http://127.0.0.1:…` means the OS actually accepted the listening socket, which is the
one thing here that no amount of desktop testing can establish. Nothing has to be configured for
it on Android — `flet build` grants `android.permission.INTERNET` by default. See the
[recipe README](../../README.md) for the rest.
