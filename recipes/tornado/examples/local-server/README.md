# tornado local server

A [tornado](https://www.tornadoweb.org/en/stable/) HTTP server starts on `127.0.0.1` when the
app opens, on a background thread, on whatever port the kernel hands out. Three segments pick
a route and **Send** calls it — from inside the same app. Both halves of the exchange land on
screen: the request line and body that went out, the status, timing and JSON that came back,
and underneath them the server's own log of the requests that actually crossed the socket.
`POST /api/notes` writes to app storage, so the list survives a restart.

What it demonstrates:

- **A server that is not on the UI thread.** The thread body is a plain `asyncio.run()`, which
  gives tornado the one loop it needs, on a thread of its own.
  [`flet.run()`](https://flet.dev/docs/cookbook/async-apps) already runs the app inside an
  event loop of its own, and blocking that one blocks the interface.
- **A port you do not choose.**
  [`bind_sockets(0, "127.0.0.1")`](https://www.tornadoweb.org/en/stable/netutil.html#tornado.netutil.bind_sockets)
  binds before the server exists, so `getsockname()` can report the port back. The address at
  the top of the screen is different on every launch.
- **Crossing between two loops.** The fetch is handed to the server's loop with
  `asyncio.run_coroutine_threadsafe`, so
  [`AsyncHTTPClient`](https://www.tornadoweb.org/en/stable/httpclient.html#tornado.httpclient.AsyncHTTPClient)
  runs where tornado lives. Calling it from the
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) worker
  directly would build a second loop that nothing runs, and the request would hang there
  forever — its own `request_timeout` cannot fire, because that timer needs the same loop.
- **A handler writing to app storage.** `POST /api/notes` appends to a JSON file under
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  and `GET` reads it back — the same durable location any Flet app should use.
- **The compiled extension, reported rather than asserted.** `GET /api/status` answers with
  `speedups_extension`, and it reports which masking implementation
  [`tornado.websocket`](https://www.tornadoweb.org/en/stable/websocket.html) actually got —
  not merely whether the `.so` shipped, which the pure-Python fallback would satisfy just as
  well.
- **Compute off the UI thread.** Each call runs in `page.run_thread` with the button disabled
  and a [`ft.ProgressRing`](https://flet.dev/docs/controls/progressring/) up, and the handler
  ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs.

Watch the two timings diverge: on a Mac desktop the round trip settles around 0.6 ms, and the
server's own `request_time` reads about 0.1 ms — a loopback call costs less than drawing its
result, and most of what the app measures is its own client. Then send the app to the
background and come back: the lifecycle handler drops the socket on `PAUSE` and binds a new one
on `RESTART`, and the address at the top has changed. Anything that had cached the old URL
would now be talking to nothing.

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
