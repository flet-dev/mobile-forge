# grpcio

[`grpcio`](https://grpc.io/docs/languages/python/) is Google's RPC framework: HTTP/2
transport, streaming in either direction or both, deadlines, status codes, metadata and
per-call compression, all driven by a large C core that this wheel wraps in a single Cython
extension. The reason to want it on a phone is narrow and decisive — the backend already
speaks gRPC, and the alternative is standing up a REST gateway in front of it.

Every one of the 56 Python files in these wheels is byte-identical to upstream's own PyPI
wheel of the same version, and so is grpc's bundled CA store
(`grpc/_cython/_credentials/roots.pem`, md5 `09b0a4e1f6db75fbc55d4b2b3643f4ea`). So
[upstream's documentation](https://grpc.github.io/grpc/python/) applies unchanged — bar one
TLS API that Android's build cannot support, in [Android notes](#android-notes) — and
everything worth knowing here is about the extension: how big it is, what it links, where it
gets its trust store, and how it resolves names.

Be warned about the first of those before you read further. This is by a wide margin the
heaviest package on this index that an app would add for networking: 14.4–19.5 MB of native
code per Android ABI and 73.9 MB on iOS, where [`aiohttp`](../aiohttp)'s README measures all
four of its extensions at 616,832 B on arm64-v8a and [`websockets`](../websockets)' at
6,992 B for its single accelerator. If your backend can be reached any other way, that is a
real argument for reaching it that way.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "grpcio",
]
```

**A bare `grpcio` does give you the wheel from this index, on every slice.** That is worth
stating because it is not true of this recipe's siblings: `flet build` resolves against PyPI
*and* `https://pypi.flet.dev` and takes the highest usable version, and both
[`aiohttp`](../aiohttp#install) and [`websockets`](../websockets#install) can lose that race
to upstream's own wheels — websockets on every slice, aiohttp on the 3.13 and 3.14 slices
upstream publishes for, which leaves one APK carrying two aiohttp versions across its ABIs.
grpcio publishes no Android or iOS wheels on PyPI and no
`py3-none-any` wheel either, so with `--only-binary :all:` there is nothing for this index to
lose to. Measured, one resolve for each of fifteen slice-and-minor combinations — Android
arm64-v8a, armeabi-v7a and x86_64 plus the iOS device and x86\_64-simulator slices, on Python
3.12, 3.13 and 3.14 — every one returned this index's wheel.

Two things come along, and only two. `typing-extensions~=4.12` is a pure-Python wheel from
PyPI (4.16.0 at the time of writing). On **Android only**, the wheel also declares
`flet-libcpp-shared (>=27.2.12479018)` and pip pulls it automatically; it carries
`libc++_shared.so`, which is 1,292,904 B on arm64-v8a, 1,252,080 B on x86_64 and 872,872 B
on armeabi-v7a. The iOS `METADATA` has no such line — iOS resolves C++ to the system
`/usr/lib/libc++.1.dylib` and ships nothing extra. Nothing else appears in the resolve.

**`grpcio[protobuf]` cannot be satisfied.** That extra asks for `grpcio-tools`, which bundles
protoc — a host binary — and is not on this index (`https://pypi.flet.dev/grpcio-tools/`
returns 404). See the codegen bullet in [Things to know](#things-to-know) for what to do
instead; the [`loopback-rpc`](examples/loopback-rpc) example needs no schema at all.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. The Python layer never touches `__file__` and never calls `open()`; the one
data file, `roots.pem`, is fetched by the *extension* through
`pkgutil.get_data("grpc._cython", "_credentials/roots.pem")`, which `zipimport` implements —
verified against a synthetic `sitepackages.zip`, where the same call returned the file's bytes
through a `zipimporter`. The [`loopback-rpc`](examples/loopback-rpc) example prints the size
it got, which is the cheap way to confirm that on your own device.

Coverage is complete for what Flet targets: 18 wheels for the version in
[`meta.yaml`](meta.yaml), spanning arm64-v8a, armeabi-v7a and x86_64 on Android
([the three `flet build` offers](https://flet.dev/docs/publish/android/#supported-target-architectures)),
the iOS device slice and both simulator slices, on Python 3.12, 3.13 and 3.14 — plus a
nineteenth, cp312-only `android_24_x86` wheel that `flet build` has no target for.
armeabi-v7a is a genuine 32-bit build rather than a stub (`file` reports *ELF 32-bit LSB
shared object, ARM, EABI5*, with a 7,172,176 B `.text`), so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed to make the build work. You may still want one to make the APK smaller —
see [Things to know](#things-to-know).

## Storage

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

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`loopback-rpc`](examples/loopback-rpc) — a gRPC server and grpc's own client on
  `127.0.0.1` with no generated stubs, and a byte counter on the wire between them.

## Threading

**The blocking API releases the GIL for the whole of a call**, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is the
right home for it and the UI stays live while a call is in flight. Measured against a
one-second server-side wait: a Python canary thread ran at 37.9 M ticks/s during the call and
38.3 M/s during a control `time.sleep(1.0)`, against 14.5 M/s while a pure-Python busy loop
held the GIL. That is the opposite of the advice on the [`aiohttp`](../aiohttp#threading) and
[`websockets`](../websockets#threading) pages, and it is because gRPC's sync API is genuinely
synchronous rather than an asyncio library.

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
Measured on a 10-logical-CPU desktop, in fresh processes: `import grpc` added no OS threads
and cost 76 ms; the first `grpc.insecure_channel(...)` took the process from 1 OS thread to 13
and cost 5.6 ms, and a second channel added none and cost 0.13 ms; on the server side
`grpc.server(...)` took it from 1 to 13 and `start()` to 15. Those threads are invisible to
`threading.enumerate()` — only the executor you hand to
[`grpc.server(...)`](https://grpc.github.io/grpc/python/grpc.html#grpc.server) shows up there.
Treat 12 as a desktop observation rather than a constant — both binaries carry the
`WorkStealingThreadPool` symbols and the string *Starting new ThreadPool thread due to
backlog*, so the pool also grows under load. The
[`loopback-rpc`](examples/loopback-rpc) example prints the figure on Android, the only
platform here where `/proc/self/task` can answer.

**If you use `grpc.aio` instead, build its objects inside a running loop.**
[`aio.insecure_channel(...)`](https://grpc.github.io/grpc/python/grpc_asyncio.html#grpc.aio.insecure_channel)
and [`aio.server()`](https://grpc.github.io/grpc/python/grpc_asyncio.html#grpc.aio.server)
both construct happily at module scope with no loop running and give no error — they fail
later, at first use, with `RuntimeError: Task … attached to a different loop` plus a
*Task was destroyed but it is pending* warning and a never-awaited-coroutine complaint, none
of which name the actual mistake. Build them inside `async def main(page)` or inside a
[`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task) coroutine. The
synchronous `grpc.insecure_channel` has no loop affinity and is fine at module scope.

## Android notes

**The `INTERNET` permission is already there.** `flet build` starts its
[permission table](https://flet.dev/docs/publish/android/#permissions) from
`{"android.permission.INTERNET": True}` and merges your entries into it
(`flet_cli/commands/build_base.py`, 0.86.5), so opening or binding a socket needs no
`pyproject.toml` entry.

**TLS is OpenSSL 3.0.20, statically linked into the extension.** `strings` on the Android
`.so` finds OpenSSL's own `crypto/asn1/*.c` paths and the version `3.0.20`, and no BoringSSL
source paths at all — the reverse of iOS, whose only `crypto/asn1` paths are
`third_party/boringssl-with-bazel/…`. Nothing is resolved at run time for it: `DT_NEEDED` is
`libm`, `liblog`, `libz`, `libpython3.<minor>`, `libc++_shared`, `libdl`, `libc`, with no
`libssl` or `libcrypto` anywhere.

**That costs Android one TLS API: the custom private-key signer.**
`grpc.experimental.ssl_channel_credentials_with_custom_signer(...)` is the hook for a client
certificate whose key you never hold — an Android Keystore or Secure Enclave one — and it is
backed by a C-core signer path upstream builds only against BoringSSL. The Android `.so`
carries the refusal string *grpc_tls_identity_pairs_add_pair_with_signer is only supported
with BoringSSL.*, which the iOS one does not; iOS carries the working implementation's
*PrivateKeySigner is null* instead. Both wheels ship the Python function and it is callable on
both, so any failure lands at run time rather than at import, and **the symptom on a device
was not measured here**. Plain
[`grpc.ssl_channel_credentials`](https://grpc.github.io/grpc/python/grpc.html#grpc.ssl_channel_credentials)
is unaffected on both platforms.

**zlib is the system one.** `libz.so` is a `DT_NEEDED` entry, where iOS statically vendors its
own copy.

**Logs go to logcat, not to a swallowed stderr.** The extension imports
`__android_log_write` and links `liblog.so`. Verbosity and tracing are runtime-controllable
through `GRPC_VERBOSITY`, `GRPC_TRACE` and `GRPC_PYTHON_DISABLE_ABSL_INIT_LOG`, all present in
both platforms' binaries.

**The extension is 16 KB-page aligned**, so it loads on Android 15+ devices with 16 KB pages:
every `PT_LOAD` has `Align 0x4000`.

**DNS is the one thing to settle on your own device before designing around it.** The Android
build compiles in c-ares 1.34.5 as a resolver, and c-ares' Android server discovery wants a
JVM handle — `ares_library_init_android` / `ares_library_init_jvm` are in the binary, along
with `android/net/ConnectivityManager` — that nothing in the Python layer ever provides. The
only other server source in the binary is `/etc/resolv.conf`, which Android does not have, and
there are no `net.dns`-style system-property strings. **This has not been tested on a device
here**, and the example deliberately cannot test it: a `127.0.0.1` literal never resolves
anything. Two mitigations, both unverified: select the other resolver with
`GRPC_DNS_RESOLVER=native` before the first channel — the binary carries both *Using ares dns
resolver* and *Using native dns resolver*, and imports `getaddrinfo`/`freeaddrinfo` from
bionic — or address the backend by IP literal, which skips resolution entirely. iOS has none
of this problem; see below.

**Android is the only platform here that can count its own threads**, through
`/proc/self/task`. See [Threading](#threading).

## iOS notes

**TLS is grpc's vendored BoringSSL, statically linked** — 206 `third_party/boringssl-with-bazel/…`
source paths and `BORINGSSL_keccak_absorb` in the binary, and none of OpenSSL's markers. zlib
is vendored too, at 1.3.1.1 (its copyright banner is in the binary). Nothing is linked
dynamically for either: `otool -L` lists only `Python.framework`, `CoreFoundation`,
`libSystem` and `/usr/lib/libc++.1.dylib`.

**Sockets go through Apple's CFStream**, which is what the recipe's iOS-only
`-framework CoreFoundation` is for: `nm -u` shows `CFStreamCreatePairWithSocketToHost`, the
`CFReadStream`/`CFWriteStream`, `CFRunLoop` and `CFSocket` families, and `GRPC_CFSTREAM_RUN_LOOP`
appears in the iOS environment-variable list and not in Android's.

**DNS goes through the system resolver** — `_DNSServiceGetAddrInfo`,
`_DNSServiceSetDispatchQueue` and `_DNSServiceRefDeallocate` are undefined symbols resolved by
the OS, there is no c-ares in this build (3 `ares_` string hits against Android's 536), and the
only resolver log string is *Using EventEngine dns resolver*. The Android DNS caveat above
does not apply here.

**The extension needs no fixing up.** It is `MH_DYLIB` with `NOUNDEFS` (`otool -hv`), so it
does not hit the `MH_BUNDLE` link failure that has bitten other recipes on this index.

**It is also enormous, and two thirds of that is not code.** 73,855,304 B, of which
`__LINKEDIT` is 48,316,416 B of symbol data and `__text` is 20,936,016 B — against Android's
9,191,712 B `.text`. The iOS binary is shipped unstripped; the Android ones are stripped. See
the size bullet in [Things to know](#things-to-know).

**There is no `/proc`**, so an app cannot count the C core's threads here.

## Things to know

- **There is no protoc, no `_pb2_grpc.py` and no runtime `.proto` loading.**
  `grpc.protos()` / `grpc.protos_and_services()` raise
  `NotImplementedError: Install the grpcio-tools package (1.32.0+) to use the protos
  function.`, and grpcio-tools cannot be added — it bundles protoc, a host binary, and is not
  on this index. Three real options, in increasing order of ceremony: **(1)** raw `bytes`
  serializers and no schema at all, which is verified end to end for unary, server-streaming,
  deadlines, abort and metadata on both the sync and the `aio` API, and is what
  [`loopback-rpc`](examples/loopback-rpc) is built on; **(2)** generate `_pb2.py` and
  `_pb2_grpc.py` on your build machine and ship them as ordinary app source, since they are
  pure Python; **(3)** build descriptors at run time with the `protobuf` runtime, which *is* on
  this index (see [`protobuf`](../protobuf)), and hand `SerializeToString`/`FromString` to gRPC
  as the serializers.
- **Keep a reference to a `grpc.Server` you start.**
  `grpc._server._Server.__del__` sets a `server_deallocated` flag that the serving thread acts
  on, so a server whose only reference was a local in `main` stops serving shortly after `main`
  returns — and Flet returns from `main` as a matter of course. Every later call then comes back
  `UNAVAILABLE … failed to connect to all addresses`, which names the address rather than the
  mistake. Measured with the example: without the reference the initial render is green and
  every run after it collapses to `UNAVAILABLE`. `grpc._channel.Channel.__del__` deliberately does *not* close
  today, but upstream's comment there says that is temporary, so park the channel too.
- **Messages are capped at 4 MiB by default, in both directions, and the error says which
  side.** Measured: a 4,194,305 B response raised
  `RESOURCE_EXHAUSTED: CLIENT: Received message larger than max (4194305 vs. 4194304)`, and a
  5 MiB request raised `RESOURCE_EXHAUSTED: SERVER: Received message larger than max (5242880
  vs. 4194304)`; 4,194,288 B went through untouched. Raise it deliberately, per channel and
  per server, with `options=[("grpc.max_receive_message_length", n)]` — verified to carry a
  6 MiB response — and `grpc.max_send_message_length`.
- **gRPC brings its own trust store; unlike aiohttp it needs no `certifi`.**
  `grpc/_cython/_credentials/roots.pem` ships in every wheel: 264,440 B, 130 certificates,
  identical on both platforms and identical to upstream's. The C core fetches it through a
  Cython override callback that calls `pkgutil.get_data` — measured directly by wrapping
  `pkgutil.get_data` and completing a real TLS handshake, after which the *only* recorded call
  was `('grpc._cython', '_credentials/roots.pem')`. That measurement was on a desktop; the
  device half is the file surviving packaging, which is what the example's header line checks.
  If it ever fails, `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` points the core at a copy you place in
  app storage.
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
  members — `NoCompression` (0), `Deflate` (1), `Gzip` (2) — and the binaries carry `gzip`,
  `deflate`, `identity`, `grpc-encoding` and `grpc-accept-encoding` with no zstd or brotli
  strings. It does work: measured on loopback with a byte counter in the connection, an 8,192 B
  compressible payload went over the wire as 8,250 B with `NoCompression` and 443 B with
  `Gzip`.
- **The sync `Channel` has no `get_state()`** — `AttributeError: 'Channel' object has no
  attribute 'get_state'`; it exists only on
  [`grpc.aio.Channel`](https://grpc.github.io/grpc/python/grpc_asyncio.html#grpc.aio.Channel.get_state).
  Use [`channel.subscribe(callback, try_to_connect=True)`](https://grpc.github.io/grpc/python/grpc.html#grpc.Channel.subscribe),
  which reports every transition (measured: `IDLE → CONNECTING → READY` against a live server,
  and `TRANSIENT_FAILURE` against a dead address), or
  [`grpc.channel_ready_future(channel)`](https://grpc.github.io/grpc/python/grpc.html#grpc.channel_ready_future).
- **`grpc.aio` ships complete and works.** All 11 modules under `grpc/aio/` are in both
  wheels, plus `grpc/experimental/aio/`. Verified end to end with raw serializers: an `aio`
  server and `aio` channel in one loop, unary with trailing metadata, server-streaming, and
  `get_state()` reporting `IDLE` then `READY`. See [Threading](#threading) for the one trap.
- **Size, which is the real cost of this package.** Per slice, and the extension is 94–99% of
  it:

  | slice (cp314) | wheel | unpacked | the extension |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 6,947,731 B | 20,254,526 B | 19,331,120 B |
  | Android armeabi-v7a | 6,600,694 B | 15,338,072 B | 14,414,664 B |
  | Android x86_64 | 7,203,872 B | 20,394,930 B | 19,471,528 B |
  | iOS arm64 (device) | 13,391,523 B | 74,781,247 B | 73,855,304 B |
  | iOS arm64 (simulator) | 14,006,246 B | 75,610,157 B | 74,684,200 B |

  An APK built for all three ABIs therefore carries 53,217,312 B of `cygrpc` before whatever
  compression the packaging applies, which is the case for narrowing
  [`[tool.flet.android] target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
  to the ABIs you actually ship to. Everything else in the wheel is small: 612,994 B of Python
  across 56 files, the 264,440 B trust store, 8,902 B of two stray C++ source files that got
  packaged with it, and the `dist-info`.
- **`import grpc` is not free.** 76 ms and about 15 MB of RSS on a desktop, with the first
  channel adding roughly 1.5 MB more. That was measured against the macOS universal2 wheel,
  whose extension is 38,724,096 B for two architectures, so read it as an order of magnitude
  rather than as a device figure. Keep the import off whatever the first frame waits on.
- **Android ends up with two OpenSSLs in one process** — the 3.0.20 statically linked into
  `cygrpc`, which exports 19,139 global dynamic symbols including 465 `SSL_*` and 852 `EVP_*`,
  alongside whatever OpenSSL the Python runtime's own `ssl` module is linked against. No
  problem is known to follow from that, and none was observed; CPython loads extensions
  without `RTLD_GLOBAL` (`sys.getdlopenflags()` is `RTLD_NOW`), so interposition should not
  occur. This is recorded because it is where to look first if anything odd ever shows up
  around the ordering of `import ssl` and `import grpc` on Android — not as a reassurance,
  since it has not been tested on a device.

## Build notes (maintainers)

The recipe is a plain sdist build of upstream's `setup.py` with one patch and a per-platform
`script_env`, and the shape decision behind it is the split in how the two platforms get their
C dependencies. Android sets `GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1` and
`GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1` and links a cross-built OpenSSL and the NDK's `libz`; iOS
takes upstream's default and compiles grpc's vendored BoringSSL and zlib into the extension.
That is why almost every claim in [Android notes](#android-notes) and
[iOS notes](#ios-notes) differs between the two platforms, and why the patch exists at all —
it is entirely about include paths that only matter on the system-library side.

- **The `openssl` host requirement is not a recipe in this repo.** It comes from the CPython
  support tree: `setup.sh` runs `python -m make_dep_wheels`, which wraps each entry in that
  tree's `VERSIONS` manifest into a `<lib>-<ver>-py3-none-<platform>.whl` so forge can resolve
  it as a build dependency, and the CI job drops those again before publishing. So **a python-build
  bump moves Android's TLS library underneath this wheel** without touching `meta.yaml`, and
  the 3.0.20 in [Android notes](#android-notes) is a fact about that tree rather than about
  this recipe. It also explains why `openssl` never appears in `Requires-Dist` while
  `flet-libcpp-shared` does: `build.py` promotes a `requirements.host` entry to `Requires-Dist`
  only when its name starts with `flet-`.
- **`patches/mobile.patch` has no preamble and should get one.** The file's first line is
  already `--- a/setup.py`, so nothing in it says what it changes or why, which is exactly what
  the convention in `README.rst` § *Adding your own packages* exists to prevent. Fix it above
  the first `---`, without touching the diff body; until then this paragraph is the only record
  that its three hunks are (a) c-ares platform config directories for `ios` and `android`,
  (b) `SSL_INCLUDE` following `OPENSSL_ROOT_DIR` instead of `/usr/include/openssl`, and
  (c) dropping `ZLIB_INCLUDE` on Android to keep `/usr/include` off the cross include path.
- **`tests/test_grpcio.py` pins none of this.** Two functions, both docstring'd and neither
  version-asserting, that create credentials, a channel object and read `StatusCode` values —
  so none of the claims above turn CI red if they break. The cheap additions, in order of what
  a regression would cost an app: `len(pkgutil.get_data("grpc._cython",
  "_credentials/roots.pem")) == 264440`; a `127.0.0.1` round trip through
  `method_handlers_generic_handler` with raw serializers, which is the whole no-codegen story;
  and a `grpc.Compression.Gzip` round trip, since gzip runs through the zlib each platform
  links differently.
- **The iOS extension ships unstripped, and that is 33% of its size.** `strip -x` takes
  73,855,304 B to 48,976,208 B; it stays that large because 53,372 symbols remain exported.
  Nothing was tried here — an iOS extension that loses the wrong symbol fails at framework
  conversion or at import rather than at build — but it is the one obvious size lever this
  recipe has, and the Android side is already stripped.

On a bump, everything above this section is a claim a green build can silently invalidate:

- **Whether a bare `grpcio` still wins the resolve.** The [Install](#install) claim rests on
  upstream publishing no mobile and no `py3-none-any` wheels; the day it does, this page reads
  the way [`aiohttp`](../aiohttp#install)'s does, and pinning becomes the advice. Re-run one
  `pip download --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev
  grpcio` per target and read the filename that comes back.
- **The dependency list.** `typing-extensions~=4.12` and the Android-only
  `flet-libcpp-shared` are the entire closure today; upstream adds and drops requirements
  between releases, and a new one that has no mobile wheel breaks the build rather than the
  page.
- **The trust store's size and count.** This page, the example's README and the suggested
  test all quote 264,440 B and 130 certificates, and they change whenever upstream refreshes
  `roots.pem`. The app itself computes both, so only the prose goes stale.
- **Both platforms' linkage and vendoring.** The BoringSSL-versus-OpenSSL split, the zlib
  split, `DT_NEEDED` on Android and `otool -L` on iOS, and the CFStream and `DNSService*`
  imports are all read out of the binary in a few seconds and are what the platform notes are
  made of. A `libssl.so` appearing in `DT_NEEDED` would be a runtime dependency
  [Install](#install) does not mention, and the disappearance of the
  *only supported with BoringSSL* string from the Android `.so` would mean the custom signer
  had become usable there.
- **The measured numbers**: every size in the table, the 4 MiB ceiling and its two error
  strings, the thread and timing figures, the gzip ratio, and the c-ares version. Re-measure
  rather than scaling — and re-run the example, whose pins are the record of the combination
  that was actually built.
- **The error and status strings quoted above** are upstream's wording, including
  `'Deadline Exceeded'`, the two `Received message larger than max` variants and the
  `protos()` `NotImplementedError`. All of them are subject to being reworded.
