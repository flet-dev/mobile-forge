# tornado

[`tornado`](https://www.tornadoweb.org/en/stable/) is an asynchronous web framework and
networking library built on `asyncio`. On a phone the half worth having is the server: it runs
a real HTTP server *inside* your app, bound to the loopback interface, so a
[`WebView`](https://flet.dev/docs/controls/webview/), a native plugin or your own code can call
a local API with no network and no backend. The
[client](https://www.tornadoweb.org/en/stable/httpclient.html#tornado.httpclient.AsyncHTTPClient),
[websockets](https://www.tornadoweb.org/en/stable/websocket.html) and a
[WSGI container](https://www.tornadoweb.org/en/stable/wsgi.html#tornado.wsgi.WSGIContainer) that
runs an existing Flask or Django app come with it.

## Install

Add tornado to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "tornado",
]
```

Nothing else is pulled in: tornado declares no dependencies of its own.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`local-server`](examples/local-server) — serves a JSON API on `127.0.0.1` from a
  background thread and calls it from the app.

## Usage in a Flet app

Give the server a thread, an asyncio loop of its own, and an ephemeral loopback port:

```python
def serve(publish):
    async def run():
        sockets = tornado.netutil.bind_sockets(0, "127.0.0.1")
        tornado.httpserver.HTTPServer(application).add_sockets(sockets)
        publish(sockets[0].getsockname()[1])  # the port the kernel chose
        await asyncio.Event().wait()

    asyncio.run(run())


threading.Thread(target=serve, args=(show_port,), daemon=True).start()
```

[`bind_sockets`](https://www.tornadoweb.org/en/stable/netutil.html#tornado.netutil.bind_sockets)
plus [`add_sockets`](https://www.tornadoweb.org/en/stable/tcpserver.html#tornado.tcpserver.TCPServer.add_sockets)
rather than [`Application.listen`](https://www.tornadoweb.org/en/stable/web.html#tornado.web.Application.listen),
because the socket then exists before the server does — the only way to read back a port you
did not choose.

### Storage

Handlers are ordinary Python, so what they read and write belongs in Flet's app-storage
directories:
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for what the user keeps,
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for what can be rebuilt, and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch.

Do not point
[`StaticFileHandler`](https://www.tornadoweb.org/en/stable/web.html#tornado.web.StaticFileHandler)
at a directory inside an installed package. On Android, site-packages is a zip file at
runtime, so a path into it is not a directory and the handler fails. Give it the
[assets directory](https://flet.dev/docs/cookbook/assets) — which the app receives as
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir) —
or app storage instead:

```python
(r"/static/(.*)", tornado.web.StaticFileHandler,
 {"path": os.getenv("FLET_ASSETS_DIR", "assets")})
```

### Threading

**Tornado is one event loop on one thread, and it must not be Flet's.** `flet.run()` runs the
app inside `asyncio.run()`, and a synchronous `def main(page)` is called from within that
coroutine, so blocking there blocks Flet's own loop. Start the server on a thread of its own
and call `asyncio.run()` in it, which creates the loop that
[`IOLoop`](https://www.tornadoweb.org/en/stable/ioloop.html) wraps for that thread alone.

From a [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
worker, do not start tornado work on `IOLoop.current()`. That thread has no loop, so
`IOLoop.current()` silently *creates* one and hands it back — and nothing ever runs it.
`fetch()` then returns a future that stays pending forever, and not even its own
`request_timeout` fires, because that timer is scheduled on the same dead loop. Cross into the
server's loop instead — `asyncio.run_coroutine_threadsafe(coro, loop)` when you want the
result, or
[`IOLoop.add_callback`](https://www.tornadoweb.org/en/stable/ioloop.html#tornado.ioloop.IOLoop.add_callback),
which is documented as safe to call from any thread. Going the other way, work done on the
server thread reaches the UI only through an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

In an [async app](https://flet.dev/docs/cookbook/async-apps) a loop is already running, so
`application.listen(port, "127.0.0.1")` attaches the server to it with no extra thread — fewer
moving parts, at the price that handlers then share the loop dispatching your UI events, where
one blocking call freezes the interface.

### Binding and ports

Bind `127.0.0.1`, and pass port `0`. A fixed port is what reliably fails on a phone: below
1024 needs root, and above it another app may already hold the one you picked. Port 0 asks the
kernel for a free port, and `getsockname()` reads back which one it was. Use the literal
address rather than `"localhost"`, which also resolves to `::1` and binds a second socket.
Loopback keeps working in airplane mode, because nothing leaves the device.

On Android, opening a socket at all needs the `INTERNET` permission — the platform gates the
socket call itself, not just outbound traffic, so loopback is covered by it too. `flet build`
seeds that permission for every app, so there is nothing to add to
[`[tool.flet.android.permission]`](https://flet.dev/docs/publish/android/#permissions) — only
something not to remove.

Binding `0.0.0.0` is a different proposition: it publishes the API on whatever network the
device has joined, and on iOS 14 and later reaching other devices on the local network
requires an `NSLocalNetworkUsageDescription` and prompts the user. Stay on loopback unless
being on the network is the point.

### Backgrounding

The server runs only while the process does. A suspended app executes no code, so an in-flight
request goes unanswered, and the OS may reclaim the socket or terminate the app while it is
away. Treat the listener as a foreground-only resource, and give
[`page.on_app_lifecycle_state_change`](https://flet.dev/docs/controls/page/#flet.Page.on_app_lifecycle_state_change)
the job: stop on `AppLifecycleState.PAUSE`, bind again on `RESTART`. Those two are delivered on
Android and iOS only, so wiring them leaves a desktop run untouched.

Never persist the port. It changes across that cycle, so anything holding the URL — a WebView,
a saved setting, another module — has to be handed the new one.

### App size

The wheel is approximately 0.45 MB compressed and 1.7 MB unpacked per architecture. What lands
in the app is larger than the unpacked wheel, not smaller:
[package compilation](https://flet.dev/docs/publish/#compilation-and-cleanup) is on by default
and tornado's bytecode is bigger than its source, so the installed package measures around
2.5 MB.

Nearly half of that is `tornado/test`, tornado's own test suite, which upstream ships inside
the package and Flet's default cleanup does not remove. Dropping it saves roughly 1.2 MB per
architecture — easily the largest lever this package has:

```toml
[tool.flet.cleanup]
package_files = ["tornado/test"]
```

Keep the path relative to site-packages, as above: `"**/tornado/test"` looks equivalent but
matches nothing, because `**` spans separators and so still demands a directory above
`tornado/`.

The compiled part is a few kilobytes on Android and under 70 KB on iOS; the rest is Python
source, so the usual Android levers — an app bundle, split APKs, narrowing
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) — save
almost nothing here, however much they matter to the app as a whole.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel: same Python code, same compiled extension. What
differs is the environment, and that is where the bugs are — on desktop a port stays bound as
long as you like, the process is never suspended, and a hardcoded port usually works. Exercise
the lifecycle path, the ephemeral port and the first-launch storage path on a device or
emulator, not only under `flet run`.

## Things to know

- **The compiled `tornado.speedups` extension is present in these wheels.** Every published
  slice ships `tornado/speedups.abi3.so`, holding exactly one function — `websocket_mask()`,
  which XORs a frame against its 4-byte key. The rest of tornado is Python. Upstream marks the
  extension optional, so a wheel built without it still imports and still serves, masking in a
  Python loop instead.

- **Present and *in use* are different questions.** `from tornado import speedups` only proves
  the file is there. `tornado.util` picks the masking implementation once, at import, and
  [`tornado.websocket`](https://www.tornadoweb.org/en/stable/websocket.html) uses whatever it
  picked — and setting `TORNADO_EXTENSION=0` or `TORNADO_NO_EXTENSION` makes it pick the Python
  loop with the `.so` sitting right there unused. `tornado.util._websocket_mask.__module__`
  answers the real question: `"tornado.speedups"` means the C path is live, `"tornado.util"`
  means it is not. It is a private name, so treat it as a diagnostic, not an API.

- **`tornado.curl_httpclient` is not usable.** It needs `pycurl`, which has no mobile wheel.
  `AsyncHTTPClient()` returns the pure-Python `simple_httpclient` implementation, and
  [`CurlAsyncHTTPClient`](https://www.tornadoweb.org/en/stable/httpclient.html#tornado.curl_httpclient.CurlAsyncHTTPClient)
  raises `ImportError` if you configure it. Same for `tornado.platform.caresresolver`
  (`pycares`) and `tornado.platform.twisted` (`twisted`).

- **Process-level features do not apply.**
  [`fork_processes`](https://www.tornadoweb.org/en/stable/process.html#tornado.process.fork_processes),
  [`autoreload`](https://www.tornadoweb.org/en/stable/autoreload.html) and
  `options.parse_command_line()` assume a forking server started from a command line, and Flet
  supports neither [`multiprocessing`](https://flet.dev/docs/cookbook/multiprocessing/) nor a
  CLI on Android or iOS. One process, one loop.

- **On Android, loopback is not private to your app.** Any installed app holding the `INTERNET`
  permission can connect to `127.0.0.1:<port>`, and an ephemeral port is obscurity rather than
  access control. If the local API does anything that matters, mint a random token at startup
  and require it in a header.

- **A WebView pointed at `http://127.0.0.1:<port>` meets Android's cleartext rule.** Python
  clients inside the app are unaffected, because the rule lives in Android's Java networking
  stack rather than the kernel. But Flet's generated `AndroidManifest.xml` sets no
  `usesCleartextTraffic` and ships no network-security config, and cleartext is disallowed by
  default from API 28, so expect that load to be refused. The template does render arbitrary
  `android:*` attributes onto `<application>`, which is the lever:

  ```toml
  [tool.flet.android.manifest_application]
  usesCleartextTraffic = "true"
  ```

  That opens cleartext to every host, so a network-security config limiting it to
  `127.0.0.1` is the better trade. Read out of the generated manifest template; not measured
  on a device.

- **Tornado logs through `logging`, which on device means the console.**
  [`tornado.access`](https://www.tornadoweb.org/en/stable/log.html) gets one line per finished
  request — `info` below 400, `warning` for 4xx, `error` for 5xx — and handler tracebacks go to
  `tornado.application` at `error`. With logging unconfigured only the warnings and errors
  reach stderr, so a failing request shows up in the device log while a successful one does
  not. Usually the quickest way to see why a handler returns 500 on a phone.

## Build notes (maintainers)

### Recipe shape

Tornado is Python apart from one small, self-contained C file, so the question is why it needs
a recipe at all. The answer is packaging rather than compilation: upstream publishes no
`py3-none-any` wheel — every PyPI artifact is a platform-tagged `cp39-abi3` wheel plus an sdist
— so a mobile install matches nothing and falls back to building that sdist during packaging.
Adding tornado to `[tool.flet] source_packages` was rejected for the same reason: that route is
for pure-Python sdists, and this one carries an extension that has to cross-compile. The sdist
otherwise builds unmodified — no patches, no host requirements, no build script.

### Upgrade hazards

The extension is built with `Py_LIMITED_API` at `0x03090000` and tagged `cp39-abi3` upstream;
forge retags the result to a per-Python platform wheel. A bump that moves the limited-API floor,
or stops using the limited API, changes what is being retagged — check the resulting filenames
and the `WHEEL` tag, not just that the build was green. `tornado/test` shipping inside the
package is upstream's choice too: if it stops, the size figure and the cleanup snippet above
are both wrong.

### Re-verification checklist

- **The extension is really there:** `tornado/speedups.abi3.so` in all six slices, with the
  right machine type for each. The recipe makes the extension mandatory, so a compile failure
  fails the build rather than yielding a pure-Python wheel — but a wheel that lost the `.so`
  any other way still imports and still serves, so nothing else announces it.
- **32-bit correctness:** `speedups.c` picks a 64-bit masking loop with
  `if (sizeof(size_t) >= 8)`, so armeabi-v7a takes a different path through the same function.
  The mask round-trip test covers that; keep it.
- **Dependencies stay empty:** the wheel metadata declares no `Requires-Dist`. Anything
  appearing there needs a recipe of its own before this one can ship.
- **Optional-import claims:** confirm `curl_httpclient`, `caresresolver` and `platform.twisted`
  are still the only pieces needing absent third-party packages.
- **Size:** re-measure compressed and unpacked from the wheels, and recheck the `tornado/test`
  share, rather than scaling these figures.

### Coverage gaps

The device tests cover the compiled extension loading, a `websocket_mask` round trip, and
importing `tornado.ioloop`. They bind no socket, serve no request, run no client and never
touch the lifecycle path — so everything this page says about *running a server* rests on the
example app and on desktop runs, not on device coverage. A test that binds an ephemeral
loopback port, answers one request and shuts down again would close most of that gap, and is
worth adding before any claim here is strengthened.

They also test the extension by importing it directly, which proves it is present and callable
but not that `tornado.util` selected it — the pure-Python fallback passes that test unchanged.
Asserting `tornado.util._websocket_mask.__module__ == "tornado.speedups"` would close that gap
in one line.
