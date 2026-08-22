# grpcio

[`grpcio`](https://grpc.io/docs/languages/python/) is Google's RPC framework: HTTP/2
transport, streaming in either direction or both, deadlines, status codes, metadata and
per-call compression, all driven by a large C core that this wheel wraps in a single Cython
extension. The reason to want it on a phone is narrow and decisive — the backend already
speaks gRPC, and the alternative is standing up a REST gateway in front of it.

The Python layer here is byte-identical to upstream's own wheel of the same version, so
[upstream's documentation](https://grpc.github.io/grpc/python/) applies unchanged, bar one TLS
API that Android's build cannot support (see [Android](#android)). Everything else worth
knowing is about the extension: how big it is, what it links, where it gets its trust store,
and how it resolves names.

Be warned about the first of those before you go further. Per architecture this is roughly
14–20 MB of native code on Android and about 74 MB on iOS, which makes it by a wide margin the
heaviest package on this index that an app would add for networking. If your backend can be
reached any other way, that is a real argument for reaching it that way.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "grpcio",
]
```

**Ask for `grpcio`, never `grpcio[protobuf]`.** That extra requires `grpcio-tools`, which
bundles protoc — a host binary — and is not on this index, so the build stops at dependency
resolution. [Schemas and codegen](#schemas-and-codegen) covers the three ways to get message
types onto a device without it.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`loopback-rpc`](examples/loopback-rpc) — a gRPC server and grpc's own client on
  `127.0.0.1` with no generated stubs, and a byte counter on the wire between them.

## Usage in a Flet app

A channel, a call, and the answer in a [`ft.Text`](https://flet.dev/docs/controls/text/). The
serialiser pair is the identity function, which is all gRPC requires when the message is
already `bytes`:

```python
import flet as ft
import grpc


def raw(data):
    """Serialise and deserialise bytes as themselves — no .proto, no protoc."""
    return data


CHANNEL = grpc.insecure_channel("10.0.2.2:50051")
DIGEST = CHANNEL.unary_unary(
    "/forge.Echo/Digest", request_serializer=raw, response_deserializer=raw
)


def main(page: ft.Page):
    answer = ft.Text()

    def call():
        try:
            answer.value = DIGEST(b"ping", timeout=5).decode()
        except grpc.RpcError as error:
            answer.value = f"{error.code().name}: {error.details()}"
        page.update()

    page.add(answer, ft.Button("Call", on_click=lambda e: page.run_thread(call)))
```

Four details in that snippet are load-bearing rather than stylistic: the channel lives at
module scope so nothing collects it, `timeout=` is passed explicitly, `grpc.RpcError` is
caught by name, and the worker ends with `page.update()`. [Threading](#threading) and
[Things to know](#things-to-know) say what each one costs when it is left out.

### Storage

grpcio picks no path of its own and writes nothing. The only file it opens unasked is its own
CA bundle, which lives inside the package rather than on the filesystem (see the trust-store
bullet in [Things to know](#things-to-know)).

The one path you might hand it is a replacement for that bundle, through
`GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` — a `.pem` you ship or fetch, which belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups. Not
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
(the OS may purge it under storage pressure) or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
(may vanish between launches): a trust store that disappears fails at handshake time, which
reads like a server problem.

### Threading

**The blocking API releases the GIL for the whole of a call**, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is the
right home for it and the UI stays live while a call is in flight. gRPC's sync API is
genuinely synchronous — a C core doing the work with the GIL dropped, not an asyncio library
being driven from a thread. Measured on desktop against a one-second server-side wait: a
Python canary thread ran at 37.9 M ticks/s during the call and 38.3 M/s during a control
`time.sleep(1.0)`, against 14.5 M/s while a pure-Python busy loop held the GIL.

Two things follow:

- **Wrap the worker body in `try/except grpc.RpcError` — and a bare `except Exception` —
  and render the failure.** `run_thread` submits to an executor and never retrieves the
  future, so anything the worker raises vanishes: no crash screen, no log record, nothing in
  `console.log`. `RpcError` is the one exception class a networking app raises constantly, so
  this is not a theoretical tidy-up.
- **End the worker with an explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).** Flet's
  auto-update fires around event handlers and around `main`, not inside a thread.

**gRPC's C core starts its own thread pool on the first channel or server, not at import.**
Measured on a 10-logical-CPU desktop, in fresh processes: `import grpc` added no OS threads;
the first `grpc.insecure_channel(...)` took the process from 1 OS thread to 13, and a second
channel added none; on the server side `grpc.server(...)` took it from 1 to 13 and `start()`
to 15. Those threads are invisible to `threading.enumerate()` — only the executor you hand to
[`grpc.server(...)`](https://grpc.github.io/grpc/python/grpc.html#grpc.server) shows up there,
and only Android has the `/proc/self/task` needed to count the rest. Treat 12 as a desktop
observation rather than a constant: both binaries carry the `WorkStealingThreadPool` symbols
and the string *Starting new ThreadPool thread due to backlog*, so the pool grows under load.

**If you use `grpc.aio` instead, build its objects inside a running loop.**
[`aio.insecure_channel(...)`](https://grpc.github.io/grpc/python/grpc_asyncio.html#grpc.aio.insecure_channel)
and [`aio.server()`](https://grpc.github.io/grpc/python/grpc_asyncio.html#grpc.aio.server)
both construct happily at module scope with no loop running and give no error — they fail
later, at first use, with `RuntimeError: Task … attached to a different loop` plus a
*Task was destroyed but it is pending* warning and a never-awaited-coroutine complaint, none
of which name the actual mistake. Build them inside `async def main(page)` or inside a
[`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task) coroutine. The
synchronous `grpc.insecure_channel` has no loop affinity and is fine at module scope.

