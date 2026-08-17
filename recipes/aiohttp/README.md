# aiohttp

[`aiohttp`](https://docs.aiohttp.org/en/stable/) is asyncio's HTTP stack: a client with
connection pooling, streaming bodies, transparent decompression and WebSockets, and a
complete [web server](https://docs.aiohttp.org/en/stable/web_quickstart.html) in the same
package. On a phone the client half is the obvious draw, and it fits Flet unusually well — a
Flet session already *is* an event loop, so a request is a coroutine on it rather than a
thread you have to manage, and concurrency comes from the loop instead of from a pool you
size.

The server half is the less obvious one: an in-process HTTP and WebSocket API, which is how
you let a WebView, the Flutter side, or a test harness talk to your Python over a protocol
they already speak instead of an ad-hoc bridge. The
[`loopback-api`](examples/loopback-api) example is exactly that shape — both halves in one
event loop, nothing leaving the device — and it prints the address it bound to, which is how
you confirm on your own device that it did.

Every file in these wheels except the four extensions and two metadata files — the whole
Python layer, and `METADATA` with it — is byte-identical to upstream's own wheel of the same
version, so [upstream's documentation](https://docs.aiohttp.org/en/stable/) applies unchanged.
What is worth knowing is what the *platform* does not give aiohttp: no CA bundle, no C
resolver, and pure-Python versions of four of its dependencies. All three are below.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "aiohttp",
]
```

**A bare `aiohttp` will not always be the wheel from this index — upstream publishes mobile
wheels of its own now.** `flet build` installs with
`pip install --upgrade --only-binary :all: --extra-index-url https://pypi.flet.dev`
(serious_python's `package_command.dart`), so pip sees PyPI *and* this index and takes the highest
version it can use. Upstream's 3.14.3 covers Python 3.13 and 3.14 only, and on Android only
arm64-v8a and x86_64 — tagged `android_21_*`, which still satisfies Flet's API-24 target — with no
armeabi-v7a. Measured, one resolve for each of the eighteen slice-and-minor combinations:

| slice | Python 3.12 | Python 3.13 and 3.14 |
| --- | --- | --- |
| Android arm64-v8a, x86_64 | this index | upstream 3.14.3 |
| Android armeabi-v7a | this index | this index |
| iOS device and both simulators | this index | upstream 3.14.3 |

So a 3.13 or 3.14 Android build carries **two different aiohttp versions across its ABIs**, and
nothing on screen says so. Neither wheel is wrong — but every figure on this page was measured on
the one from this index, so pin `aiohttp` to the version in [`meta.yaml`](meta.yaml) if you want
the wheel this page describes on every slice, as the
[`loopback-api`](examples/loopback-api) example's `pyproject.toml` does.

Nothing else to configure. No `flet-lib*` wheel comes along — the four compiled modules
resolve nothing but `libm`, `libdl`, `libc` and `libpython` on Android
(`DT_NEEDED`), and nothing but `Python.framework` and `libSystem` on iOS (`otool -L`). No
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry either: the wheel's whole non-code payload is Cython source text with its `.hash`
sidecars, two licences and a `py.typed` marker; nothing in the package opens a file at import;
and `__file__` appears nowhere in it — so it runs as-is out of Android's zipped site-packages.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS
device plus both simulator slices, on Python 3.12, 3.13 and 3.14. No
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed; armeabi-v7a is a genuine 32-bit build, not a stub.

**`aiohttp[speedups]` fails the build.** Upstream marks every CPython requirement in that
extra `sys_platform != "android" and sys_platform != "ios"` (`brotlicffi` is the exception,
and it is gated on *non*-CPython instead, so it never applies here), which looks like it
protects you and does not: `flet build` cross-installs by running pip on the *build host*
with the wheel platform tag patched, so `sys.platform` is still `darwin` (or `linux` on CI)
when markers are evaluated, and the guard comes out `True`. Everything in the extra is
therefore requested for real. Measured, resolving for Android arm64 against this index —
which of the two blockers pip reports depends on the interpreter it runs under, so treat
these as two faces of one failure rather than a per-version rule:

| Python | what you get |
| --- | --- |
| 3.14 | `ResolutionImpossible` — every `aiodns` release needs `pycares`, and "some packages in these conflicts have no matching distributions available for your environment: `pycares`" |
| 3.12 | `Could not find a version that satisfies the requirement backports.zstd` — it gets as far as downloading a mobile `Brotli` first |

Ask for what you actually want instead: plain `aiohttp`, plus `Brotli` by name if you need
`br`. zstd needs nothing at all on 3.14.

**Only aiohttp itself gets a compiled wheel; four of its dependencies fall back to pure
Python.** Resolved the way `flet build` resolves — pip with `--only-binary :all:` and
pypi.flet.dev as an extra index — an Android arm64 / Python 3.14 install of
`flet==0.86.5` + `aiohttp==3.14.0` takes the mobile `aiohttp` wheel and then the
`py3-none-any` wheels of `multidict`, `yarl`, `frozenlist` and `propcache`, plus
`aiosignal`, `aiohappyeyeballs` and `attrs`, which are pure Python upstream anyway. The
first four ship C accelerators on desktop and have no mobile wheels on PyPI at all. See
[Things to know](#things-to-know) for what that costs and the one pin that changes it.

## Storage

aiohttp chooses no path of its own — the one file it opens unasked is covered at the end of
this section. The places *you* hand it a path belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups:

```python
jar = aiohttp.CookieJar()
cookies = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "cookies.json")
if os.path.exists(cookies):
    jar.load(cookies)
...
jar.save(cookies)
```

[`CookieJar.save`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.CookieJar.save)
writes JSON and creates the file mode `0600`, which is the right default for something that
usually holds a session token;
[`load`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.CookieJar.load)
reads that back and falls back to the legacy pickle format for files written by older
releases. The other path is server-side —
[`web.FileResponse`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.FileResponse)
and static routes serve whatever you point them at, so that is your data and your directory
choice.

From Flet 0.86.0 `FLET_APP_STORAGE_DATA` is also the process working directory on device, so
a bare relative filename lands there; spelling it out costs one line and behaves the same on
desktop. Do not keep a cookie jar in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

The exception, and it is server-side only: `Request.post()` spools each multipart field that
carries a `filename` into a `tempfile.TemporaryFile`, in whatever directory the stdlib
`tempfile` module picks rather than in Flet's app storage. TemporaryFile is unlinked as soon as
it is opened, so nothing accumulates, but the bytes do land on the device's filesystem on the
way through. The ceiling is `client_max_size`, which `web.Application` defaults to 1 MiB —
raise it deliberately, not reflexively, and reach for `request.multipart()` instead if you
would rather stream an upload straight past disk.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`loopback-api`](examples/loopback-api) — an aiohttp server and aiohttp's own client
  talking to each other on `127.0.0.1`, six checks deep.

## Threading

**aiohttp is asyncio, so on Flet the answer is almost always "no thread at all".** Flet
awaits an `async def main(page)` directly inside the session's event loop, and it awaits it
to completion before its first post-`main` update. So:

- **Write `async def main(page)` and use aiohttp straight from it.** No `asyncio.run`, no
  loop of your own.
- **Start background work with
  [`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task), never
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread).**
  `run_task` schedules the coroutine on the session's loop and attaches a done-callback that
  retrieves the future and re-raises, so a failure reaches Flet's error handling; `run_thread`
  hands work to an executor, never retrieves the future, and swallows the exception whole. A
  thread also has no running loop, so aiohttp could not be used in one without standing up a
  second loop inside it.
- **End every `run_task` body with an explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).** Flet's
  auto-update fires only around event handlers and around `main`; a task started with
  `run_task` sits outside both, so the UI will not refresh on its own.
- **Do not put a re-entrancy guard inside the `run_task` body.** `run_task` schedules the
  coroutine and returns, so anything the body sets — `button.disabled = True`, a busy flag —
  has not happened yet when the handler returns and Flet pushes the control's state. A second
  tap arriving in that window is accepted and you get two overlapping runs mutating the same
  controls. Set and test the flag in the *handler*, before `run_task`, where it is synchronous
  and the post-handler auto-update carries it.
- **Return from `main` once the setup is done.** An `async def main` that parks —
  `await asyncio.Event().wait()` to keep a server alive, say — never lets Flet reach the
  update that follows `main`, and the first render is stranded. Set the
  [runner](https://docs.aiohttp.org/en/stable/web_advanced.html#application-runners) up and
  return; it goes on serving from the same loop.
- **Never build a
  [`ClientSession`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientSession)
  at module scope.** Its constructor calls `asyncio.get_running_loop()`, so at import time it
  raises `RuntimeError: no running event loop` — before any Flet UI exists, which makes it
  look like a broken build rather than a misplaced line. Build it inside `main` or inside a
  `run_task` coroutine, ideally as `async with aiohttp.ClientSession(...) as session:`.

One thread does get used behind your back: with no `aiodns` installed the resolver is
aiohttp's `ThreadedResolver`, which calls `loop.getaddrinfo` — asyncio's own wrapper that runs
the blocking stdlib lookup in the loop's default executor. So a slow DNS server delays that one
request without blocking the loop, and the thread is the stdlib's rather than aiohttp's.
Connecting to a numeric host skips the whole path: `TCPConnector._resolve_host` returns a
synthetic result for an IP literal before any resolver is consulted, which is why a
`127.0.0.1` client does no name resolution at all.

## Android notes

**The `INTERNET` permission is already there.** `flet build` starts its permission table
from `{"android.permission.INTERNET": True}` and merges your entries into it, so opening or
binding a socket needs no `pyproject.toml` entry. This is the only platform where the
question exists.

**The four accelerators are not where the wheel put them.** Flet moves every native extension
into the APK's `lib/<abi>/`, flattening the module path into the filename, and leaves a
`.soref` marker behind in the zipped site-packages for serious_python's import hook to follow.
Read out of the [`loopback-api`](examples/loopback-api) example's own APK:

| in the wheel | in the APK | marker left behind |
| --- | --- | --- |
| `aiohttp/_http_parser…so` | `lib/<abi>/libaiohttp-_http_parser.so` | `aiohttp/_http_parser.soref` |
| `aiohttp/_http_writer…so` | `lib/<abi>/libaiohttp-_http_writer.so` | `aiohttp/_http_writer.soref` |
| `aiohttp/_websocket/mask…so` | `lib/<abi>/libaiohttp-_websocket-mask.so` | `aiohttp/_websocket/mask.soref` |
| `aiohttp/_websocket/reader_c…so` | `lib/<abi>/libaiohttp-_websocket-reader_c.so` | `aiohttp/_websocket/reader_c.soref` |

All four are submodules, so none of them can hit the `lib<pkg>.so` collision that packages
whose `__init__` *is* the extension run into. What the relocation does mean is that such an
extension's `__file__` is not a path you can open — as [`pydantic-core`](../pydantic-core)
measured, on Android it is not even set.

**OpenSSL was configured with `OPENSSLDIR="/usr/local/ssl"`** (read out of
`libcrypto_python.so`), a path that cannot exist on Android, and there is no `.pem` file
anywhere in the runtime's `stdlib.zip`. See the TLS bullet in
[Things to know](#things-to-know).

**Site-packages is a ZIP here, a directory on iOS.** It costs aiohttp nothing, since the
wheel has no data files — but it is why `certifi.where()` takes a temporary-extraction path
on Android and returns a plain filesystem path on iOS.

**Nothing in the manifest opts into cleartext HTTP.** Read out of the
[`loopback-api`](examples/loopback-api) example's own APK, `AndroidManifest.xml` carries neither
`android:usesCleartextTraffic` nor a `networkSecurityConfig`, so the platform default for the
target SDK applies. Python's sockets are not subject to that policy — which is why the example's
client reaches its own server at all — but the Dart/WebView side of the bridge this recipe's
opening paragraph advertises *is*, and whether a WebView will load `http://127.0.0.1:<port>` from
a Flet app has **not** been tested here. Establish it before designing around it.

## iOS notes

**The extensions need no fixing up and no preloading.** All four are `MH_DYLIB` with
`NOUNDEFS` (`otool -hv`) and link only `@rpath/Python.framework/Python` and
`/usr/lib/libSystem.B.dylib`, so none of them hits the `MH_BUNDLE` link failure that has
bitten other recipes on this index, and there is no third-party dylib to ship beside them.
Each is lifted into a signed framework of its own and replaced, at the path the wheel put it,
by a one-line `<name>.fwork` text file naming the framework binary. Read out of the
[`loopback-api`](examples/loopback-api) example's own simulator build:
`site-packages/aiohttp/_http_parser.fwork` holds
`Frameworks/aiohttp._http_parser.framework/aiohttp._http_parser`, and that framework carries a
`_CodeSignature` and an `MH_DYLIB`/`NOUNDEFS` binary — with `aiohttp._websocket.mask.framework`
and `aiohttp._websocket.reader_c.framework` beside it, so a submodule's dotted name becomes the
framework name. Android's relocation-plus-`.soref` reaches the same outcome by an unrelated
route, and shares none of the failure modes.

**iOS natives are about 1.5x the size of Android's** for the same four extensions:
906,944 B against 616,832 B on arm64, with `_http_parser` alone 455,416 B against 357,104 B.

**OpenSSL was configured with `OPENSSLDIR="/etc/ssl"`** here, against Android's
`/usr/local/ssl`. If TLS ever behaves differently between the two platforms, that asymmetry
is where to look first.

## Things to know

- **Do not assume HTTPS to a public host works — pass a CA bundle explicitly.**
  aiohttp builds its default `SSLContext` at *import* time from
  `ssl.create_default_context()`, with no cert file argument, and it never mentions `certifi`
  anywhere in the package. On a desktop that context comes back with a system trust store
  behind it; on device nothing in the Python runtime provides one — the Android runtime's
  `stdlib.zip` holds zero `.pem` files, and its OpenSSL default directory (`/usr/local/ssl`)
  cannot exist there at all (see the two platform notes; the iOS half of that, `/etc/ssl`, was
  not checked on a device and is not being claimed). Nothing fails at import — the failure
  would land later, at handshake, as a verification error, which reads like a server problem.
  The fix needs no new dependency, because a bundle *is* already in your app payload, just not
  anywhere OpenSSL looks: `certifi` comes in with Flet (`flet` → `httpx` → `certifi`; version
  2026.7.22 with its 240,216 B `cacert.pem`, present in both a built APK's `sitepackages.zip`
  and the iOS `site-packages`). Hand it over explicitly:

  ```python
  ctx = ssl.create_default_context(cafile=certifi.where())
  async with session.get(url, ssl=ctx) as response:
      ...
  ```

  See [SSL control](https://docs.aiohttp.org/en/stable/client_advanced.html#ssl-control-for-tcp-sockets)
  for the `ssl=` argument. This has **not** been settled by a handshake on a device here — the
  evidence above is the absence of a bundle where OpenSSL would look for one, not an observed
  failure — so treat passing `certifi.where()` as the cheap way to make the question moot. The
  [`cryptography`](../cryptography) README reaches the same conclusion about the platform
  generally: there is no trust store on the device.
- **What the client asks for depends on the Python version, and it tells you so.**
  `Accept-Encoding` is assembled at import from what is importable: `gzip, deflate, zstd` on
  Python 3.14, and `gzip, deflate` on 3.12 and 3.13. The zstd half is free on 3.14 only —
  aiohttp takes it from the stdlib `compression.zstd` there, and Flet's mobile runtimes ship
  the `_zstd` extension on both platforms (`lib_zstd.so` in Android's `jniLibs`, `_zstd.fwork`
  in the iOS runtime's `lib-dynload`). The decode path was exercised on a desktop 3.14 rather
  than on a device: a server-sent `Content-Encoding: zstd` body came back inflated with no
  intervention, 1,735 B on the wire to 24,890 B. On 3.12/3.13 aiohttp wants `backports.zstd`
  instead, which is not on this index; upstream publishes its own mobile wheels on PyPI but only
  for cp313, and with no armeabi-v7a slice.
- **`br` is not advertised, and an unsolicited `br` response raises.** `HAS_BROTLI` is false in
  a stock mobile install, so the client never offers `br` — and the decoder in `http_parser.py`
  is gated on that same flag, so a server that sends it anyway gets a `ContentEncodingError`
  that names the fix:

  ```text
  Can not decode content-encoding: brotli (br). Please install `Brotli`
  ```

  Adding `Brotli` to your dependencies does exactly that, and it resolves on every mobile
  slice, armeabi-v7a included: `recipes/brotli` builds 1.2.0 for all three Python minors. With
  it installed `Accept-Encoding` becomes `gzip, deflate, br, zstd`.
- **aiohttp's *server* can only compress with gzip or deflate.** `ContentCoding` has exactly
  three members — `deflate`, `gzip`, `identity` — so a bare
  [`enable_compression()`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.StreamResponse.enable_compression)
  negotiating against a 3.14 client's `gzip, deflate, zstd` picks **deflate**, not zstd. Pass
  `force=web.ContentCoding.gzip` if you want to know which one you got.
- **All four compiled accelerators ship on both platforms, and nothing tells you if one
  stopped working.** The set is `_http_parser` (llhttp 9.4.1, statically vendored),
  `_http_writer`, `_websocket/mask` and `_websocket/reader_c` — exactly the four upstream's
  own wheels carry, all four loaded by a plain `import aiohttp`, none of them lazy, and
  `import aiohttp.web` adds no fifth. There is no public flag for whether they are live, which
  is why the [`loopback-api`](examples/loopback-api) example prints a `C speedups n/4` line —
  but only three of the four can be checked the obvious way, by comparing against the private
  name the pure-Python twin would be bound to. **`_websocket/reader_c` cannot.** The wheel
  ships `aiohttp/_websocket/reader_c.py` — byte-identical to `reader_py.py`, 19,437 B of it —
  right beside the extension of the same name, and `reader.py` imports `.reader_c` inside a
  `try/except ImportError` that a same-named `.py` satisfies. So an unloadable extension gets
  silently replaced by pure Python under the *same* module name, and
  `WebSocketReader.__module__` still reads `aiohttp._websocket.reader_c`. Measured by hiding
  each extension in turn: hiding `reader_c` left that comparison reporting `True` while the
  module's `__file__` was the `.py`. Only the loader distinguishes them
  (`ExtensionFileLoader`, which iOS's `AppleFrameworkLoader` subclasses, against
  `SourceFileLoader`/`zipimporter`), which is what the example checks. That `.py` survives
  packaging on both platforms, so the fallback really is sitting there on device: a
  `reader_c.pyc` sits next to `reader_c.soref` in the APK (21,535 B) and next to
  `reader_c.fwork` in the iOS bundle (21,540 B). A slice that fell
  back returns identical results, and not measurably slower either — aiohttp's pure-Python
  masker is four `bytes.translate` calls, so forcing it left the example's WebSocket check at
  the same 0.9–1.0 ms.
- **`multidict`, `yarl`, `frozenlist` and `propcache` are pure Python on device, and
  `multidict` is the one that costs you.** With the pure wheels in place `CIMultiDict`
  resolves to `multidict._multidict_py` while aiohttp's own four accelerators stay live.
  Measured on a desktop that can run both, 300 loopback round trips took 40–43 ms with the C
  `multidict` and `yarl` and 55–62 ms with the pure ones. Pinning `yarl==1.24.2` *does* pull
  a compiled yarl from this index (measured: `yarl-1.24.2-1-cp314-cp314-android_24_arm64_v8a.whl`
  instead of `yarl-1.24.5-py3-none-any.whl`, which wins on version alone) — but it made no
  measurable difference in that benchmark, 60–61 ms, and it buys you a pin that a future
  aiohttp bump can put in conflict. There is no equivalent option for `multidict`.
- **`web.run_app(...)` cannot be used inside a Flet app at all.** It drives the loop itself
  (`loop.run_until_complete`), so inside Flet's already-running loop it dies with a message that
  says nothing about the actual mistake, plus a *Task was destroyed but it is pending* warning
  and a never-awaited coroutine:

  ```text
  ValueError: The future belongs to a different loop than the one specified as the loop argument
  ```

  Use the
  [runner API](https://docs.aiohttp.org/en/stable/web_advanced.html#application-runners)
  instead: [`web.AppRunner`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.AppRunner)
  plus [`web.TCPSite`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.TCPSite),
  and pass `access_log=None` so the server does not write a log line per request on a phone.
  Bind to port `0` and read the port back off `site.name`.
- **The default timeouts are desktop-sized.** `ClientTimeout(total=300, sock_connect=30)` —
  five minutes before a request gives up, which on a phone that just lost its network means a
  spinner nobody will wait out. Pass your own
  [`ClientTimeout`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientTimeout)
  per session or per request.
- **Cookies from a numeric host are dropped silently.**
  [`CookieJar`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.CookieJar)
  ignores `Set-Cookie` from an IP-address host unless it was built with `unsafe=True`, so a
  session against your own `127.0.0.1` server keeps nothing: measured, 0 cookies with the
  default and 1 with `unsafe=True`, no warning either way.
- **There is no `aiodns` on mobile and nothing to install.** `AsyncResolver` needs `pycares`,
  which publishes no `py3-none-any` wheel on PyPI and has nothing on this index, so
  `ThreadedResolver` is the resolver here. That is a working DNS path rather than a degraded
  one — see [Threading](#threading).
- **`import aiohttp` does real work.** It builds two `SSLContext`s (the verified and
  unverified defaults, both at module level in `connector.py`), pulls in `ssl`, and loads all
  four native extensions. Nothing to configure — but it is work done whether or not the app
  ever makes a request, so keep the import out of whatever the first frame waits on.
- **Size.** Small, and almost all of it is the four extensions:

  | slice | wheel | unpacked | the four `.so` |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 481 KB | 1.63 MB | 617 KB |
  | Android armeabi-v7a | 454 KB | 1.44 MB | 420 KB |
  | iOS arm64 (device) | 500 KB | 1.92 MB | 907 KB |

  The seven pure-Python dependencies add another 188 KB of wheels, 639 KB unpacked, the same on
  every slice. What actually lands, read out of the
  [`loopback-api`](examples/loopback-api) example's own APK: 68 `aiohttp/` entries in
  `sitepackages.zip` — 55 `.pyc` totalling 1,467,731 B, four
  `.soref` markers, and 3,007 B of `.pxi` and `.hash` files — plus 8 `dist-info` entries and
  the native code in
  `lib/<abi>/`, at 616,832 B on arm64-v8a, 665,440 B on x86_64 and 420,332 B on armeabi-v7a.
  Flet's default
  [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) had taken the
  46,466 B of `.pyx`, `.pxd` and `py.typed` with it, exactly as its glob list predicts, and left
  the `.pxi` and `.hash` files, which are not on that list — the same on the iOS side, where
  they survive in the app bundle's `site-packages`. The one duplicate worth knowing
  about survives as bytecode: `reader_py.pyc` at 21,536 B beside an all-but-identical
  `reader_c.pyc` at 21,535 B. Nothing here is worth trimming by hand.

## Build notes (maintainers)

The recipe is six lines of `meta.yaml` — name, version, build number — with no patches, no
`requirements`, no `script_env` and no `test.requires`, and that is the fact worth recording,
because it is not luck. The sdist ships the Cython output as `.c` (`_http_parser.c`,
`_http_writer.c`, `_websocket/mask.c`, `_websocket/reader_c.c`, `_find_header.c`), so nothing
needs Cython at build time; llhttp is vendored under `vendor/llhttp` and compiled straight
into `_http_parser`, so there is no `flet-lib*` recipe underneath this one; and
`build-system.requires` is only `pkgconfig` and `setuptools`. The day this recipe needs a
patch, suspect the toolchain or an upstream restructuring before reaching for one.

One property makes a green build worth more here than in most recipes: **`setup.py` has no
`BuildFailed` fallback.** `ext_modules` is set unconditionally unless `AIOHTTP_NO_EXTENSIONS`
is in the environment (or the interpreter is not CPython, which cannot happen here), and
`meta.yaml` sets no `script_env` at all, so a compile failure fails
the build rather than quietly producing a pure-Python wheel. The corollary is that
`AIOHTTP_NO_EXTENSIONS` must never appear in this recipe.

**The tests are the weak point and should be fixed before the next bump.**
`tests/test_aiohttp.py` is two functions, neither with a docstring, and `test_basic` does
`session.get("http://python.org")` — which 301-redirects into HTTPS, so it silently depends on
internet access *and* on a device trust store this README says is absent. It is not evidence
that TLS works on device, and there is no sign it has ever run on one at this version: aiohttp
is not in `SMOKE_TEST_PACKAGES`, and no commit has ever touched this recipe on its own — the
version came in with `e4e0d28`, a repo-wide bump of every recipe, and the only commit after it
is a repo-wide normalisation. What that file should be is a `127.0.0.1` `AppRunner` round trip
plus an assertion on all four accelerators — today only the parser is checked, so
`_http_writer`, `_websocket/mask` and `_websocket/reader_c` could each regress to pure Python
with CI still green, which is exactly the failure this README warns app authors about. Note
that `_websocket/reader_c` needs the loader check described in
[Things to know](#things-to-know), not a `__module__` comparison, or the test will pass over
the very regression it is meant to catch.

On a version bump, and everything above this section is a claim a bump can falsify without
the build failing:

- **The accelerator set and the private names three of the four checks hang off.**
  `HttpRequestParserPy`, `_py_serialize_headers` and `_websocket_mask_python` are private, and
  the gates that select them are keyed on `helpers.NO_EXTENSIONS`. A rename breaks the
  example's header line, and the count of `.so` in the wheel is the independent check: it must
  be four, and they must be the same four upstream's own wheel of that version carries. The
  fourth check, `ws-reader`, hangs off `ExtensionFileLoader` instead, because upstream ships a
  pure-Python `reader_c.py` under the same module name as the extension. Re-verify by hiding
  each `.so` in turn and confirming the header drops to `3/4` for that one — a `4/4` with a
  hidden extension is the bug this replaced. If upstream ever stops shipping `reader_c.py`, the
  simpler `__module__` comparison becomes valid again, but there is no reason to go back to it.
- **`METADATA` against upstream's.** 78 files are present in the Android wheel, the iOS wheel
  and upstream's manylinux wheel alike, and 76 of them are byte-identical across all three —
  only `RECORD` and `WHEEL` differ, and `METADATA` matches at md5
  `91b8d81c9cab6b2d4919655568a27bd5`. The `speedups` extra and its `sys_platform` markers are
  *upstream's*, not this recipe's, and the reason they do not protect a mobile build is
  serious_python's, so the [Install](#install) table can change from either side. Re-run both
  resolves rather than editing the wording.
- **The dependency resolution, re-run rather than assumed.** Which of `multidict`, `yarl`,
  `frozenlist` and `propcache` are pure Python on device is a fact about *their* release
  history, not about aiohttp: any of them could publish mobile wheels, and yarl's compiled
  build on this index is only reachable by pin because a newer pure release outranks it.
  Re-measure with `pip install --dry-run --report` under serious_python's cross-compile
  `sitecustomize.py`, which is what produced the figures above.
- **Which index a bare `aiohttp` actually resolves to, per slice.** The table in
  [Install](#install) is a race between upstream's own mobile wheels and this recipe, and it moves
  whenever either side releases — including in this recipe's favour, which would make that whole
  paragraph unnecessary. It is also the question of whether the recipe is still needed at all: the
  day upstream covers armeabi-v7a and 3.12 as well, the only thing this index adds is a slice
  nobody asked for. Re-run one `pip download --only-binary :all: --platform … --extra-index-url
  https://pypi.flet.dev aiohttp` per target and read the filename that comes back.
- **The zstd story, which is about Flet's Python build and not about aiohttp.** The
  `sys.version_info >= (3, 14)` branch in `compression_utils.py` and the `_zstd` extension in
  both runtimes are separate moving parts; re-read the first from the sdist and the second from
  the python-build release that flet-cli pins.
- **The linkage lists on both platforms.** Android `DT_NEEDED` is `libm`, `libpython3.<minor>`,
  `libdl`, `libc` on all four extensions; iOS is `MH_DYLIB`/`NOUNDEFS` with only
  `Python.framework` and `libSystem`. Anything new in either list is a runtime dependency
  [Install](#install) does not mention — and an iOS extension that came back as `MH_BUNDLE`
  would fail at link time rather than at import.
- **The measured numbers**: the per-slice wheel sizes, the 617 KB / 907 KB native totals, the
  188 KB / 639 KB of pure dependencies, the multidict benchmark, and the zstd and gzip ratios
  quoted in the example. Re-measure rather than scaling. The relocated `lib/<abi>/` names, the
  `.soref` and `.fwork` paths and every figure about what survives cleanup were read out of the
  example's own built APK and simulator bundle rather than reasoned about, so rebuilding it is
  the way to refresh them — and note that serious_python's `junkFilesMobile` glob list, which
  decides the cleanup half, lives outside this repo (`**.pxd` and `**.pyx` are on it today;
  `**.pxi` and `**.hash` are not).
- **The error and header strings quoted above** — the `ContentEncodingError` text, the
  `run_app` `ValueError`, the `Accept-Encoding` values. All upstream's wording, all subject to
  being reworded.
