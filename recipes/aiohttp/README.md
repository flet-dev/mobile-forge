# aiohttp

[`aiohttp`](https://docs.aiohttp.org/en/stable/) is asyncio's HTTP stack: a client with
connection pooling, streaming bodies, transparent decompression and WebSockets, and a
complete [web server](https://docs.aiohttp.org/en/stable/web_quickstart.html) in the same
package. On a phone the client half is the obvious draw, and it fits Flet unusually well — a
Flet session already *is* an event loop, so a request is a coroutine on it rather than a
thread you have to manage, and concurrency comes from the loop instead of from a pool you
size. The server half is the less obvious one: an in-process HTTP and WebSocket API is how
you let a [`WebView`](https://flet.dev/docs/controls/webview/), the Flutter side or a test
harness talk to your Python over a protocol they already speak, instead of an ad-hoc bridge.

The whole Python layer of these wheels is byte-identical to upstream's own wheel of the same
version, so [upstream's documentation](https://docs.aiohttp.org/en/stable/) applies unchanged.
What is worth knowing is what the *platform* does not give aiohttp: no CA bundle, no C
resolver, and pure-Python versions of several of its dependencies. All three are below.

## Install

Add aiohttp to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "aiohttp",
]
```

**A bare `aiohttp` will not always be the wheel from this index — upstream publishes mobile
wheels of its own now.** `flet build` installs with `pip install --upgrade --only-binary :all:
--extra-index-url https://pypi.flet.dev`, so pip sees PyPI *and* this index and takes the
highest version it can use. Upstream's 3.14.3 covers Python 3.13 and 3.14 only, and on Android
only arm64-v8a and x86_64 — tagged `android_21_*` on cp313 and `android_24_*` on cp314, both of
which satisfy Flet's API-24 target — with no armeabi-v7a. Measured, one resolve for each of the
eighteen slice-and-minor combinations:

| slice | Python 3.12 | Python 3.13 and 3.14 |
| --- | --- | --- |
| Android arm64-v8a, x86_64 | this index | upstream 3.14.3 |
| Android armeabi-v7a | this index | this index |
| iOS device and both simulators | this index | upstream 3.14.3 |

So a 3.13 or 3.14 Android build carries **two different aiohttp versions across its ABIs**, and
nothing on screen says so. Neither wheel is wrong — but every figure on this page was measured
on the one from this index, so pin `aiohttp` to the version in [`meta.yaml`](meta.yaml) if you
want the wheel this page describes on every slice, as the
[`loopback-api`](examples/loopback-api) example's `pyproject.toml` does.

**`aiohttp[speedups]` fails the build.** Upstream guards that extra with
`sys_platform != "android" and sys_platform != "ios"`, which looks like protection and is not:
`flet build` cross-installs by running pip on the *build host* with the wheel platform tag
patched, so `sys.platform` is still `darwin` (or `linux` on CI) when markers are evaluated and
the guard comes out `True`. Everything in the extra is requested for real. Which of the two
blockers pip reports depends on the interpreter it runs under, so treat these as two faces of
one failure rather than a per-version rule:

| Python | what you get |
| --- | --- |
| 3.14 | `ResolutionImpossible` — every `aiodns` release needs `pycares`, and "some packages in these conflicts have no matching distributions available for your environment: `pycares`" |
| 3.12 | `Could not find a version that satisfies the requirement backports.zstd` — it gets as far as downloading a mobile `Brotli` first |

Ask for what you actually want instead: plain `aiohttp`, plus [`Brotli`](../brotli) by name if
you need `br`. zstd needs nothing at all on Python 3.14.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`loopback-api`](examples/loopback-api) — an aiohttp server and aiohttp's own client
  talking to each other on `127.0.0.1`, six checks deep.

## Usage in a Flet app

Write an `async def main`, build the session inside a handler, and put the decoded body into a
control:

```python
CONTEXT = ssl.create_default_context(cafile=certifi.where())
TIMEOUT = aiohttp.ClientTimeout(total=15)


async def main(page: ft.Page):
    async def load(e):
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(URL, ssl=CONTEXT) as response:
                payload = await response.json()
        feed.controls = [ft.Text(item["title"]) for item in payload]
        page.update()

    page.add(ft.Button("Load", on_click=load), feed := ft.Column())
```

Both arguments a mobile app should not leave to the defaults are in there:
[`ssl=`](https://docs.aiohttp.org/en/stable/client_advanced.html#ssl-control-for-tcp-sockets),
because the device has no trust store for the default context to find, and
[`ClientTimeout`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientTimeout),
because aiohttp's own default is five minutes. [Things to know](#things-to-know) has the
symptom for each.

### Storage

aiohttp chooses no path of its own — the one file it opens unasked is at the end of this
section. The places *you* hand it a path belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups:

```python
jar = aiohttp.CookieJar()
cookies = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "cookies.json")
if os.path.exists(cookies):
    jar.load(cookies)
...
jar.save(cookies)
```

[`CookieJar.save`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.CookieJar.save)
writes JSON and creates the file mode `0600`, the right default for something that usually holds
a session token;
[`load`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.CookieJar.load) reads
that back and falls back to the legacy pickle format for files written by older releases.
Server-side,
[`web.FileResponse`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.FileResponse)
and static routes serve whatever you point them at, so that is your directory choice too.

From Flet 0.86.0 `FLET_APP_STORAGE_DATA` is also the process working directory on device, so a
bare relative filename lands there; spelling it out costs one line and behaves the same on
desktop. Do not keep a cookie jar in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches).

The exception is server-side only: `Request.post()` spools each multipart field carrying a
`filename` into a `tempfile.TemporaryFile`, in whatever directory the stdlib `tempfile` module
picks rather than in Flet's app storage. TemporaryFile is unlinked as soon as it is opened, so
nothing accumulates, but the bytes do land on the device's filesystem on the way through. The
ceiling is `client_max_size`, which `web.Application` defaults to 1 MiB — raise it
deliberately, and reach for `request.multipart()` instead if you would rather stream an upload
straight past disk.

### Threading

**aiohttp is asyncio, so on Flet the answer is almost always "no thread at all".** Flet awaits
an `async def main(page)` directly inside the session's event loop, and awaits it to completion
before its first post-`main` update. So:

- **Write `async def main(page)` and use aiohttp straight from it.** No `asyncio.run`, no loop
  of your own.
- **Start background work with
  [`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task), never
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread).**
  `run_task` schedules the coroutine on the session's loop and re-raises what it caught, so a
  failure reaches Flet's error handling; `run_thread` hands work to an executor, never
  retrieves the future, and swallows the exception whole. A thread also has no running loop, so
  aiohttp could not be used in one without standing up a second loop inside it.
- **End every `run_task` body with an explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).** Flet's auto-update
  fires only around event handlers and around `main`, and a `run_task` body is outside both, so
  the UI will not refresh on its own.
- **Put the re-entrancy guard in the handler, not in the `run_task` body.** `run_task`
  schedules and returns, so a `button.disabled = True` set inside the coroutine has not happened
  yet when the handler returns and Flet pushes the control's state. A second tap in that window
  is accepted, and two overlapping runs mutate the same controls. Set and test the flag in the
  handler, where it is synchronous and the post-handler auto-update carries it.
- **Return from `main` once setup is done.** An `async def main` that parks —
  `await asyncio.Event().wait()` to keep a server alive, say — never lets Flet reach the update
  that follows `main`, and the first render is stranded. Set the
  [runner](https://docs.aiohttp.org/en/stable/web_advanced.html#application-runners) up and
  return; it goes on serving from the same loop.
- **Never build a
  [`ClientSession`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientSession)
  at module scope.** Its constructor calls `asyncio.get_running_loop()`, so at import it raises
  `RuntimeError: no running event loop` — before any UI exists, which reads like a broken build
  rather than a misplaced line. Build it inside `main` or inside a `run_task` coroutine, as
  `async with aiohttp.ClientSession(...) as session:`.

One thread does get used behind your back: with no `aiodns` installed the resolver is aiohttp's
`ThreadedResolver`, which calls `loop.getaddrinfo` — asyncio's own wrapper that runs the
blocking stdlib lookup in the loop's default executor. A slow DNS server therefore delays that
one request without blocking the loop. A numeric host skips the path entirely:
`TCPConnector._resolve_host` short-circuits an IP literal before any resolver is consulted,
which is why a `127.0.0.1` client does no name resolution at all.

### Android

**The `INTERNET` permission is already there.** `flet build` starts its
[permission table](https://flet.dev/docs/publish/android/#permissions) from
`{"android.permission.INTERNET": True}` and merges your entries into it, so opening or binding
a socket needs no `pyproject.toml` entry. This is the only platform where the question exists.

**The four accelerators are not where the wheel put them.** Flet relocates every native
extension into the APK's `lib/<abi>/` and leaves a marker behind for its import hook to follow.
The import works; what changes is that a relocated extension's `__file__` is not a path you can
open — on Android it is not set at all. All four are submodules, so none can hit the
`lib<pkg>.so` collision that packages whose `__init__` *is* the extension run into.

**Site-packages is a ZIP here, a directory on iOS.** aiohttp runs out of it as-is: nothing in
the package opens a file at import and `__file__` appears nowhere in it, so there is no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry to write.
It is also why `certifi.where()` takes a temporary-extraction path on Android and returns a
plain filesystem path on iOS.

**OpenSSL was configured with `OPENSSLDIR="/usr/local/ssl"`** (read out of
`libcrypto_python.so`), a path that cannot exist on Android, and there is no `.pem` file
anywhere in the runtime's `stdlib.zip`. See the TLS bullet in
[Things to know](#things-to-know).

**Nothing in the manifest opts into cleartext HTTP.** Read out of the example's own APK,
`AndroidManifest.xml` carries neither `android:usesCleartextTraffic` nor a
`networkSecurityConfig`, so the platform default applies. Python's sockets are not subject to
that policy — which is why the example's client reaches its own server — but the Dart/WebView
side of the bridge this page opens by advertising *is*. Whether a WebView will load
`http://127.0.0.1:<port>` from a Flet app has **not** been tested here; establish it before
designing around it.

### iOS

**The extensions need no fixing up and no preloading.** All four link nothing but Python and
libSystem, so there is no third-party dylib to ship beside them. Each is lifted into a signed
framework of its own and replaced, at the path the wheel put it, by a one-line `.fwork` stub —
the iOS counterpart of Android's relocation, with the same consequence for `__file__`.

**If you check for an accelerator yourself, check the loader class.** A `.fwork` stub imports
through `AppleFrameworkLoader`, a subclass of `importlib.machinery.ExtensionFileLoader`, so one
`isinstance(module.__loader__, ExtensionFileLoader)` test is correct on iOS and Android alike.
That is what makes the check in [Things to know](#things-to-know) portable.

**OpenSSL was configured with `OPENSSLDIR="/etc/ssl"`** here, against Android's
`/usr/local/ssl`. If TLS ever behaves differently between the two platforms, that asymmetry is
where to look first.

### App size

The wheel is approximately 0.45–0.50 MB compressed and 1.4–1.9 MB unpacked per slice, and
almost all of the unpacked bytes are the four compiled accelerators: roughly 0.42 MB on Android
armeabi-v7a, 0.62 MB on Android arm64-v8a and 0.91 MB on iOS arm64. The pure-Python
dependencies add about 0.19 MB of wheels and 0.64 MB unpacked, the same on every slice.
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
worth adding: the default already removes aiohttp's Cython sources, and what it leaves is
kilobytes.

Wheels are published for all three Android ABIs Flet targets and for the iOS device plus both
simulator slices, on Python 3.12, 3.13 and 3.14 — so narrowing
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) is a size
decision rather than a necessity, and armeabi-v7a is a genuine 32-bit build rather than a stub.
On Android an app bundle, split APKs or a narrowed `target_arch` are the levers; packaging and
compression decide what actually reaches the APK.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel — same Python code, same four accelerators — but
three things around it differ, and each hides a mobile failure. `ssl.create_default_context()`
comes back with the operating system's trust store behind it, so an HTTPS call that works under
`flet run` says nothing about the device. `multidict`, `yarl`, `frozenlist` and `propcache`
resolve to their compiled desktop wheels, so desktop timings for a request-heavy screen are
optimistic. And site-packages is a plain directory with real `__file__` paths, where on Android
it is a ZIP with every extension relocated out of it.

Validate on a device or emulator/simulator: one real HTTPS handshake against your own backend,
the first-launch storage path, and — if you rely on the accelerators being live — the loader
check, since a slice that fell back to pure Python returns identical results.

## Things to know

- **Do not assume HTTPS to a public host works — pass a CA bundle explicitly.** aiohttp builds
  its default `SSLContext` at *import* time from `ssl.create_default_context()` with no cert
  file argument, and never mentions `certifi` anywhere in the package. On desktop that context
  has a system trust store behind it; on device nothing in the Python runtime provides one. The
  failure lands at handshake rather than at import, as a verification error that reads like a
  server problem. It needs no new dependency: `certifi` comes in with Flet
  (`flet` → `httpx` → `certifi`) and its `cacert.pem` is present in both a built APK's
  `sitepackages.zip` and the iOS `site-packages` — just nowhere OpenSSL looks. Hand it over with
  `ssl=`, as the snippet at the top of [Usage in a Flet app](#usage-in-a-flet-app) does. This has
  **not** been settled by a handshake on a device here — the evidence is the absence of a bundle
  where OpenSSL would look for one, not an observed failure — so treat `certifi.where()` as the
  cheap way to make the question moot.

- **The default timeouts are desktop-sized.** `ClientTimeout(total=300, sock_connect=30)`: five
  minutes before a request gives up, which on a phone that just lost its network is a spinner
  nobody will wait out. Pass your own
  [`ClientTimeout`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientTimeout)
  per session or per request.

- **What the client asks for depends on the Python version, and it tells you so.**
  `Accept-Encoding` is assembled at import from what is importable: `gzip, deflate, zstd` on
  Python 3.14, `gzip, deflate` on 3.12 and 3.13. The zstd half is free on 3.14 only — aiohttp
  takes it from the stdlib `compression.zstd`, and Flet's mobile runtimes ship the `_zstd`
  extension on both platforms. The decode path was exercised on a desktop 3.14 rather than on a
  device: a server-sent `Content-Encoding: zstd` body came back inflated with no intervention,
  1,735 B on the wire to 24,890 B. On 3.12 and 3.13 aiohttp wants `backports.zstd` instead,
  which is not on this index.

- **`br` is not advertised, and an unsolicited `br` response raises.** `HAS_BROTLI` is false in
  a stock mobile install, so the client never offers `br` — and the decoder in `http_parser.py`
  is gated on the same flag, so a server that sends it anyway gets a `ContentEncodingError` that
  names the fix:

  ```text
  Can not decode content-encoding: brotli (br). Please install `Brotli`
  ```

  Adding [`Brotli`](../brotli) to your dependencies does exactly that, and it resolves on every
  mobile slice, armeabi-v7a included. `Accept-Encoding` then becomes `gzip, deflate, br, zstd`.

- **aiohttp's *server* can only compress with gzip or deflate.** `ContentCoding` has exactly
  three members — `deflate`, `gzip`, `identity` — so a bare
  [`enable_compression()`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.StreamResponse.enable_compression)
  negotiating against a 3.14 client's `gzip, deflate, zstd` picks **deflate**, not zstd. Pass
  `force=web.ContentCoding.gzip` if you want to know which one you got.

- **All four compiled accelerators ship on both platforms, and nothing tells you if one stopped
  working.** The set is `_http_parser` (llhttp 9.4.1, statically vendored), `_http_writer`,
  `_websocket/mask` and `_websocket/reader_c` — the same four upstream's own wheels carry, all
  loaded by a plain `import aiohttp`, none lazy, and `import aiohttp.web` adds no fifth. There
  is no public flag for whether they are live, which is why the
  [`loopback-api`](examples/loopback-api) example prints a `C speedups n/4` line. Three can be
  checked by comparing against the private name the pure-Python twin would be bound to;
  **`_websocket/reader_c` cannot.** The wheel ships `aiohttp/_websocket/reader_c.py` beside the
  extension of the same name, and `reader.py` imports `.reader_c` inside a
  `try/except ImportError` the `.py` satisfies — so an unloadable extension is silently replaced
  by pure Python under the *same* module name, and `WebSocketReader.__module__` still reads
  `aiohttp._websocket.reader_c`. That fallback is not theoretical: a built app carries
  `reader_c.pyc` next to `reader_c.soref` in the APK and next to `reader_c.fwork` in the iOS
  bundle, both about 21.5 KB, so the pure-Python twin is sitting on the device ready to take
  over silently. Measured by hiding each extension in turn, that comparison
  reported `True` for a `reader_c` that was not loaded. Only the loader tells them apart —
  `ExtensionFileLoader` against `SourceFileLoader` or `zipimporter` — which is what the example
  checks, and which works on both platforms for the reason in [iOS](#ios). A slice that fell
  back returns identical results and is not measurably slower: the pure-Python masker is four
  `bytes.translate` calls, and forcing it left the example's WebSocket check at 0.9–1.0 ms
  either way.

- **`multidict`, `yarl`, `frozenlist` and `propcache` are pure Python on device, and
  `multidict` is the one that costs you.** Those four ship C accelerators on desktop and have no
  mobile wheels on PyPI at all, so an `--only-binary :all:` resolve takes their `py3-none-any`
  wheels. `CIMultiDict` then resolves to `multidict._multidict_py` while aiohttp's own four
  accelerators stay live. Measured on a desktop that can run both, 300 loopback round trips took
  40–43 ms with the C `multidict` and `yarl` and 55–62 ms with the pure ones. Pinning
  [`yarl`](../yarl) down to the compiled build on this index *is* possible — a newer pure-Python
  release outranks it on version alone, so take the exact version from [`yarl`](../yarl)'s
  `meta.yaml`, which is the one this index builds — but it made no
  measurable difference in that benchmark, 60–61 ms, and it buys a pin that a future aiohttp
  bump can put in conflict. There is no equivalent option for `multidict`.

- **`web.run_app(...)` cannot be used inside a Flet app at all.** It drives the loop itself, so
  inside Flet's already-running one it dies with a message that says nothing about the actual
  mistake, plus a *Task was destroyed but it is pending* warning and a never-awaited coroutine:

  ```text
  ValueError: The future belongs to a different loop than the one specified as the loop argument
  ```

  Use the
  [runner API](https://docs.aiohttp.org/en/stable/web_advanced.html#application-runners) —
  [`web.AppRunner`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.AppRunner)
  plus [`web.TCPSite`](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.TCPSite)
  — and pass `access_log=None` so the server does not write a log line per request on a phone.
  Bind to port `0` and read the port back off `site.name`.

- **Cookies from a numeric host are dropped silently.**
  [`CookieJar`](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.CookieJar)
  ignores `Set-Cookie` from an IP-address host unless it was built with `unsafe=True`, so a
  session against your own `127.0.0.1` server keeps nothing: measured, 0 cookies with the
  default and 1 with `unsafe=True`, no warning either way.

- **There is no `aiodns` on mobile and nothing to install.** `AsyncResolver` needs `pycares`,
  which publishes no `py3-none-any` wheel on PyPI and has nothing on this index, so
  `ThreadedResolver` is the resolver here. That is a working DNS path rather than a degraded one
  — see [Threading](#threading).

- **`import aiohttp` does real work.** It builds two `SSLContext`s (the verified and unverified
  defaults, both at module level in `connector.py`), pulls in `ssl`, and loads all four native
  extensions. Nothing to configure, but it is work done whether or not the app ever makes a
  request, so keep the import out of whatever the first frame waits on.

## Build notes (maintainers)

### Recipe shape

The recipe is name, version and build number, with no patches, no `requirements`, no
`script_env` and no `test.requires` — and that is the fact worth recording, because it is not
luck. The sdist ships the Cython output as `.c` (`_http_parser.c`, `_http_writer.c`,
`_websocket/mask.c`, `_websocket/reader_c.c`, `_find_header.c`), so nothing needs Cython at
build time; llhttp is vendored under `vendor/llhttp` and compiled straight into `_http_parser`,
so there is no `flet-lib*` recipe underneath this one; and `build-system.requires` is only
`pkgconfig` and `setuptools`. The day this recipe needs a patch, suspect the toolchain or an
upstream restructuring before reaching for one.

One property makes a green build worth more here than in most recipes: **`setup.py` has no
`BuildFailed` fallback.** `ext_modules` is set unconditionally unless `AIOHTTP_NO_EXTENSIONS`
is in the environment, and `meta.yaml` sets no `script_env` at all, so a compile failure fails
the build rather than quietly producing a pure-Python wheel. The corollary is that
`AIOHTTP_NO_EXTENSIONS` must never appear in this recipe.

### Upgrade hazards

**Upstream's own mobile wheels are the live question.** The [Install](#install) table is a race
between them and this recipe, and it moves whenever either side releases — including in this
recipe's favour. It is also the question of whether the recipe is still needed: the day upstream
covers armeabi-v7a and Python 3.12 as well, the only thing this index adds is a slice nobody
asked for.

**Both rows of the [Install](#install) failure table can change from outside this repo.** The
`speedups` extra's `sys_platform` markers are upstream's, and the reason they fail to protect a
mobile build is serious_python's.

**`_websocket/reader_c.py` is what makes the accelerator check subtle.** Upstream ships a
pure-Python module under the same name as the extension, which is why the fourth check hangs off
`ExtensionFileLoader` rather than a `__module__` comparison. If upstream stops shipping it the
simpler comparison becomes valid again — but the loader test keeps working either way.

### Re-verification checklist

- **The accelerator set and the three private names.** `HttpRequestParserPy`,
  `_py_serialize_headers` and `_websocket_mask_python` are private, and the gates selecting them
  are keyed on `helpers.NO_EXTENSIONS`; a rename breaks the example's header line. The count of
  `.so` in the wheel is the independent check: four, and the same four upstream's own wheel of
  that version carries. Re-verify by hiding each `.so` in turn and confirming the header drops
  to `3/4` for that one — a `4/4` with a hidden extension is the bug the loader check replaced.
- **`METADATA` against upstream's.** 78 files are present in the Android wheel, the iOS wheel
  and upstream's manylinux wheel alike, and 76 are byte-identical across all three — only
  `RECORD` and `WHEEL` differ, and `METADATA` matches at md5
  `91b8d81c9cab6b2d4919655568a27bd5`. That identity is what the intro's claim that upstream's
  documentation applies unchanged rests on.
- **Which index a bare `aiohttp` resolves to, per slice.** Re-run one `pip download
  --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev aiohttp` per target
  and read the filename back; do not edit the table from reasoning.
- **The dependency resolution.** Which of `multidict`, `yarl`, `frozenlist` and `propcache` are
  pure Python on device is a fact about *their* release history, not about aiohttp. Re-measure
  with `pip install --dry-run --report` under serious_python's cross-compile `sitecustomize.py`.
- **Zip-safety.** The wheel's whole non-code payload is Cython source text with its `.hash`
  sidecars, two licences and a `py.typed` marker; nothing in the package opens a file at import,
  and `__file__` appears nowhere in it. Confirm both still hold, or [Android](#android)'s "no
  `extract_packages` entry to write" stops being true.
- **The linkage lists.** Android `DT_NEEDED` is `libm`, `libpython3.<minor>`, `libdl`, `libc` on
  all four extensions; iOS is `MH_DYLIB`/`NOUNDEFS` with only `Python.framework` and
  `libSystem`. Anything new is a runtime dependency [Install](#install) does not mention — and
  an iOS extension that came back as `MH_BUNDLE` would fail at link time.
- **The zstd story, which is about Flet's Python build and not about aiohttp.** The
  `sys.version_info >= (3, 14)` branch in `compression_utils.py` and the `_zstd` extension in
  both runtimes are separate moving parts; re-read the first from the sdist and the second from
  the python-build release that flet-cli pins.
- **The measured sizes; re-measure rather than scaling.** The four extensions totalled
  616,832 B on Android arm64-v8a, 665,440 B on x86_64 and 420,332 B on armeabi-v7a, against
  906,944 B on iOS arm64, with `_http_parser` alone 357,104 B against 455,416 B. In the
  example's own APK that sits beside 68 `aiohttp/` entries in `sitepackages.zip` — 55 `.pyc`
  totalling 1,467,731 B, four `.soref` markers and 3,007 B of `.pxi` and `.hash` files — after
  Flet's default [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) took
  46,466 B of `.pyx`, `.pxd` and `py.typed` and left the `.pxi` and `.hash`, which are not on
  its glob list (`junkFilesMobile`, which lives outside this repo). Every figure here, and the
  relocated `lib/<abi>/` names and `.fwork` paths, came out of that build: rebuilding the
  example is how to refresh them.
- **The error and header strings quoted above** — the `ContentEncodingError` text, the
  `run_app` `ValueError`, the `Accept-Encoding` values. All upstream's wording, all subject to
  being reworded.

### Coverage gaps

`tests/test_aiohttp.py` is two functions. `test_basic` does `session.get("http://python.org")`,
which 301-redirects into HTTPS, so it silently depends on internet access *and* on a device
trust store this page says is absent; `test_extension` checks only `_http_parser`, so
`_http_writer`, `_websocket/mask` and `_websocket/reader_c` could each regress to pure Python
with CI still green — exactly the failure this page warns app authors about. There is no sign
the tests have run on a device at this version: aiohttp is not in `SMOKE_TEST_PACKAGES`, and no
commit has touched this recipe on its own.

What that file should be is a `127.0.0.1` `AppRunner` round trip plus an assertion on all four
accelerators, with `_websocket/reader_c` checked through its loader rather than through
`__module__`, or the test passes over the very regression it is meant to catch. Until then,
everything this page says about *running* a client or a server rests on the example app and on
desktop runs, not on device coverage.
