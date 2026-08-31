# curl-cffi fingerprint fan-out

Five browser profiles probe one fingerprinting endpoint at the same time, and the screen
lays the JA4, JA3n, JA3 and HTTP/2 hashes each handshake produced side by side. The band
above them is local and fills in with the radio off: the `libcurl-IMPERSONATE` version
string, whether this build holds fingerprint tables for each target, and the CA bundle
curl-cffi resolved at import.

The probes are the only thing here that leaves the device. They go to
[tls.browserleaks.com](https://tls.browserleaks.com/), a third-party endpoint, because only
the far end of a handshake can report what the ClientHello looked like.

What it demonstrates:

- **What impersonation actually changes.** Five targets, five different ClientHellos, and
  `off` — no impersonation — sends no `User-Agent` at all, which is the shape a filter looks
  for when it decides a caller is a script. Setting
  [`impersonate`](https://curl-cffi.readthedocs.io/en/latest/impersonate/_index.html) is the
  whole of it.
- **The half you cannot see locally.** JA3 and JA4 hash the ClientHello — cipher suites,
  extensions, curves, ALPN — so no socket the app opens itself can report them. That is why
  the rows need the network and the header does not, and why a matching `User-Agent` alone
  does not make a client look like Chrome.
- **Press "Probe all targets" again and read the tinted values**, which are the ones that
  moved since the previous run. For both Chrome targets that is `ja3`, every time: Chrome has
  [permuted its ClientHello extensions since version 110](https://curl-cffi.readthedocs.io/en/latest/faq.html#why-does-the-ja3-fingerprints-change-for-chrome-110-impersonation)
  and curl-impersonate reproduces that, so the raw hash is different on every connection while
  `ja3n` (extensions sorted) and `ja4` (sorted by construction) hold still. Safari, Firefox and
  `off` do not move at all. Pinning a client by raw JA3 is pinning noise.
- **`chrome131_android` moves its `ja4` and `ja3n` too, now and then.** Roughly one handshake
  in five carried one extra TLS extension — `t13d1517h2_…` instead of `t13d1516h2_…` — over 22
  handshakes, sequential and concurrent alike. No mechanism is claimed for it here; it is
  another reason not to key anything off a single fingerprint, and it is why an occasional
  tint on that row is not a bug in the app.
- **The `h2` line does not separate what the TLS lines do.** `chrome150`,
  `chrome131_android` and `off` all came back with the same Akamai HTTP/2 hash. Two clients
  can share an HTTP/2 fingerprint and be nothing alike on the wire.
- **The fan-out**, which is the point for anything that queries several endpoints at once. One
  `asyncio.gather` over five tasks, and one
  [`AsyncSession`](https://curl-cffi.readthedocs.io/en/latest/asyncio.html) per
  target rather than one shared: a session pools connections, and a pooled connection is a
  handshake that already happened, so sharing one would let an earlier target answer for a
  later one. The footer prints the wall clock against the sum of the five, so the overlap is a
  number rather than a claim — 886 ms against 3,208 ms, 3.6x, on an Android emulator.
- **Async on Flet's own loop.**
  [`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task), not
  `run_thread`: `AsyncSession` drives libcurl through the running loop's readers and writers,
  a worker thread has no loop to give it, and `run_thread` discards whatever its worker
  raises. The button is disabled in the handler rather than inside the coroutine, because
  `run_task` only *schedules* — a `disabled` set inside the task has not happened when the
  handler returns and Flet pushes the button's state, and a second tap in that window queues a
  second fan-out into the same five rows. The task ends in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a task needs, since
  auto-update only fires around event handlers and around `main`.
- **With no network it still says something true.** Each probe is wrapped on its own, so an
  unreachable endpoint is one red row reading `DNSError: … curl: (6) Could not resolve host …`
  and never a crash or a blank screen. `timeout=15` is passed explicitly, because curl-cffi's
  own default is 30 s and a phone that just lost signal spends all of it spinning.

The CA line is worth reading on both. curl-cffi resolves its bundle once, at
`import curl_cffi`: `SSL_CERT_FILE` / `CURL_CA_BUNDLE` / `REQUESTS_CA_BUNDLE` first, then
OpenSSL's compiled-in path, then [certifi](https://github.com/certifi/python-certifi). A
desktop `flet run` reaches the second and reports `openssl default path`; on device the first
already wins, because `flet build` generates startup code that exports `SSL_CERT_FILE` and
`REQUESTS_CA_BUNDLE` pointing at certifi's bundle. Either way the device trusts certifi's roots
and nothing else — but the step differs, which is why the app prints the winner rather than
asserting one.

`[tool.flet.android] target_arch = ["arm64-v8a", "x86_64"]` is required: no `armeabi-v7a`
wheel exists, and without it the APK build fails resolving that ABI.

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

The line to read first on device is `fingerprint tables 4/4`. It answers offline, and it is
the one thing no desktop run can establish: that the fingerprint tables inside the static
curl-impersonate archive survived the cross-compile and linked into the wheel for that
platform. See the [recipe README](../../README.md) for the rest.