### Schemas and codegen

**There is no protoc on device, no way to generate `_pb2_grpc.py` there, and no runtime
`.proto` loading.** [`grpc.protos()`](https://grpc.github.io/grpc/python/grpc.html#grpc.protos)
and `grpc.protos_and_services()` raise `NotImplementedError: Install the grpcio-tools package
(1.32.0+) to use the protos function.`, and grpcio-tools cannot be added — it bundles protoc,
a host binary, and is not on this index. Three real options, in increasing order of ceremony:

1. **Raw `bytes` messages and no schema at all**, with the identity function for both
   serialisers. Verified end to end for unary, server-streaming, deadlines, abort and
   metadata on both the sync and the `aio` API, and it is what
   [`loopback-rpc`](examples/loopback-rpc) is built on. Suits an app that already has its own
   framing, or one talking to a service it also owns.
2. **Generate `_pb2.py` and `_pb2_grpc.py` on your build machine** and ship them as ordinary
   app source. They are pure Python, so they package like any other module and the schema
   stays authoritative.
3. **Build descriptors at run time** with the `protobuf` runtime, which *is* on this index
   (see [`protobuf`](../protobuf)), and hand `SerializeToString` / `FromString` to gRPC as the
   serialisers. The most flexible and the most code.

### App size

Per slice, compressed wheel and unpacked payload, of which the single `cygrpc` extension is
94–99%:

| slice | wheel | unpacked |
| --- | ---: | ---: |
| Android arm64-v8a | 6.9 MB | 20.3 MB |
| Android armeabi-v7a | 6.6 MB | 15.3 MB |
| Android x86_64 | 7.2 MB | 20.4 MB |
| iOS arm64 (device) | 13.4 MB | 74.8 MB |
| iOS arm64 (simulator) | 14.0 MB | 75.6 MB |

An APK built for all three ABIs carries about 53 MB of `cygrpc` before whatever compression
the packaging applies. Every slice `flet build` targets has a wheel, so narrowing
[`[tool.flet.android] target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
to the ABIs you actually ship to is a size decision rather than a necessity — and on Android
it is the only lever that helps, alongside an app bundle or split APKs. There is nothing else
worth removing with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup): about 0.6 MB
of Python, the 264 KB trust store and the `dist-info` are all that sit beside the extension.

Sizes here are decimal, matching how the wheel's own byte count reads; `du -h` uses binary
units and will report each figure a few percent lower.

### Android

**The `INTERNET` permission is already there.** `flet build` starts its
[permission table](https://flet.dev/docs/publish/android/#permissions) from
`{"android.permission.INTERNET": True}` and merges your entries into it
(`flet_cli/commands/build_base.py`, 0.86.5), so opening or binding a socket needs no
`pyproject.toml` entry.

**TLS is OpenSSL 3.0.20, statically linked into the extension**, and nothing is resolved at
run time for it — there is no `libssl` or `libcrypto` among the extension's shared-library
dependencies. Compression uses the system `libz`.

**That costs Android one TLS API: the custom private-key signer.**
`grpc.experimental.ssl_channel_credentials_with_custom_signer(...)` is the hook for a client
certificate whose key you never hold — an Android Keystore or Secure Enclave one — and it is
backed by a C-core signer path upstream builds only against BoringSSL. The Android extension
carries the refusal string *grpc_tls_identity_pairs_add_pair_with_signer is only supported
with BoringSSL.*, which the iOS one does not. Both wheels ship the Python function and it is
callable on both, so any failure lands at run time rather than at import, and **the symptom on
a device was not measured here**. Plain
[`grpc.ssl_channel_credentials`](https://grpc.github.io/grpc/python/grpc.html#grpc.ssl_channel_credentials)
is unaffected on both platforms.

**Logs go to logcat, not to a swallowed stderr.** The extension links `liblog.so`. Verbosity
and tracing are runtime-controllable through `GRPC_VERBOSITY`, `GRPC_TRACE` and
`GRPC_PYTHON_DISABLE_ABSL_INIT_LOG`, all present in both platforms' binaries.

**The extension is 16 KB-page aligned**, so it loads on Android 15+ devices with 16 KB pages.

**DNS is the one thing to settle on your own device before designing around it.** The Android
build compiles in c-ares 1.34.5 as its resolver, and c-ares' Android server discovery wants a
JVM handle that nothing in the Python layer ever provides; the only other server source
compiled in is `/etc/resolv.conf`, which Android does not have. **This has not been tested on
a device here**, and the example deliberately cannot test it — a `127.0.0.1` literal never
resolves anything. Two mitigations, both unverified: select the other resolver with
`GRPC_DNS_RESOLVER=native` before the first channel, which routes lookups through bionic's
`getaddrinfo`, or address the backend by IP literal and skip resolution entirely. iOS has none
of this problem.

### iOS

**TLS is grpc's vendored BoringSSL, statically linked**, and so is zlib, at 1.3.1.1. Nothing
is linked dynamically for either. Because the trust store and the crypto both ship inside the
extension, an iOS build shares no TLS state with the system and none with the Python runtime's
`ssl` module.

**Sockets go through Apple's CFStream**, which is what the recipe's iOS-only
`-framework CoreFoundation` is for, and `GRPC_CFSTREAM_RUN_LOOP` is a recognised environment
variable here where it is not on Android.

**DNS goes through the system resolver.** The `DNSService*` family is resolved by the OS,
there is no c-ares in this build, and the only resolver log string is *Using EventEngine dns
resolver*. The Android DNS caveat above does not apply.

**There is no `/proc`**, so an app cannot count the C core's threads here — the example prints
`OS thread count needs /proc, so Android only` instead of guessing.

### Other considerations

A desktop `flet run` uses PyPI's own grpcio wheel, which is a different build of the same
Python API: it vendors BoringSSL on every platform, so the Android notes above describe a
binary you will never meet on your laptop, and the custom private-key signer that fails on an
Android device works in a desktop run. Anything that depends on which TLS library is
underneath — a custom signer, a cipher expectation, a `GRPC_*` environment variable — has to
be validated on a device or emulator.

`import grpc` is not free: about 76 ms and 15 MB of RSS, with the first channel adding roughly
1.5 MB more. That was measured against the macOS universal2 desktop wheel, whose extension
carries two architectures, so read it as an order of magnitude rather than as a device figure.
Either way, keep the import off whatever the first frame waits on.

## Things to know

- **Keep a reference to a `grpc.Server` you start.**
  `grpc._server._Server.__del__` sets a `server_deallocated` flag that the serving thread acts
  on, so a server whose only reference was a local in `main` stops serving shortly after `main`
  returns — and Flet returns from `main` as a matter of course. Every later call then comes back
  `UNAVAILABLE … failed to connect to all addresses`, which names the address rather than the
  mistake. Measured with the example: without the reference the initial render is green and
  every run after it collapses to `UNAVAILABLE`. `grpc._channel.Channel.__del__` deliberately
  does *not* close today, but upstream's comment there says that is temporary, so park the
  channel too.
- **Messages are capped at 4 MiB by default, in both directions, and the error says which
  side.** Measured: a 4,194,305 B response raised
  `RESOURCE_EXHAUSTED: CLIENT: Received message larger than max (4194305 vs. 4194304)`, and a
  5 MiB request raised `RESOURCE_EXHAUSTED: SERVER: Received message larger than max (5242880
  vs. 4194304)`; 4,194,288 B went through untouched. Raise it deliberately, per channel and
  per server, with `options=[("grpc.max_receive_message_length", n)]` — verified to carry a
  6 MiB response — and `grpc.max_send_message_length`.
- **gRPC brings its own trust store, so TLS needs no `certifi` and no system CA access.**
  `grpc/_cython/_credentials/roots.pem` ships in every wheel — about 264 KB and 130
  certificates, identical on both platforms and to upstream's. The C core fetches it through a
  callback into `pkgutil.get_data`, which was measured directly by wrapping that function and
  completing a real TLS handshake, after which the only recorded call was
  `('grpc._cython', '_credentials/roots.pem')`. That was a desktop measurement; the device half
  is the file surviving packaging, which the [`loopback-rpc`](examples/loopback-rpc) example
  prints in its header — the cheap way to confirm it on your own device. If it ever fails,
  `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` points the core at a copy you place in app storage.
- **Pass `timeout=` on every call.** Measured, `timeout=0.15` against a two-second handler
  raised `StatusCode.DEADLINE_EXCEEDED` with details `'Deadline Exceeded'` in about 155 ms.
  It is also the only limit whose behaviour this page has established — the keepalive and idle
  defaults below are not.
- **Do not rely on the keepalive and idle defaults on a phone.** A channel that has
  backgrounded or changed network can look alive and not be. All the knobs are in both
  binaries — `grpc.keepalive_time_ms`, `grpc.keepalive_timeout_ms`,
  `grpc.keepalive_permit_without_calls`, `grpc.client_idle_timeout_ms`,
  `grpc.initial_reconnect_backoff_ms`, `grpc.max_reconnect_backoff_ms`, `grpc.enable_retries` —
  so set the ones you care about explicitly in
  `grpc.insecure_channel(target, options=[...])`. **Their default values were not measured
  here**, so no number is quoted; establish them before designing a reconnect policy around
  them.
- **Compression is gzip or deflate, and nothing else.** `grpc.Compression` has exactly three
  members — `NoCompression` (0), `Deflate` (1), `Gzip` (2) — and neither binary carries a zstd
  or brotli codec. It does work: measured on loopback with a byte counter in the connection, an
  8,192 B compressible payload went over the wire as 8,250 B with `NoCompression` and 443 B
  with `Gzip`.
- **The sync `Channel` has no `get_state()`** — `AttributeError: 'Channel' object has no
  attribute 'get_state'`; it exists only on
  [`grpc.aio.Channel`](https://grpc.github.io/grpc/python/grpc_asyncio.html#grpc.aio.Channel.get_state).
  Use [`channel.subscribe(callback, try_to_connect=True)`](https://grpc.github.io/grpc/python/grpc.html#grpc.Channel.subscribe),
  which reports every transition (measured: `IDLE → CONNECTING → READY` against a live server,
  and `TRANSIENT_FAILURE` against a dead address), or
  [`grpc.channel_ready_future(channel)`](https://grpc.github.io/grpc/python/grpc.html#grpc.channel_ready_future).
- **`grpc.aio` ships complete and works.** Every module under `grpc/aio/` is in both wheels,
  plus `grpc/experimental/aio/`. Verified end to end with raw serializers: an `aio` server and
  `aio` channel in one loop, unary with trailing metadata, server-streaming, and `get_state()`
  reporting `IDLE` then `READY`. See [Threading](#threading) for the one trap.

## Build notes (maintainers)

### Recipe shape

A plain sdist build of upstream's `setup.py` with one patch and a per-platform `script_env`.
The shape decision behind it is the split in how the two platforms get their C dependencies:
Android sets `GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1` and `GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1` and
links a cross-built OpenSSL and the NDK's `libz`, while iOS takes upstream's default and
compiles grpc's vendored BoringSSL and zlib into the extension. That single choice is why
almost every claim in [Android](#android) and [iOS](#ios) differs between the platforms, and
why the patch exists at all — it is entirely about include paths that only matter on the
system-library side.

**The `openssl` host requirement is not a recipe in this repo.** It comes from the CPython
support tree: `setup.sh` runs `python -m make_dep_wheels`, which wraps each entry in that
tree's `VERSIONS` manifest into a `<lib>-<ver>-py3-none-<platform>.whl` so forge can resolve it
as a build dependency, and the CI job drops those again before publishing. So **a python-build
bump moves Android's TLS library underneath this wheel** without touching `meta.yaml`, and the
3.0.20 quoted in [Android](#android) is a fact about that tree rather than about this recipe.
It also explains why `openssl` never appears in `Requires-Dist` while `flet-libcpp-shared`
does: `build.py` promotes a `requirements.host` entry to `Requires-Dist` only when its name
starts with `flet-`.

**The runtime closure is two packages.** `typing-extensions~=4.12` resolves to a pure-Python
wheel from PyPI, and on **Android only** the wheel declares
`flet-libcpp-shared (>=27.2.12479018)` for `libc++_shared.so` — 1,292,904 B on arm64-v8a,
1,252,080 B on x86_64 and 872,872 B on armeabi-v7a. The iOS `METADATA` carries no such line,
because iOS resolves C++ against the system `/usr/lib/libc++.1.dylib`.

**The iOS extension ships unstripped, and that is a third of its size.** `strip -x` takes it
from 73,855,304 B to 48,976,208 B, and it stays that large because 53,372 symbols remain
exported. Nothing was tried here — an iOS extension that loses the wrong symbol fails at
framework conversion or at import rather than at build — but it is the one obvious size lever
this recipe has, and the Android side is already stripped.

### Upgrade hazards

**Upstream's dependency list moves between releases.** `typing-extensions` and the Android-only
`flet-libcpp-shared` are the whole closure today; a new upstream requirement without a mobile
wheel breaks the build rather than the page, and a dropped one silently invalidates the
paragraph above.

**A bump can end the `grpcio[protobuf]` story or start a protoc one.** The
[Schemas and codegen](#schemas-and-codegen) section rests on grpcio-tools being unavailable
here; if that ever changes, options (2) and (3) stop being the only routes to a schema.

### Re-verification checklist

Everything above this section is a consumer-facing claim that a green build can silently
invalidate.

- **Whether a bare `grpcio` still wins the resolve.** `flet build` resolves against PyPI *and*
  `https://pypi.flet.dev` and takes the highest usable version; this index only wins because
  upstream publishes no Android, no iOS and no `py3-none-any` wheel. The day it does, pinning
  becomes the advice in [Install](#install). Re-run one
  `pip download --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev
  grpcio` per target and read the filename that comes back — last measured across all fifteen
  slice-and-minor combinations (three Android ABIs plus the iOS device and x86\_64-simulator
  slices, on Python 3.12, 3.13 and 3.14), every one of which returned this index's wheel.
- **Wheel coverage.** 19 wheels for the current version: the three Android ABIs, the iOS device
  slice and both simulator slices on each of Python 3.12, 3.13 and 3.14, plus a cp312-only
  `android_24_x86` wheel that `flet build` has no target for. armeabi-v7a must stay a genuine
  32-bit build rather than a stub — `file` should report *ELF 32-bit LSB shared object, ARM,
  EABI5* — or [App size](#app-size)'s claim that no `target_arch` narrowing is required stops
  being true.
- **That the Python layer is still upstream's.** 56 `.py` files, 612,994 B in total, each
  byte-identical to upstream's PyPI wheel of the same version, and `roots.pem` with md5
  `09b0a4e1f6db75fbc55d4b2b3643f4ea`. That identity is what licenses the intro's claim that
  upstream's documentation applies.
- **The trust store's size and count.** [Things to know](#things-to-know) quotes about 264 KB
  and 130 certificates, and both change whenever upstream refreshes `roots.pem`. The example
  computes them at run time, so only the prose goes stale.
- **Both platforms' linkage and vendoring.** The BoringSSL-versus-OpenSSL split, the zlib
  split, `DT_NEEDED` on Android and `otool -L` on iOS, and the CFStream and `DNSService*`
  imports are all read out of the binary in seconds and are what the platform sections are made
  of. A `libssl.so` appearing in `DT_NEEDED` would be a runtime dependency [Install](#install)
  does not mention, and the disappearance of the *only supported with BoringSSL* string from
  the Android extension would mean the custom signer had become usable there.
- **Every measured number**: the size table, the 4 MiB ceiling and its two error strings, the
  thread and timing figures, the gzip ratio, and the c-ares version. Re-measure rather than
  scaling, and re-run the example, whose pins are the record of the combination that was
  actually built.
- **The error and status strings quoted above** are upstream's wording, including
  `'Deadline Exceeded'`, the two `Received message larger than max` variants and the
  `protos()` `NotImplementedError`. All of them are subject to being reworded.

### Coverage gaps

`tests/test_grpcio.py` pins none of this: two functions that create credentials, a channel
object and read `StatusCode` values, so no claim on this page turns CI red if it breaks. The
cheap additions, in order of what a regression would cost an app, are a
`pkgutil.get_data("grpc._cython", "_credentials/roots.pem")` length assertion; a `127.0.0.1`
round trip through `method_handlers_generic_handler` with raw serializers, which is the whole
no-codegen story; and a `grpc.Compression.Gzip` round trip, since gzip runs through the zlib
each platform links differently.

Four consumer-facing claims rest on desktop measurement or inspection alone:

- **Zipped site-packages.** The C core reaches `roots.pem` through `pkgutil.get_data`, which
  needs the module's `__file__` and its loader's `get_data`. Both work under `zipimport`, and
  that was verified against a synthetic `sitepackages.zip` on desktop — a real device has only
  ever been checked through the example's header line.
- **Android DNS.** Never exercised on a device; the example uses an IP literal, which skips
  resolution entirely, and `GRPC_DNS_RESOLVER=native` has not been tried.
- **The custom private-key signer.** Known to be compiled out of the Android extension from the
  refusal string alone; nobody has watched it fail on a device, so the exception type and
  message are unknown.
- **Two OpenSSLs in one Android process.** The 3.0.20 linked into the extension sits alongside
  whatever the Python runtime's `ssl` module is linked against. CPython loads extensions
  without `RTLD_GLOBAL`, so interposition should not occur, and nothing odd has been observed —
  but nothing has been tested for it either. It is where to look first if the ordering of
  `import ssl` and `import grpc` ever seems to matter.
