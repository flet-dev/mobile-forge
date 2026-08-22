# websockets

[`websockets`](https://websockets.readthedocs.io/en/stable/) is the reference WebSocket
implementation for Python: a client *and* a server, built on a sans-I/O protocol core with an
[asyncio](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html) binding on
top. It fits Flet the way asyncio libraries do — a Flet session already *is* an event loop, so
a connection is a coroutine on it rather than a thread you have to manage, and a server you
start inside `main` goes on serving from that same loop after `main` returns.

What this index adds over PyPI is **exactly one file**: `websockets/speedups`, the C frame-mask
accelerator. Every other entry in the wheel is upstream's own, so
[upstream's documentation](https://websockets.readthedocs.io/en/stable/) applies unchanged and
the one question this page really has to answer is whether you are getting that file. By
default you are not.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "websockets",
]
```

**A bare `websockets` does not give you the wheel from this index — on any slice.**
`flet build` installs with `pip install --upgrade --only-binary :all: --extra-index-url
https://pypi.flet.dev`, so pip sees PyPI *and* this index and takes the highest version it can
use. Upstream's 17.0.1 publishes a `py3-none-any` wheel that satisfies every Android and iOS
tag, and it outranks this index's platform wheels on version alone. Measured with one
`pip download` per slice — Android arm64-v8a on 3.12 and 3.14, armeabi-v7a on 3.14, x86_64 on
3.13, the iOS device slice on 3.14 and an iOS simulator slice on 3.13 — all six came back
`websockets-17.0.1-py3-none-any.whl`, which carries `speedups.c` and `speedups.pyi` and no
compiled module anywhere.

Nothing is broken by that. The pure-Python fallback is a complete, working websockets, and the
example in [`examples/`](examples) runs against it unchanged; you simply do not get the
accelerator, and nothing on screen tells you so. To get it, pin your own dependency to the
version [`meta.yaml`](meta.yaml) declares — re-running the same six resolves with that `==`
pin returned this index's platform wheel every time, because at equal version pip ranks a
platform tag above `py3-none-any`.

One consequence of pinning is worth planning for: upstream raised its floor to `>=3.11` in
17.0.1, while the version on this index is still `>=3.10`. A pinned app keeps
`requires-python = ">=3.10"` today, and letting the pin drift onto 17.x means raising it in the
same commit — otherwise `flet build` stops with *No solution found when resolving dependencies
for split*, naming the Python version rather than the pin.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`loopback-feed`](examples/loopback-feed) — a websockets server streaming to websockets' own
  client on `127.0.0.1`.

## Usage in a Flet app

