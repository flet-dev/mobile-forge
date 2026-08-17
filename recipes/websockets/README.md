# websockets

[`websockets`](https://websockets.readthedocs.io/en/stable/) is the reference WebSocket
implementation for Python: a client *and* a server, built on a sans-I/O protocol core with
an [asyncio](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html)
binding on top, and no runtime dependencies at all — the wheels here declare zero
`Requires-Dist` and zero extras, so adding it adds one package and nothing else. It fits
Flet the way asyncio libraries do: a Flet session already *is* an event loop, so a
connection is a coroutine on it rather than a thread you have to manage, and a server you
start inside `main` goes on serving from that same loop after `main` returns.

Both platforms ship, at full coverage: 19 wheels on the index for 16.0, covering every
Android ABI and every iOS slice Flet targets on Python 3.12, 3.13 and 3.14.

What this index adds over PyPI is **exactly one file**. Compared against upstream's own
`websockets-16.0-py3-none-any.whl`, the Android wheel holds the same 57 entries — 55 of
them byte-identical, only `RECORD` and `WHEEL` differ, and `METADATA` matches at md5
`da3b65c97cab41b11179909e1879e358` — plus `websockets/speedups`, the C frame-mask
accelerator. So [upstream's documentation](https://websockets.readthedocs.io/en/stable/)
applies unchanged, and the only question this page really has to answer is whether you are
getting that one file. By default you are not; see below.

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
https://pypi.flet.dev` (serious_python's `package_command.dart`), so pip sees PyPI *and*
this index and takes the highest version it can use. Upstream's 17.0.1 publishes a
`py3-none-any` wheel that satisfies every platform tag, and it outranks this index's 16.0
on version alone. Measured with one `pip download` per slice, six for six — Android
arm64-v8a on 3.12 and 3.14, armeabi-v7a on 3.14, x86_64 on 3.13, the iOS device slice on
3.14, and an iOS simulator slice on 3.13 — every one came back
`websockets-17.0.1-py3-none-any.whl`. That wheel contains `speedups.c` and `speedups.pyi`
and **no compiled module anywhere**, so what ships by default is the pure-Python fallback.

Nothing is broken by that: the fallback is a complete, working websockets, and the example
in [`examples/`](examples) runs against it unchanged. You just do not get the accelerator.
To get it, pin your own dependency to the version [`meta.yaml`](meta.yaml) declares —
re-running the same six resolves with that `==` pin returned this index's platform wheel
every time, because
at equal version pip ranks a platform tag above `py3-none-any` (so even upstream's own
`websockets-16.0-py3-none-any.whl` loses). The
[`loopback-feed`](examples/loopback-feed) example's `pyproject.toml` does exactly that, and
reports on screen which one it got.

One consequence of the pin worth knowing: upstream raised its floor to `>=3.11` in 17.0.1,
while 16.0 is still `>=3.10`. So a pinned example keeps `requires-python = ">=3.10"`, and
letting the pin drift to 17.x means raising it.

Nothing else to configure. No `flet-lib*` wheel comes along — the extension's `DT_NEEDED`
list on Android is `libm`, `libpython3.<minor>`, `libdl`, `libc` and nothing more, and its
16 undefined symbols are 13 CPython entry points plus `__cxa_atexit`, `__cxa_finalize` and
`__register_atfork` from bionic. (Read that with `nm -D -u`: the `.so` is stripped, so a
plain `nm -u` prints *no symbols* and looks like an empty table.) On iOS it links only
`Python.framework` and `libSystem`.
No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry either: the package's entire non-code payload is `speedups.c`, `speedups.pyi`, a
`py.typed` marker and the licence, none of which is read at runtime; nothing in the package
calls `open()`; and `__file__` appears only inside `version.py`'s `if not released:` block,
which a release build never enters (the module sets `released = True`). It runs out of
Android's zipped site-packages as-is.

Coverage is complete for what Flet targets — arm64-v8a, armeabi-v7a and x86_64 on Android
([the three `flet build` offers](https://flet.dev/docs/publish/android/#supported-target-architectures)),
device plus both simulator slices on iOS, on all three Python minors. No
`target_arch` narrowing is needed, and armeabi-v7a is a genuine 32-bit build rather than a
stub (`file` reports *ELF 32-bit LSB shared object, ARM*). The one gap on the index — an
`android_24_x86` wheel that exists for 3.12 but not for 3.13 or 3.14 — is a slice Flet does
not build for.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`loopback-feed`](examples/loopback-feed) — a websockets server streaming to websockets'
  own client on `127.0.0.1`, six checks deep.

## Threading

**websockets is asyncio, so on Flet the answer is almost always "no thread at all".** The
rules are the same ones the [`aiohttp`](../aiohttp#threading) page sets out — write
`async def main(page)`, start background work with
[`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task) and never
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), which
has no running loop for a coroutine and swallows whatever its worker raises; end every
`run_task` body with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update); and put any
re-entrancy guard in the *handler* rather than in the task, because `run_task` only
schedules. Two things are specific to websockets:

- **`await serve(...)` returns as soon as the socket is bound**, and the returned
  [`Server`](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html#websockets.asyncio.server.serve)
  goes on serving from the same loop afterwards. That is the form to use inside `main`:
  set the server up and **return**. The context-manager form is the trap, in both
  directions — `serve.__aexit__` calls `close()` and then `await wait_closed()`, so
  `async with serve(...) as server:` shuts the server down the instant the block ends,
  and keeping it alive by parking inside the block (`await asyncio.Future()`) strands the
  first render, because Flet awaits `main` to completion before its first post-`main`
  update. Read the bound port back off `server.sockets[0].getsockname()` when you bind to
  port `0`.
- **`websockets.sync` is the wrong half of the library here.** The threading API blocks the
  calling thread by design, so inside a Flet session it either blocks the event loop or has
  to live in a `page.run_thread` worker — which is the one place an exception disappears
  without trace. Use `websockets.asyncio`. The `sync` package still ships (112,768 B of the
  wheel) whether you import it or not.

## Android notes

**The `INTERNET` permission is already there.** `flet build` starts its
[permission table](https://flet.dev/docs/publish/android/#permissions) from
`{"android.permission.INTERNET": True}` and merges your entries into it
(`flet_cli/commands/build_base.py`), so opening or binding a socket needs no
`pyproject.toml` entry. This is the only platform where the question exists.

**The extension is not where the wheel put it.** Flet relocates every native module into
the APK's `jniLibs/<abi>/`, flattening the dotted module name into
`lib<name-with-dashes>.so` (`mangledLib` in `serious_python_android`'s `build.gradle.kts`)
and leaving a `.soref` marker behind for the import hook to follow — so
`websockets.speedups` becomes `libwebsockets-speedups.so`. The `lib<name-with-dashes>.so`
half of that was read out of a built APK on the [`aiohttp`](../aiohttp#android-notes) page
rather than re-verified for websockets here. The half the accelerator check in
[Things to know](#things-to-know) depends on needs no APK: serious_python's import hook
resolves the marker and hands back a real `importlib.machinery.ExtensionFileLoader`
(`ExtensionFileLoader(fullname, origin)` in `serious_python_android`'s `_sp_bootstrap.py`),
so the `isinstance` test is correct on Android as well as iOS. What matters for the rest of
this recipe is that `speedups` is a *submodule*, so it
cannot hit the `lib<pkg>.so` collision that bites packages whose `__init__` is itself the
extension. The practical consequence is the same as everywhere: a relocated extension's
`__file__` is not a path you can open.

**Site-packages is a ZIP here, a directory on iOS.** It costs websockets nothing, since the
wheel has no data files to read.

## iOS notes

**The extension needs no fixing up and no preloading.** `otool -hv` reports
`MH_MAGIC_64 ARM64 DYLIB NOUNDEFS DYLDLINK TWOLEVEL`, and `otool -L` lists only
`@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib` — so it cannot hit the
`MH_BUNDLE` link failure that has bitten other recipes on this index, and there is no
third-party dylib to ship beside it. `nm -u` lists 14 symbols, all CPython or `dyld`.

**The iOS `.so` is about ten times the Android one on disk and it is not extra code.**
67,248 B against 6,992 B on arm64-v8a, because Mach-O aligns four segments to 16 KB:
`size -m` reports an 81,920 B vmsize around 1,068 B of actual `__text`, and the whole
binary has 20 symbols. Nothing is missing from the Android build.

**Loader class, if you check for the accelerator yourself.** iOS lifts each extension into
a signed framework and leaves a `.fwork` stub at the path the wheel used, which imports
through `AppleFrameworkLoader` — a subclass of `importlib.machinery.ExtensionFileLoader`,
so an `isinstance(..., ExtensionFileLoader)` test is correct on both platforms. Established
from a built simulator bundle on the [`aiohttp`](../aiohttp#ios-notes) page, not
re-verified for websockets here.

## Things to know

- **The obvious way to check for the accelerator is always False, even when it is
  working.** Upstream's `speedups.c` declares its module name as `"websocket.speedups"` —
  singular — so `websockets.frames.apply_mask.__module__` reads `websocket.speedups` with
  the extension live and `websockets.utils` without it. A comparison against
  `"websockets.speedups"` is therefore False in both states and discriminates nothing,
  and a consumer who writes it concludes their build has no accelerator when it does.
  Three checks that do flip, verified against a live extension, the same install with the
  `.so` renamed away, and a real install of upstream's `py3-none-any` wheel:

  ```python
  import websockets.speedups                                  # ModuleNotFoundError on fallback
  websockets.frames.apply_mask is not websockets.utils.apply_mask
  isinstance(websockets.speedups.__spec__.loader, ExtensionFileLoader)
  ```

  The first is honest here because the package ships no same-named `.py` for the import to
  fall back on. A fourth, weaker but free: `type(apply_mask).__name__` is
  `builtin_function_or_method` for the C one and `function` for the fallback.
- **A fallback is silent, and it changes nothing you can see.** `frames.py` does
  `try: from .speedups import apply_mask / except ImportError: from .utils import apply_mask`,
  so a missing extension is not an error — the results are identical and the API is
  identical. Measured on a desktop, the difference is confined to the one operation it
  accelerates, and it scales with the buffer: masking 64 KiB took 1.24 µs with the C code
  against 101 µs in pure Python, 4 KiB 0.15 µs against 6.6 µs, 256 B 0.06 µs against
  0.67 µs — best of 15 runs of 200 calls each, on CPython 3.12 and 3.14 alike. So the
  speed-up is a function of message size, roughly 10x at 256 B, 40x at 4 KiB and 80–100x at
  64 KiB, not one headline number. Do not read a tighter figure than that off a screen: the
  example's own on-screen ratio is a 5-by-5 stopwatch whose C leg is a few microseconds
  total, and it reported anywhere between 34x and 141x across repeated runs of the same
  binary on one machine.
- **Only client-to-server bytes go through the accelerator**, which is smaller than it
  sounds if your app mostly *receives*. RFC 6455 masks in one direction only, and
  `protocol.py` implements exactly that: `mask=self.side is CLIENT` on the write path,
  `mask=self.side is SERVER` on the read path. So a client masks what it sends and a server
  unmasks what it receives, and everything travelling server-to-client skips `apply_mask`
  altogether. Instrumenting the [`loopback-feed`](examples/loopback-feed) example makes the
  asymmetry concrete: one 200-message run pushes 36,675 B down the wire but hands
  `apply_mask` **6 calls totalling 48 B** — the client's ping, its count request and its
  close. A run of that shape cannot tell a working accelerator from a missing one, which is
  why the example decides the question with the import check and a stopwatch instead, and
  why all six of its checks pass either way.
- **The top-level names are the asyncio ones — but the per-module ones are still legacy.**
  `websockets.connect` and `websockets.serve` alias into
  `websockets.asyncio.client` / `websockets.asyncio.server`. `from websockets.client import
  connect` and `from websockets.server import serve` still work and hand back the
  **deprecated legacy** implementation instead (`websockets.client.__all__` is
  `['ClientProtocol']` — there is no non-legacy `connect` in that module). The same applies
  to the top-level `WebSocketServerProtocol`, `WebSocketClientProtocol`,
  `WebSocketCommonProtocol`, `framing` and `handshake`. Each emits a `DeprecationWarning`
  that Python shows only for `__main__` by default, so on a device you see nothing at all.
  Import from `websockets.asyncio.client` / `websockets.asyncio.server` explicitly, and
  `grep -rn 'websockets.legacy\|websockets.client import\|websockets.server import' src/`
  is a fast audit of your own code for tutorial-copied imports. See upstream's
  [upgrade guide](https://websockets.readthedocs.io/en/stable/howto/upgrade.html).
- **A server handler takes one argument.** `async def handler(websocket, path)` — the
  signature every pre-14.0 tutorial shows — raises
  `TypeError: … missing 1 required positional argument: 'path'` inside the server, logged
  under `connection handler failed`, while the client sees only
  `ConnectionClosedError: received 1011 (internal error); then sent 1011 (internal error)`,
  which names nothing about a handler. Write `async def handler(websocket)` and read the path off
  `websocket.request.path`. Treat any 1011 on a connection you also serve as a handler
  exception first.
- **Only pass `ssl=` for `wss://`.** Both mismatches raise before a socket is opened, which
  reads like a bad URL: `connect("ws://…", ssl=True)` gives
  `ValueError: ssl argument is incompatible with a ws:// URI`, and
  `connect("wss://…", ssl=None)` gives `ValueError: ssl=None is incompatible with a wss://
  URI`. (`connect("ws://…", ssl=None)` is fine.)
- **Do not assume `wss://` to a public host works — pass a CA bundle explicitly.** For a
  `wss://` URI websockets does `kwargs.setdefault("ssl", True)` and then builds a bare
  `ssl.create_default_context()` with no `cafile`, and the package never mentions `certifi`
  anywhere. On a desktop that context has a system trust store behind it; on device nothing
  in the Python runtime provides one — the [`aiohttp`](../aiohttp#things-to-know) and
  [`cryptography`](../cryptography) pages measure that in detail rather than assume it.
  The fix needs no new dependency, because `certifi` is already in your payload via
  `flet` → `httpx`:

  ```python
  ctx = ssl.create_default_context(cafile=certifi.where())
  async with connect(uri, ssl=ctx) as websocket:
      ...
  ```

  Plain `ws://` needs nothing configured.
- **Every client connect consults the system proxy configuration by default.**
  `connect(...)` takes `proxy: str | Literal[True] | None = True`, and `proxy is True`
  means `get_proxy(uri)`, which calls `urllib.request.proxy_bypass()` and
  `urllib.request.getproxies()`. `urllib/request.py` binds those two names in a
  `if sys.platform == 'darwin' / elif os.name == 'nt' / else` chain, and everything that
  falls through to the `else` gets the environment-variable readers (checked in 3.14), so
  off macOS and Windows the lookup is inert — but what Flet's mobile runtimes report for
  `sys.platform` was **not** checked on a device here. Pass `proxy=None` for a
  loopback or known-direct connection: it is unambiguous, skips the lookup entirely, and
  costs nothing. See upstream's
  [proxy docs](https://websockets.readthedocs.io/en/stable/topics/proxies.html).
- **The keepalive defaults close a stalled connection rather than waiting on it.** Both
  `connect` and `serve` default to `ping_interval=20` and `ping_timeout=20`, plus
  `close_timeout=10` and, on the client, `open_timeout=10` — so a link that stops
  delivering is torn down somewhere between 20 and 40 s later instead of hanging. On a
  phone that is usually the behaviour you want, but it does mean an app that loses its
  radio, or sits backgrounded long enough, comes back to a closed connection: write the
  reconnect. Tune the numbers deliberately; see
  [keepalive](https://websockets.readthedocs.io/en/stable/topics/keepalive.html).
- **A message over 1 MiB closes the connection, it does not just fail.** `max_size` defaults
  to `2**20`, and exceeding it raised
  `ConnectionClosedError: sent 1009 (message too big) frame exceeds limit of 1048576 bytes`
  on the receiving side, with `close_code` reading 1006 afterwards. Raise `max_size`, pass
  `max_size=None`, or stream with `recv_streaming()` if you expect large frames.
- **Compression is on by default, and the shipped defaults are already phone-sized.**
  `compression` defaults to `"deflate"` on both `connect` and `serve`, and the server-side
  defaults are `server_max_window_bits=12`, `client_max_window_bits=12`,
  `memLevel=5` rather than the RFC maximum — a negotiated handshake reports
  `PerMessageDeflate(…, remote_max_window_bits=12, local_max_window_bits=12)`. Pass
  `compression=None` to turn it off; see
  [compression](https://websockets.readthedocs.io/en/stable/topics/compression.html).
- **`ping()` gives you a latency figure twice over.** `await websocket.ping()` returns a
  future that resolves to the round-trip time in seconds, and the same measurement is
  assigned to
  [`websocket.latency`](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html#websockets.asyncio.client.ClientConnection.latency)
  — so `rtt = await (await websocket.ping())` and `websocket.latency` compare equal
  exactly, which makes a latency reading cheap to cross-check on screen.
- **Nothing is written to disk.** websockets opens no file, reads no data file at import,
  and chooses no path of its own — so there is no
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  question here at all.
- **Size, and how much of it is code you should not call.** The wheel is about 174 KB —
  174,094 to 174,844 B across all 19 — unpacking to 638,358 B on Android arm64-v8a,
  635,876 B on armeabi-v7a and 698,605 B on the iOS device slice (3.13 and 3.14; 3.12 is
  within 16 B of each). 612,044 B of that is the Python layer, byte-for-byte identical on
  every slice — the native code is a rounding error. Of the Python layer, the deprecated
  `websockets/legacy/` stack is 163,141 B across nine modules (27%) and `websockets/sync/`
  another 112,768 B. There is nothing to trim by hand — neither is imported by
  `websockets.asyncio.client`/`.server` (checked against `sys.modules` after the example's
  own import list), so they cost bytes rather than import time — but it is worth knowing
  when sizing a payload.

## Build notes (maintainers)

The recipe is six lines of `meta.yaml` — name, version, build number — with no patches, no
`requirements`, no `script_env` and no `test.requires`. That is not luck: websockets'
`build-system.requires` is `["setuptools"]` alone, it vendors no C library, and the single
extension is 5,920 B of C with no third-party include. The day this recipe needs a patch,
suspect the toolchain before reaching for one.

**The one thing that should change: this recipe cannot fail loudly if the extension stops
compiling.** `setup.py` builds it as
`setuptools.Extension(..., optional=os.environ.get("BUILD_EXTENSION") != "yes")`, so with
`BUILD_EXTENSION` unset setuptools drops a failing extension and carries on. Reproduced by
appending `#error` to `speedups.c` and building the sdist: `python -m build --wheel` exited
**0** and produced a platform-tagged wheel containing `speedups.c`, `speedups.pyi` and no
`.so` — a green build shipping pure Python behind a filename indistinguishable from a good
one, which is the precise regression the [Install](#install) section warns app authors
about. With `BUILD_EXTENSION=yes` in the environment the identical tree fails outright
(*1 error generated*, *ERROR Backend subprocess exited when trying to invoke build_wheel*,
no wheel produced). The fix is two halves: add `build: script_env: [BUILD_EXTENSION=yes]`
to `meta.yaml`, and make `tests/` assert that `import websockets.speedups` succeeds. Today
it does neither — `tests/test_websockets.py::test_frame_mask_roundtrip` says in its own
docstring that it passes either way, and `test_import_api` only checks
`hasattr(websockets, "connect"/"serve")`, which the legacy stack satisfies equally.

**There is no evidence this version has ever run on a device.** `git log` shows no
standalone commit for this recipe — 16.0 arrived with `e4e0d28`, a repo-wide bump, followed
only by a repo-wide normalisation — and websockets is not in the workflow's
`SMOKE_TEST_PACKAGES`. Everything above was established from the shipped wheels and from
desktop runs; the [`loopback-feed`](examples/loopback-feed) example is the thing to build
and install to close that gap, and its second header line (`serving ws://127.0.0.1:…`) is
the part no desktop run can establish.

On a version bump, and everything above this section is a claim a bump can falsify without
the build failing:

- **Whether the recipe is still worth having.** Its entire contribution is one `.so`; if
  upstream ever publishes Android and iOS wheels of its own, this recipe adds nothing.
  Conversely, re-run the resolution measurements either way: which wheel a bare
  `websockets` gets is a race between upstream's release cadence and this recipe's version,
  and the whole [Install](#install) section turns on it. One
  `pip download --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev
  websockets` per target, then read the filename.
- **`requires-python`, both upstream's and the example's.** 16.0 is `>=3.10`, 17.0.1 is
  `>=3.11`. The example pins the recipe's version and its `requires-python` must be the
  floor of what it pins, or `flet build` dies with *No solution found … for split*. Check
  it the way a consumer meets it: `pyproject.toml` alone in an empty directory, `uv lock`.
- **The `"websocket.speedups"` module-name typo**, which is the whole reason
  [Things to know](#things-to-know) tells consumers to avoid the `__module__` comparison.
  If upstream ever fixes it that comparison becomes valid — there is still no reason to go
  back to it, but the paragraph would be wrong as written.
- **The alias targets.** 16.0 points top-level `connect`/`serve` at `.asyncio.*`; the
  previous version on this index, 13.0.1, pointed them at `.legacy.*` (checked in both
  wheels; upstream's 14.0 is the first with `.asyncio.client`). If a future release finally
  removes `websockets/legacy/`, both the deprecation bullet and the size figures change.
- **The measured numbers**: per-slice wheel and unpacked sizes, the 612,044 B Python layer,
  the `legacy`/`sync` shares, the two `.so` sizes and the iOS segment breakdown, and the
  masking benchmark. Re-measure rather than scaling — and give the benchmark enough
  repetitions that its C leg is not timer noise (the quoted figures are best of 15 runs of
  200 calls; the example's on-screen 5-by-5 stopwatch is not a benchmark and swings by 4x).
- **The defaults quoted above** — `ping_interval`/`ping_timeout`/`close_timeout`/
  `open_timeout`, `max_size`, `proxy=True`, the 12-bit deflate windows — and the error
  strings, which are all upstream's wording and all subject to being reworded.
- **The linkage lists.** Android `DT_NEEDED` is `libm`, `libpython3.<minor>`, `libdl`,
  `libc`, and `nm -D -u` gives 16 undefined symbols, 13 CPython and 3 bionic; iOS is
  `MH_DYLIB`/`NOUNDEFS` with only `Python.framework` and `libSystem`, and `nm -u` gives 14,
  all CPython or `dyld`. Anything new in either list is a runtime dependency
  [Install](#install) does not mention. Use `nm -D -u` on the ELF side — the Android `.so`
  is stripped, so a plain `nm -u` reports nothing at all and hides a regression rather than
  showing one.
