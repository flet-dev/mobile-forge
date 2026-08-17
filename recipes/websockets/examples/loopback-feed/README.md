# websockets loopback feed

A [websockets server](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html)
streaming to
[websockets' own client](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html)
on `127.0.0.1` — both in Flet's event loop, in one process, on the phone. A slider sets how
many messages the run carries; let it go and the whole conversation happens again.

Nothing leaves the device: no external host, no DNS lookup, no TLS, no bundled asset and
nothing written to storage. So what the screen reports is the WebSocket stack itself
working, not a network.

The file is also the correction to any tutorial you might copy from. It imports
`websockets.asyncio.server.serve` and `websockets.asyncio.client.connect` by their full
paths, which is the current API — `from websockets.client import connect` still works in
16.0 but hands back the deprecated legacy implementation, with a `DeprecationWarning`
nothing on a device will show you. And its handler takes **one** argument, because that is
what the asyncio server passes.

What it demonstrates:

- **A server inside Flet's loop that outlives `main`.** `await serve(handler, "127.0.0.1", 0)`
  returns as soon as the socket is bound, `main` reads the port back off
  `server.sockets[0].getsockname()` and then **returns** — Flet awaits `main` to completion
  before its first post-`main` update, so parking to keep the server alive would strand the
  render. The bound address is printed in the header. Do not reach for
  `async with serve(...)` here: its `__aexit__` closes the server the instant the block ends.
  The bind gets a `try` of its own because it is the one step a desktop cannot settle, and
  an `OSError` out of `main` would reach Flet as a crash screen with nothing on it to read.
  Refused, the header says `not serving`, a red `listening socket` row names the errno, and
  the slider stays disabled.
- **Whether the C accelerator is actually live**, in the header, as `masking C extension`
  with the measured ratio after it — a two-digit number, jittery, 34x to 141x across
  desktop runs of one binary — or `masking pure Python (1x)`, which is steady because both
  legs are then the same function. Read it as *large versus 1*, not as a benchmark; the
  [recipe README](../../README.md#things-to-know) carries controlled figures. websockets
  exposes no public flag for this, and
  the obvious check is a trap: upstream's `speedups.c` declares its module name as
  `"websocket.speedups"`, singular, so comparing `apply_mask.__module__` against
  `"websockets.speedups"` is False whether or not the extension loaded. The app instead
  imports `websockets.speedups` (honest here — there is no same-named `.py` to satisfy the
  import), checks the loader is an `ExtensionFileLoader` (iOS's `AppleFrameworkLoader`
  subclasses it), and checks `frames.apply_mask is not utils.apply_mask`. Then it
  cross-checks that boolean with a stopwatch, timing both implementations over the same
  64 KiB buffer, so the verdict and the measurement have to agree. It has to work that way:
  masking is one-directional in RFC 6455, so the 36,675 B this run streams — all of it
  server-to-client — never touches `apply_mask` at all. Instrumented, a 200-message run
  gives the accelerator 6 calls totalling 48 B, the client's ping, count request and close.
  The six checks below therefore pass identically with the extension and without it; the
  header line is the only thing on screen that answers the question.
- **A live streamed feed**, one JSON message per row, appended to a
  [`ListView`](https://flet.dev/docs/controls/listview/) as it arrives. The repaint is
  batched every twentieth message: one `page.update()` per message would be hundreds of
  round trips to the client for a single run.
- **Totals cross-checked from both ends.** The server counts the messages and payload bytes
  it sent and reports them in a summary frame; the client counts what it actually read, and
  both pairs print side by side. The **byte** totals are the leg that carries the check —
  the client's message count can only ever be the number it was told to read — so a server
  that miscounts by one byte shows as `3,906 B` against `3,907 B`. A frame going missing
  outright is a different failure and does not reach this row at all: the fixed-length read
  slides onto the following frame and the run ends on the red row instead. At 200 messages
  both sides read `200 msg / 3,907 B`, and the footer adds the streamed bytes to the payload
  bytes exactly as displayed — `3,907 + 32,768 = 36,675`. The messages are generated from
  their index, so those figures are the same on every install and two devices can be
  compared directly.
- **A second, independent integrity check.** The summary frame announces a sha256 of the
  32,768 B payload the server is about to send; the client recomputes it over what arrived
  and shows match or mismatch. That catches corruption the counts would agree through.
- **Binary versus text, without decoding anything by hand.** The app prints
  `type(...).__name__` for the summary frame and the payload frame — `str`, then `bytes`.
  That is how websockets surfaces the opcode: a text frame arrives as `str`, a binary one
  as `bytes`.
- **The negotiated extension.** `permessage-deflate (12-bit windows)`, read off
  `websocket.protocol.extensions` — compression is on by default in 16.0, with 12-bit
  windows rather than the RFC maximum. Pass `compression=None` to `connect`/`serve` to
  turn it off and watch this row go to *none negotiated*.
- **Round-trip latency, measured twice.** `rtt = await (await websocket.ping())` gives the
  round trip in seconds, and
  [`websocket.latency`](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html#websockets.asyncio.client.ClientConnection.latency)
  is set from the same measurement, so the row passes only when the two compare equal
  exactly. The ping goes first, on an idle connection, because the server closes as soon as
  the payload is out.
- **A graceful close with a code.** The server ends with `close(1001, "feed complete")`; the
  client's next `recv` raises
  [`ConnectionClosedOK`](https://websockets.readthedocs.io/en/stable/reference/exceptions.html#websockets.exceptions.ConnectionClosedOK),
  which is how a clean shutdown reaches the client, and the app shows the `close_code` and
  `close_reason` it can only read afterwards.
- **Recomputation from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end)**, so
  one gesture means one run, with `on_change` only rewriting the caption. The run goes
  through [`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task) —
  not `run_thread`, which has no event loop for a coroutine and discards whatever its worker
  raises — and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a task needs.
  The handler disables the slider itself and reads that back as its own re-entrancy guard,
  rather than leaving the disable to the task: `run_task` only *schedules*, so a `disabled`
  set inside the coroutine has not happened yet when the handler returns and Flet pushes the
  slider's state. Two clients sharing one feed interleave their messages and the totals stop
  adding up.

A run that fails anywhere lands as one red row carrying the exception type and message,
instead of a Flet crash screen.

**On a default `websockets` dependency the header honestly reads `masking pure Python
(1x)`** — a bare requirement resolves to upstream's `py3-none-any` wheel, which carries no
compiled module on any slice. Verified: the app runs unchanged against upstream's 17.0.1
universal wheel, all six checks pass, and the timings are indistinguishable. That is why
this `pyproject.toml` pins `websockets==16.0` alongside `flet==0.86.5`, and why
`requires-python` stays at `>=3.10` — 16.0's own floor. See the
[recipe README](../../README.md#install) for the resolution measurements behind that.

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

The line to read first on device is the second one in the header. A port in
`serving ws://127.0.0.1:…` means the OS actually accepted the listening socket, which is the
one thing here that no amount of desktop testing can establish; `not serving` plus a red
`listening socket` row means it refused, and the row carries the errno. Nothing has to be
configured for it on Android — `flet build` grants `android.permission.INTERNET` by default.
See the [recipe README](../../README.md) for the rest.