Write an `async def main`, open the connection in a task, and append each message to a
[`ListView`](https://flet.dev/docs/controls/listview/) as it arrives:

```python
CONTEXT = ssl.create_default_context(cafile=certifi.where())


async def main(page: ft.Page):
    async def listen():
        async with connect(URI, ssl=CONTEXT, proxy=None) as socket:
            async for message in socket:
                feed.controls.append(ft.Text(message))
                page.update()

    page.add(feed := ft.ListView(expand=True))
    page.run_task(listen)
```

Import
[`connect`](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html#websockets.asyncio.client.connect)
from `websockets.asyncio.client` and
[`serve`](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html#websockets.asyncio.server.serve)
from `websockets.asyncio.server`. Both arguments a mobile app should not leave to the defaults
are in the snippet: `ssl=`, because the device has no trust store for the default context to
find, and `proxy=`, because every client connect otherwise consults the system proxy
configuration. [Things to know](#things-to-know) has the symptom for each — including the one
that bites when `URI` is `ws://`, where passing `ssl=` at all raises before a socket is opened.

### Threading

**websockets is asyncio, so on Flet the answer is almost always "no thread at all".** Flet
awaits an `async def main(page)` directly inside the session's event loop, and awaits it to
completion before its first post-`main` update. So:

- **Write `async def main(page)` and use websockets straight from it.** No `asyncio.run`, no
  loop of your own.
- **Start background work with
  [`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task), never
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread).** A
  thread has no running loop to await a coroutine on, and `run_thread` never retrieves its
  worker's future, so whatever that worker raises disappears without a traceback.
- **End every `run_task` body with an explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).** Flet's
  auto-update fires only around event handlers and around `main`, and a `run_task` body is
  outside both.
- **Put the re-entrancy guard in the handler, not in the `run_task` body.** `run_task`
  schedules and returns, so a `disabled = True` set inside the coroutine has not happened yet
  when the handler returns and Flet pushes the control's state. A second tap in that window is
  accepted, and two overlapping conversations mutate the same controls.
- **`await serve(...)` returns as soon as the socket is bound**, and the returned
  [`Server`](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html#websockets.asyncio.server.Server)
  goes on serving from the same loop afterwards. That is the form to use inside `main`: set the
  server up and **return**. The context-manager form is the trap, in both directions —
  `serve.__aexit__` calls `close()` and then `await wait_closed()`, so
  `async with serve(...) as server:` shuts the server down the instant the block ends, and
  keeping it alive by parking inside the block (`await asyncio.Future()`) strands the first
  render, because Flet awaits `main` to completion before its first post-`main` update. Read
  the bound port back off `server.sockets[0].getsockname()` when you bind to port `0`.
- **`websockets.sync` is the wrong half of the library here.** The threading API blocks the
  calling thread by design, so inside a Flet session it either blocks the event loop or has to
  live in a `page.run_thread` worker — the one place an exception disappears without trace. Use
  `websockets.asyncio`.

### The C accelerator

The accelerator is one function: the XOR frame mask. websockets exposes no public flag for
whether it is live, and the obvious check is always False even when it is working — upstream's
`speedups.c` declares its module name as `"websocket.speedups"`, *singular*, so
`websockets.frames.apply_mask.__module__` reads `websocket.speedups` with the extension live
and `websockets.utils` without it. Compared against `"websockets.speedups"` that is False in
both states, and a consumer who writes it concludes their build has no accelerator when it has
one.

Three checks do flip, verified against a live extension, the same install with the `.so`
renamed away, and a real install of upstream's `py3-none-any` wheel:

```python
from importlib.machinery import ExtensionFileLoader

import websockets.frames
import websockets.utils

try:
    import websockets.speedups
except ModuleNotFoundError:  # the pure-Python fallback is what shipped
    live = False
else:
    live = isinstance(
        websockets.speedups.__spec__.loader, ExtensionFileLoader
    ) and websockets.frames.apply_mask is not websockets.utils.apply_mask
```

The import is honest here because the package ships no same-named `.py` for it to fall back on,
and the
[`ExtensionFileLoader`](https://docs.python.org/3/library/importlib.html#importlib.machinery.ExtensionFileLoader)
test holds on both platforms. A fourth check, weaker but free: `type(apply_mask).__name__` is
`builtin_function_or_method` for the C one and `function` for the fallback.

**A fallback is silent and changes nothing you can see.** `frames.py` does
`try: from .speedups import apply_mask / except ImportError: from .utils import apply_mask`, so
a missing extension is not an error — same results, same API. The difference is confined to
that one operation and scales with the buffer: masking 64 KiB took 1.24 µs with the C code
against 101 µs in pure Python, 4 KiB 0.15 µs against 6.6 µs, 256 B 0.06 µs against 0.67 µs
(best of 15 runs of 200 calls, CPython 3.12 and 3.14 alike). Read that as roughly 10x at 256 B,
40x at 4 KiB and 80–100x at 64 KiB rather than one headline number, and do not read a tighter
figure off a screen — the example's own on-screen ratio is a five-by-five stopwatch whose C leg
is a few microseconds in total, and it reported anywhere between 34x and 141x across repeated
runs of one binary on one machine.

**Only client-to-server bytes go through it**, which matters less than it sounds if your app
mostly *receives*. RFC 6455 masks in one direction only, and `protocol.py` implements exactly
that: `mask=self.side is CLIENT` on the write path, `mask=self.side is SERVER` on the read
path. So a client masks what it sends, a server unmasks what it receives, and everything
travelling server-to-client skips `apply_mask` altogether. Instrumented, one 200-message run of
the [`loopback-feed`](examples/loopback-feed) example pushes 36,675 B down the wire and hands
`apply_mask` **6 calls totalling 48 B** — the client's ping, its count request and its close. A
feed of that shape cannot tell a working accelerator from a missing one, so decide the question
with the check above, not with a stopwatch on your traffic.

### Android

**The `INTERNET` permission is already there.** `flet build` starts its
[permission table](https://flet.dev/docs/publish/android/#permissions) from
`{"android.permission.INTERNET": True}` and merges your entries into it, so opening or binding
a socket needs no `pyproject.toml` entry. This is the only platform where the question exists.

**The accelerator is not where the wheel put it.** Flet relocates every native module into the
APK's `jniLibs/<abi>/`, flattening the dotted module name into `lib<name-with-dashes>.so` and
leaving a `.soref` marker behind for its import hook to follow, so `websockets.speedups`
becomes `libwebsockets-speedups.so`. The import works; what changes is that a relocated
extension's `__file__` is not a path you can open. `speedups` is a *submodule*, so it cannot hit
the `lib<pkg>.so` collision that bites packages whose `__init__` is itself the extension — and
serious_python's import hook hands back a real `ExtensionFileLoader`, which is what makes the
check above correct on Android as well as iOS.

**Site-packages is a ZIP here, a directory on iOS.** websockets runs out of it as-is: nothing
in the package opens a file and it reads no data file at import, so there is no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry to write.

### iOS

**The accelerator needs no fixing up and no preloading.** It links only `Python.framework` and
`libSystem`, so there is no third-party dylib to ship beside it and it cannot hit the
`MH_BUNDLE` load failure other recipes on this index have run into. iOS lifts it into a signed
framework and leaves a `.fwork` stub at the path the wheel used — the counterpart of Android's
relocation, with the same consequence for `__file__`. The stub imports through
`AppleFrameworkLoader`, a subclass of `ExtensionFileLoader`, so one `isinstance` test covers
both platforms.

**The iOS binary is about ten times the Android one on disk, and it is not extra code.** Roughly
67 KB against 7 KB, because Mach-O aligns its segments to 16 KB around about a kilobyte of
actual instructions. Nothing is missing from the Android build.

### App size

Approximately 0.17 MB compressed and 0.64–0.70 MB unpacked per slice. Almost all of that is the
Python layer — about 0.61 MB, byte-for-byte identical on every slice — and the accelerator
itself is the rounding error, about 7 KB on Android and 67 KB on iOS.

Roughly 45% of the Python layer is code a `websockets.asyncio` app never imports: the
deprecated `websockets/legacy/` stack is about 0.16 MB across nine modules and
`websockets/sync/` another 0.11 MB. Neither is reachable from
`websockets.asyncio.client`/`.server`, so they cost bytes rather than import time, and there is
nothing to trim by hand — [`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup)
has nothing worth adding here either. It is a figure to know when sizing a payload rather than
one to act on.

Wheels are published for all three Android ABIs Flet targets and for the iOS device plus both
simulator slices, on Python 3.12, 3.13 and 3.14, so narrowing
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) is a size
decision rather than a necessity — and armeabi-v7a is a genuine 32-bit build rather than a stub.
On Android an app bundle, split APKs or a narrowed `target_arch` are the levers; at well under a
megabyte per slice the package is unlikely to be the reason you reach for one.

### Other considerations

**A desktop `flet run` resolves a different wheel, and it is the one with the accelerator in
it.** Upstream's desktop wheels ship a compiled `speedups` —
`websockets-17.0.1-cp313-cp313-macosx_11_0_arm64.whl` carries a 51 KB
`speedups.cpython-313-darwin.so` — while the only 17.0.1 wheel that satisfies an Android or iOS
tag is `py3-none-any`, which carries the C source and nothing built. With a bare dependency the
accelerator is therefore live under `flet run` and dead on device: the question this page is
about is precisely the one desktop never asks. Run the check in
[The C accelerator](#the-c-accelerator) on a device, and do not read desktop timings for a
send-heavy screen as mobile ones.

Two more things a desktop run settles wrongly. `ssl.create_default_context()` finds the
operating system's trust store there and nothing at all on device, so a `wss://` call that works
under `flet run` says nothing about the phone. And whether the OS lets your app bind a listening
socket at all is a device question — worth putting on screen in a build you install, rather than
inferring from a desktop run that always succeeds.

## Things to know

- **A server handler takes one argument.** `async def handler(websocket, path)` — the signature
  every pre-14.0 tutorial shows — raises
  `TypeError: … missing 1 required positional argument: 'path'` inside the server, logged under
  `connection handler failed`, while the client sees only
  `ConnectionClosedError: received 1011 (internal error); then sent 1011 (internal error)`,
  which names nothing about a handler. Write `async def handler(websocket)` and read the path
  off `websocket.request.path`. Treat any 1011 on a connection you also serve as a handler
  exception first.
- **The top-level names are the asyncio ones — but the per-module ones are still legacy.**
  `websockets.connect` and `websockets.serve` alias into `websockets.asyncio.client` /
  `websockets.asyncio.server`. `from websockets.client import connect` and
  `from websockets.server import serve` still work and hand back the **deprecated legacy**
  implementation instead (`websockets.client.__all__` is `['ClientProtocol']` — there is no
  non-legacy `connect` in that module). The same applies to the top-level
  `WebSocketServerProtocol`, `WebSocketClientProtocol`, `WebSocketCommonProtocol`, `framing` and
  `handshake`. Each emits a `DeprecationWarning` that Python shows only for `__main__` by
  default, so on a device you see nothing at all. Import from `websockets.asyncio.client` /
  `websockets.asyncio.server` explicitly;
  `grep -rn 'websockets.legacy\|websockets.client import\|websockets.server import' src/` is a
  fast audit of your own code for tutorial-copied imports. See upstream's
  [upgrade guide](https://websockets.readthedocs.io/en/stable/howto/upgrade.html).
- **Only pass `ssl=` for `wss://`.** Both mismatches raise before a socket is opened, which
  reads like a bad URL: `connect("ws://…", ssl=True)` gives
  `ValueError: ssl argument is incompatible with a ws:// URI`, and `connect("wss://…",
  ssl=None)` gives `ValueError: ssl=None is incompatible with a wss:// URI`.
  (`connect("ws://…", ssl=None)` is fine.)
- **Do not assume `wss://` to a public host works — pass a CA bundle explicitly.** For a `wss://`
  URI websockets does `kwargs.setdefault("ssl", True)` and builds a bare
  `ssl.create_default_context()` with no `cafile`, and the package never mentions `certifi`
  anywhere. On a desktop that context has a system trust store behind it; on device the Python
  runtime provides none, and the handshake fails with a certificate-verification error against a
  host every browser trusts. The fix needs no new dependency, because
  [`certifi`](https://pypi.org/project/certifi/) is already in your payload via `flet` →
  `httpx`:

  ```python
  ctx = ssl.create_default_context(cafile=certifi.where())
  async with connect(uri, ssl=ctx) as websocket:
      ...
  ```

  Plain `ws://` needs nothing configured.
- **Every client connect consults the system proxy configuration by default.** `connect(...)`
  takes `proxy: str | Literal[True] | None = True`, and `True` means looking the proxy up
  through `urllib.request` — which off macOS and Windows reads `*_proxy` environment variables
  and is inert without them, though what Flet's mobile runtimes report for `sys.platform` was
  **not** checked on a device here. Pass `proxy=None` for a loopback or known-direct
  connection: it is unambiguous, skips the lookup entirely and costs nothing. See upstream's
  [proxy docs](https://websockets.readthedocs.io/en/stable/topics/proxies.html).
- **The keepalive defaults close a stalled connection rather than waiting on it.** Both `connect`
  and `serve` default to `ping_interval=20` and `ping_timeout=20`, plus `close_timeout=10` and,
  on the client, `open_timeout=10` — so a link that stops delivering is torn down somewhere
  between 20 and 40 s later instead of hanging. On a phone that is usually what you want, but it
  does mean an app that loses its radio, or sits backgrounded long enough, comes back to a closed
  connection: write the reconnect. Tune the numbers deliberately; see
  [keepalive](https://websockets.readthedocs.io/en/stable/topics/keepalive.html).
- **A message over 1 MiB closes the connection, it does not just fail.**
  [`max_size`](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html#websockets.asyncio.client.connect)
  defaults to `2**20`, and exceeding it raised
  `ConnectionClosedError: sent 1009 (message too big) frame exceeds limit of 1048576 bytes` on
  the receiving side, with `close_code` reading 1006 afterwards. Raise `max_size`, pass
  `max_size=None`, or stream with
  [`recv_streaming()`](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html#websockets.asyncio.client.ClientConnection.recv_streaming)
  if you expect large frames.
- **Compression is on by default, and the shipped defaults are already phone-sized.**
  `compression` defaults to `"deflate"` on both `connect` and `serve`, and the server-side
  defaults are `server_max_window_bits=12`, `client_max_window_bits=12`, `memLevel=5` rather
  than the RFC maximum — a negotiated handshake reports
  `PerMessageDeflate(…, remote_max_window_bits=12, local_max_window_bits=12)`. Pass
  `compression=None` to turn it off; see
  [compression](https://websockets.readthedocs.io/en/stable/topics/compression.html).
- **`ping()` gives you a latency figure twice over.** `await websocket.ping()` returns a future
  that resolves to the round-trip time in seconds, and the same measurement is assigned to
  [`websocket.latency`](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html#websockets.asyncio.client.ClientConnection.latency)
  — so `rtt = await (await websocket.ping())` and `websocket.latency` compare equal exactly,
  which makes a latency reading cheap to cross-check on screen.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is six lines — name, version, build number — with no patches, no `requirements`, no
`script_env` and no `test.requires`. That is not luck: websockets' `build-system.requires` is
`["setuptools"]` alone, it vendors no C library, and the single extension is 5,920 B of C with
no third-party include. The day this recipe needs a patch, suspect the toolchain before
reaching for one.

**The recipe cannot fail loudly if the extension stops compiling, and that is the one thing
about its shape that should change.** `setup.py` builds it as
`setuptools.Extension(..., optional=os.environ.get("BUILD_EXTENSION") != "yes")`, so with
`BUILD_EXTENSION` unset setuptools drops a failing extension and carries on. Reproduced by
appending `#error` to `speedups.c` and building the sdist: `python -m build --wheel` exited
**0** and produced a platform-tagged wheel containing `speedups.c`, `speedups.pyi` and no `.so`
— a green build shipping pure Python behind a filename indistinguishable from a good one, which
is the exact regression [Install](#install) warns app authors about. With `BUILD_EXTENSION=yes`
in the environment the identical tree fails outright (*1 error generated*, *ERROR Backend
subprocess exited when trying to invoke build_wheel*, no wheel produced). The fix is two halves:
`build: script_env: [BUILD_EXTENSION=yes]` in `meta.yaml`, and a test in `tests/` asserting that
`import websockets.speedups` succeeds.

What the index actually adds, checked against upstream's own `py3-none-any` wheel of the same
version: the same 57 entries, 55 of them byte-identical, only `RECORD` and `WHEEL` differing,
`METADATA` matching at md5 `da3b65c97cab41b11179909e1879e358`, plus one extra member —
`websockets/speedups`. Nineteen files are published for the current version and build number
(seven on cp312, six each on cp313 and cp314); the one asymmetry, an `android_24_x86` wheel that
exists for 3.12 and not for the later minors, is a slice Flet does not build for.

There is no `extract_packages` entry because the package's entire non-code payload is
`speedups.c` (5,920 B), `speedups.pyi` (102 B), a `py.typed` marker and the licence, none of it
read at runtime; the only `open(` in the package is `def open(self)` in `legacy/protocol.py`;
and `__file__` appears only in `version.py`, inside an `if not released:` block a release build
never enters. `meta.yaml` records none of that reasoning, which is why it is here.

Linkage, for comparison after a bump: on Android `DT_NEEDED` is `libm`, `libpython3.<minor>`,
`libdl` and `libc`, with 16 undefined symbols — 13 CPython entry points plus `__cxa_atexit`,
`__cxa_finalize` and `__register_atfork` from bionic. On iOS the extension is
`MH_MAGIC_64 ARM64 DYLIB NOUNDEFS DYLDLINK TWOLEVEL` against `@rpath/Python.framework/Python`
and `/usr/lib/libSystem.B.dylib`, with 14 undefined symbols, all CPython or `dyld`. The
iOS-versus-Android size gap is segment alignment, not content: `size -m` reports an 81,920 B
vmsize around 1,068 B of `__text`, over a whole binary of 20 symbols.

### Upgrade hazards

- **Whether the recipe is still worth having.** Its entire contribution is one `.so`; the day
  upstream publishes Android and iOS wheels of its own, this recipe adds nothing. Either way the
  resolution measurements have to be re-run: which wheel a bare `websockets` gets is a race
  between upstream's release cadence and this recipe's version, and the whole
  [Install](#install) section turns on it.
- **`requires-python`, both upstream's and the example's.** Upstream moved from `>=3.10` to
  `>=3.11` at 17.0.1. The example pins this recipe's version, and its `requires-python` must be
  the floor of what it pins or `flet build` dies with *No solution found … for split*.
- **The `"websocket.speedups"` module-name typo**, which is the whole reason
  [The C accelerator](#the-c-accelerator) tells consumers to avoid the `__module__` comparison.
  If upstream ever fixes it that comparison becomes valid — no reason to go back to it, but the
  paragraph would be wrong as written.
- **The alias targets.** The current version points top-level `connect`/`serve` at `.asyncio.*`;
  the previous version on this index, 13.0.1, pointed them at `.legacy.*` (checked in both
  wheels; upstream's 14.0 is the first with `.asyncio.client`). If a future release finally
  removes `websockets/legacy/`, both the deprecation bullet and the size figures change.
- **The defaults and error strings quoted above** — `ping_interval`/`ping_timeout`/
  `close_timeout`/`open_timeout`, `max_size`, `proxy=True`, the 12-bit deflate windows — are all
  upstream's wording and all subject to being reworded.

### Re-verification checklist

- **That the extension is in the wheel at all.** `unzip -l` each wheel and look for
  `websockets/speedups*.so`; a wheel without one still installs, still passes `tests/`, and is
  tagged exactly like a good one.
- **Which wheel a bare requirement resolves to**, once per target:
  `pip download --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev
  websockets`, then read the filename. Repeat with the `==` pin.
- **The example's `requires-python`**, the way a consumer meets it: copy its `pyproject.toml`
  alone into an empty directory and run `uv lock` there. A build that reused an existing lock
  proves nothing.
- **The linkage lists**, with `nm -D -u` on the ELF side. The Android `.so` is stripped, so a
  plain `nm -u` prints *no symbols at all* and hides a regression rather than showing one.
  Anything new in either list is a runtime dependency [Install](#install) does not mention.
- **The measured numbers**: per-slice wheel and unpacked sizes, the Python layer, the
  `legacy`/`sync` shares, both `.so` sizes. Re-measure rather than scaling, and quote decimal MB
  — `du -h` reports binary units and will look like a regression.
- **The masking benchmark**, with enough repetitions that its C leg is not timer noise. The
  quoted figures are best of 15 runs of 200 calls; the example's on-screen five-by-five
  stopwatch is not a benchmark and swings by 4x.

### Coverage gaps

`tests/` passes with or without the accelerator, which is the gap that matters most here:
`test_frame_mask_roundtrip` says so in its own docstring, and `test_import_api` only checks
`hasattr(websockets, "connect"/"serve")`, which the legacy stack satisfies equally. A green test
run is therefore not evidence that the wheel shipped its one contribution.

Nothing else in the on-device suite touches the network: no TLS handshake, no proxy path, no
keepalive or timeout expiry, no frame over `max_size`, no compression negotiation and no server.
websockets is not in the workflow's `SMOKE_TEST_PACKAGES` either, and `git log` shows no
standalone commit for this recipe — everything on this page was established from the shipped
wheels and from desktop runs. The [`loopback-feed`](examples/loopback-feed) example is the thing
to build and install to close that gap; its second header line (`serving ws://127.0.0.1:…`) is
the part no desktop run can establish.
