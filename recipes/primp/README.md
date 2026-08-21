# primp

[`primp`](https://github.com/deedy5/primp) is an HTTP client written in Rust that can pass
itself off as a real browser. It sends the TLS handshake, HTTP/2 settings and header block of
Chrome, Firefox, Safari, Edge or Opera, so a server that fingerprints its callers — by
[JA3/JA4](https://github.com/FoxIO-LLC/ja4), by HTTP/2 frame order, by the shape of the header
set — sees a browser instead of a Python HTTP library. Reach for it in a Flet app when an API
or page you need answers an ordinary client with a challenge page, a 403 or a silent block.

The API is close to `requests`: build a `primp.Client`, call `get`/`post`/`request` on it, and
read `status_code`, `headers`, `content`, `text` or `json()` off the response.

## Install

Add primp to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "primp",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`impersonate-probe`](examples/impersonate-probe) — shows the request head each impersonation
  target produces, and the JA3/JA4 hashes a remote endpoint computes from the handshake.

## Usage in a Flet app

Build one client, give it a profile, and keep it:

```python
import primp

client = primp.Client(impersonate="chrome_148", impersonate_os="android", timeout=15)

response = client.get("https://api.example.com/items")
response.raise_for_status()
items = response.json()
```

`primp.get(url, ...)` and its siblings exist as well, but each call constructs a client, which
throws away the connection pool, the cookie jar and the TLS configuration that make the second
request fast and the disguise consistent. Construction is also where the one-off cost sits: the
first client in the process assembles the root certificate store, and that cost is
machine-dependent enough that the number matters less than the shape: measured twice on
different desktops it took 100 ms and 176 ms, while every client after it was built in about a
millisecond. Build one client and keep it.

### Storage

Responses arrive in memory: `response.content` is `bytes` and `response.text` is `str`. Put
what the user expects to keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
and stream anything large rather than holding it whole:

```python
data_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
with open(os.path.join(data_dir, "catalog.json"), "wb") as handle:
    for chunk in client.get(url, stream=True).iter_bytes():
        handle.write(chunk)
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you would happily re-download and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for a body you are about to parse and discard.

Cookies are the one piece of state that looks persistent and is not. A client keeps a cookie
jar (`cookie_store=True` by default), and that jar dies with the client. To carry a session
across launches, read it out with `client.get_cookies(url)`, keep the dictionary in
[`page.shared_preferences`](https://flet.dev/docs/services/sharedpreferences/) or a file
under `FLET_APP_STORAGE_DATA`, and put it back with `client.set_cookies(url, cookies)` on the
next run.

### Threading

primp releases the GIL for the whole of a request, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) genuinely
keeps the UI moving while a response is outstanding: a pure-Python counter kept running at its
full idle rate throughout a two-second request. One client is also safe to use from several
threads at once, and the requests really do overlap — four concurrent `get` calls through a
single client against an endpoint that sleeps one second returned in 1.00 s. Both figures were
measured on desktop. So share the client, catch exceptions inside the worker, and finish with
an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

For an async Flet app, `primp.AsyncClient` has the same constructor and awaitable versions of
the same methods.

### Impersonation

Two arguments describe the disguise. `impersonate` names a browser — a versioned target such
as `chrome_148` or `safari_26.3`, a bare family name such as `chrome`, or `random`.
`impersonate_os` names the platform it should claim: `android`, `ios`, `macos`, `windows`,
`linux` or `random`. [Upstream's
table](https://github.com/deedy5/primp#browser-profiles) is the only complete list of the
versioned names.

**Name a version, name an OS, and never pass `impersonate_os` on its own.** A bare family name
is not the newest release primp knows: it draws one of that family's versions per client, and
twelve clients built with `impersonate="chrome"` came back spread across Chrome 144, 145, 146,
147 and 148. Leaving `impersonate_os` out has the same shape — primp draws an OS at random for
each client and sticks with it, so the same profile can present as Chrome on macOS in one part
of your app and Chrome on an iPhone in another, exactly the inconsistency fingerprinting looks
for. Passed alone it does not merely relabel the platform: primp picks a browser too, so an
undisguised client takes neither argument.

**An OS the profile has no build for is ignored without a word.** Ask for `safari_26.3` on
`android`, `windows` or `linux` and every one of them produces the macOS Safari
`User-Agent` — nothing is logged, and `client.impersonate_os` still reports the string you
passed. Only `ios` and `macos` move it. Check the pairing on the wire rather than trusting
that the argument took effect.

Adding your own headers is where a good disguise usually gets spoiled — not because primp
discards the browser's block, which it never does, but because of where yours lands in it. A
`headers=` argument on the request goes in front of everything, ahead of `accept`; the same
argument on the constructor splits the block open just after `accept`; and
`client.headers_update({...})` appends to the end, which leaves the browser's own sequence
intact and is the one to reach for. Naming a header the profile already sets never duplicates
it, but which value survives depends on the route you took: the request argument wins and drags
the header to the front, `headers_update` wins in place, and the constructor argument loses —
an `Accept-Language` passed to `primp.Client(...)` is dropped for the profile's own without a
word. Send the credentials and content headers your API needs, and leave the rest alone.

### Name resolution

Ordinary requests from this wheel resolve names through the platform's `getaddrinfo`, on both
Android and iOS. Pass `dns_resolver` to choose something else: a bare address or `dns://` for
plain DNS on port 53, `dot://1.1.1.1` for DNS-over-TLS, `doh://cloudflare-dns.com/dns-query`
for DNS-over-HTTPS, `"system"` for the platform resolver by name, or a list of those as a
fallback chain, tried in order.

That default is the fix for [flet-dev/flet#6603](https://github.com/flet-dev/flet/issues/6603),
where the other resolver primp carries went looking for Android's DNS settings through a Rust
global a Flet app never initialises and aborted the process below Python, with nothing to
catch. Nothing here reaches that path — the DoH, DoT and plain resolvers bootstrap through
`getaddrinfo` as well.

### App size

Expect approximately 4.4–5.2 MB compressed and 9.5–14.4 MB unpacked per architecture. That is
one Rust extension module and nothing else, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing to
remove.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These are payload figures, not the exact amount added to
the finished APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's wheel, and it differs from the mobile one in two ways that
both look like "works on my laptop". It resolves names through Hickory rather than
`getaddrinfo`, so a VPN, a split-horizon corporate zone or the machine's own host configuration
can resolve a name one way there and another on the phone. And it merges the operating
system's trust store into primp's own — a macOS run loaded 159 certificates out of the keychain
— which the mobile wheels do not do, so an HTTPS endpoint whose chain depends on a locally
installed root succeeds on the laptop and fails on the device. Test both on a device.

## Things to know

- **On device, the trust anchors are only the ones compiled into the wheel.** primp's default
  store is a baked-in set (`ISRG Root X1`, `DigiCert Global Root G2`, `GlobalSign Root CA` and
  the rest are literal strings in the binary) plus whatever the platform hands over — and on
  mobile it hands over nothing: the lookup goes to `/etc/ssl/certs`, which Android does not
  have, and the iOS binary links no Security framework, so the keychain is never opened. A
  corporate root, or an intercepting debug proxy such as mitmproxy, therefore fails with a
  certificate error on a device where the browser is perfectly happy. Add yours to the app
  instead of installing it on the device: `primp.Client(ca_cert_file="/path/to/roots.pem")`
  *adds* to the built-in set rather than replacing it, and `PRIMP_CA_BUNDLE`, `SSL_CERT_FILE`
  and `CURL_CA_BUNDLE` are read in that order when the argument is absent.

- **A Rust panic ends the process.** The extension is built with `panic = "abort"`, so a fault
  below the Python layer is an immediate `SIGABRT` — no exception, no traceback, nothing for
  `try`/`except` to see. Ordinary failures are not like this: a refused connection, a malformed
  URL or a timeout raises `primp.ConnectError`, `primp.BuilderError` or `primp.TimeoutError`.
  Catch their common base, `primp.PrimpError`, around every request — and note that
  `primp.TimeoutError` is its own class rather than a subclass of the builtin of the same name,
  so an `except TimeoutError:` written against the builtin catches nothing. An abort is a bug
  worth reporting, not a case to handle.

- **An unknown `impersonate` name is not an error.** primp emits a `WARNING` on the
  `primp.impersonate` logger and silently substitutes a random profile, so a typo leaves you
  fingerprinted as some other browser entirely — and it warns only once per process, so a
  second bad name anywhere in the app is completely silent. `client.impersonate` echoes back
  the string you passed, valid or not, so it is not a check either.

- **HTML can come back as text.** `response.text_markdown`, `text_plain` and `text_rich`
  convert an HTML body on the device, which is often all you need to put a fetched page into a
  [`ft.Text`](https://flet.dev/docs/controls/text/) without adding a parser to the app.

## Build notes (maintainers)

### Recipe shape

A plain sdist build with one patch, whose preamble owns the explanation of what it changes.

The alternative was dropping `hickory-dns` from the `primp` feature list in
`crates/primp-python/Cargo.toml`, which removes the Android abort just as effectively. It was
rejected because primp's DoH, DoT and plain-DNS resolver types are gated on that same feature:
removing it would delete `dns_resolver` support from the Python API, a visible capability loss
traded for an unreachable default.

### Upgrade hazards

- The patch edits the DNS branch of `configure_client_builder` and names
  `primp::dns::gai::GaiResolver`. A release that reorganises `crates/primp-reqwest/src/dns` or
  the builder will not apply it, and a silently failed patch produces a wheel that aborts on
  the first Android request while every import-only test still passes.
- The impersonation targets are a hand-written match arm list, and releases add and retire
  names. Anything on this page or in the example that names a profile has to be rechecked
  against it, and an obsolete name degrades to a random profile rather than an error. The same
  goes for which profile/OS pairings are real: the unsupported ones fall back silently, so a
  release that adds a Safari-on-Android build changes what this page says without any error to
  notice.
- The bundled trust anchors move with the dependency tree. A bump can change which CAs the
  app trusts without any recipe change.

### Re-verification checklist

- **A real request on device, both platforms.** An import-and-construct test passes even when
  the first request would abort the process; that is how the original crash reached users.
  Keep a test in `tests/` that performs an actual HTTPS request and tolerates only a
  Python-level failure.
- **No reachable path to Hickory's system configuration.** `HickoryDnsResolver` should be
  constructed only in the builder branch the patch pre-empts, and the DoH, DoT and plain
  resolvers should still bootstrap through `GaiResolver` rather than reading system config.
- **iOS file type.** The extension must be `MH_DYLIB`.
- **GIL behaviour.** The threading advice rests on the binding wrapping blocking work in
  `py.detach`; confirm that before repeating it.
- **Trust anchors.** The default store has two sources — the compiled-in roots and a native
  lookup — and the consumer claim rests on the native one finding nothing on device. Re-read
  which roots are compiled in, and confirm the native lookup still probes only paths that
  neither platform has (no Android `cacerts` path, no Security-framework symbols in the iOS
  binary) before repeating the CA claim.
- **Size.** Re-measure across every published slice, not one: the unpacked figure varies by
  Python version as well as architecture, and the cp314 Android wheels are the largest by
  roughly a megabyte. Sum the file bytes rather than reading `du`, which answers in binary
  units.

### Coverage gaps

The device tests cover the import, the exception hierarchy, and one HTTPS GET that must not
abort. They do not exercise any impersonation profile, `AsyncClient`, streaming responses,
cookie round-trips, SOCKS or HTTP proxies, the DoH/DoT/plain resolvers, or a custom CA bundle.
What this page says about those was read from the sdist source or the built wheel, or measured
on desktop; no device test protects it.
