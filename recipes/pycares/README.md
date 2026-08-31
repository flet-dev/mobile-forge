# pycares

[`pycares`](https://github.com/saghul/pycares) is a Python binding for
[c-ares](https://c-ares.org/), an asynchronous DNS resolver written in C. It is what
[`aiodns`](https://github.com/aio-libs/aiodns) is built on, and `aiodns` in turn is what
[`aiohttp`](https://docs.aiohttp.org/en/stable/) uses when you ask it to resolve names
without blocking a thread.

The standard library resolves names with
[`socket.getaddrinfo`](https://docs.python.org/3/library/socket.html#socket.getaddrinfo),
which blocks — asyncio's
[`loop.getaddrinfo`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.getaddrinfo)
just moves that block onto a thread-pool worker. c-ares speaks DNS over
UDP itself, so a lookup is genuinely asynchronous and hundreds can be in flight at once.
That is the reason to reach for it on a phone: a crawler, a scanner, or anything that
resolves many names at once stops being bounded by the thread pool.

The wheel is small (roughly 120–145 KB compressed per slice) and vendors
[c-ares 1.34.6](https://github.com/c-ares/c-ares/releases/tag/v1.34.6) statically, so
nothing else needs to ship with it.

## Install

```toml
dependencies = [
    "flet",
    "aiodns",
    "pycares",
]
```

`aiodns` is pure Python and installs straight from
[PyPI](https://pypi.org/project/aiodns/); `pycares` comes from
[pypi.flet.dev](https://pypi.flet.dev). [`cffi`](https://cffi.readthedocs.io/en/stable/),
which pycares needs at runtime, is already published there too and resolves automatically.
IDNA-2008 support is an optional extra (`pycares[idna]`, pulling
[`idna`](https://pypi.org/project/idna/)) — without it pycares falls back to the standard
library's
[IDNA-2003 codec](https://docs.python.org/3/library/codecs.html#module-encodings.idna),
which is present in Flet's Python builds.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`dns-lookup`](examples/dns-lookup) — resolves a hostname to `A`/`AAAA`/`CNAME`/`MX`/`NS`/`TXT`
  records against either the system resolver or a public one, and shows which nameservers
  c-ares actually found.

## Read this first: nameservers on Android

**On Android, c-ares finds no system nameservers, and every lookup fails until you supply
your own.** This is not something the recipe can fix, and it is the one thing that will
cost you an afternoon if you do not know it.

Android removed the `net.dns1`…`net.dns8` system properties in
[Android 8](https://developer.android.com/about/versions/oreo/android-8.0-changes), and the
replacement —
[`ConnectivityManager`](https://developer.android.com/reference/android/net/ConnectivityManager)`.getLinkProperties()`
+ [`getDnsServers()`](<https://developer.android.com/reference/android/net/LinkProperties#getDnsServers()>)
— is Java-only. c-ares can call it, but only if the app first hands it a JVM pointer
through
[`ares_library_init_jvm()` / `ares_library_init_android()`](https://c-ares.org/docs/ares_library_init_android.html),
and pycares exposes neither. So
c-ares' Android config path finds nothing, and rather than failing loudly it falls back to
a single default server, `127.0.0.1:53`, where nothing is listening. Verified on an API-34
emulator with this recipe's wheel:

```
auto-discovered servers: ['127.0.0.1:53']
[system DNS]                query A -> FAILED DNSError: (11, 'Could not contact DNS servers')
[explicit 1.1.1.1/8.8.8.8]  query A -> ['54.160.224.51', '54.227.151.68']
```

Pass the nameservers explicitly and everything works:

```python
resolver = aiodns.DNSResolver(nameservers=["1.1.1.1", "8.8.8.8"])
```

or, at the pycares layer:

```python
channel = pycares.Channel(servers=["1.1.1.1", "8.8.8.8"])
```

Which resolvers to name is your call — a public one
([Cloudflare](https://developers.cloudflare.com/1.1.1.1/),
[Google](https://developers.google.com/speed/public-dns),
[Quad9](https://www.quad9.net/)), your own, or one your user configures. There is no
environment variable for it:
[`LOCALDOMAIN` and `RES_OPTIONS`](https://man7.org/linux/man-pages/man5/resolv.conf.5.html)
are honoured, but neither sets servers.

If you need the *device's* resolvers specifically, read them on the Java side with
[pyjnius](https://pyjnius.readthedocs.io/en/latest/) via
[`ConnectivityManager`](https://developer.android.com/reference/android/net/ConnectivityManager),
then pass the addresses into `DNSResolver(nameservers=...)`. If you would rather not deal
with any of this,
[`socket.getaddrinfo`](https://docs.python.org/3/library/socket.html#socket.getaddrinfo)
(and asyncio's default resolver) uses Android's own resolver and always works — you just
lose the concurrency that made pycares worth it.

On **iOS** none of this applies: c-ares reads the system DNS configuration and lookups work
with no configuration. Verified on the simulator — the real router and ISP resolvers came
back, and `pypi.flet.dev` resolved through them.

## Usage in a Flet app

[`aiodns`](https://github.com/aio-libs/aiodns#api) is the API you want; awaiting it from a
Flet handler is the whole integration:

```python
import aiodns

async def resolve(e):
    resolver = aiodns.DNSResolver(nameservers=["1.1.1.1"], timeout=5.0, tries=2)
    try:
        result = await resolver.query_dns("pypi.flet.dev", "A")
        for record in result.answer:
            print(record.name, record.ttl, record.data)
    finally:
        await resolver.close()
```

`query_dns()` returns pycares 5.x's
[typed dataclasses](https://github.com/saghul/pycares/blob/master/docs/channel.rst) — an `A`
answer carries `ARecordData(addr=...)`, an `MX` answer `MXRecordData(priority=..., exchange=...)`,
and so on. (`query()` still exists but is deprecated in aiodns 4.x.)
[`getaddrinfo()`](https://c-ares.org/docs/ares_getaddrinfo.html) is the closest analogue to
the stdlib call and returns both address families at once.

Resolving many names concurrently — with
[`asyncio.gather`](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather) —
is the point of all this:

```python
results = await asyncio.gather(
    *(resolver.query_dns(name, "A") for name in names),
    return_exceptions=True,
)
```

### Threading

There is no
[`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) here and
there should not be. pycares gives every channel its own c-ares event thread —
[epoll](https://man7.org/linux/man-pages/man7/epoll.7.html) on Android,
[kqueue](https://man.freebsd.org/cgi/man.cgi?kqueue) on iOS — inside the wheel, and aiodns
marshals each completion back with
[`loop.call_soon_threadsafe`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.call_soon_threadsafe).
Awaiting a lookup never blocks the UI thread, and the resolver does not need a
[`SelectorEventLoop`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.SelectorEventLoop).

Two consequences worth knowing. A channel is not a free object: each one starts a thread,
so build one resolver and keep it rather than one per lookup. And `DNSResolver.close()` is
a coroutine — `await` it, or the daemon thread that tears the channel down keeps waiting on
the query queue.

Construct the resolver inside the running loop, not at module import. On Python 3.14
[`asyncio.get_event_loop()`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.get_event_loop)
raises outside a running loop, which turns a module-level `DNSResolver()` into an
import-time crash.

### Offline vs online

Everything here needs the network by definition. On Android that means the
[`INTERNET`](https://developer.android.com/reference/android/Manifest.permission#INTERNET)
permission, which [`flet build`](https://flet.dev/docs/publish/android/#permissions) grants
by default. Nothing is cached to disk: c-ares keeps an in-memory query cache per channel
and reads no configuration files on either platform.

### App size

Roughly 116–143 KB compressed and 257–445 KB unpacked per slice, essentially all of it the
one compiled extension with c-ares linked in; `armeabi_v7a` is the smallest. There are no
data files, and `aiodns` adds a 13 KB pure-Python wheel on top.

## Things to know

- **`ARES_VERSION` is c-ares', not pycares'.** The vendored library is pinned by the sdist;
  this wheel carries [1.34.6](https://github.com/c-ares/c-ares/releases/tag/v1.34.6).

- **`aiodns` pins `pycares>=5.0.0,<6`.** They move together — a pycares bump past 5.x will
  need an aiodns that accepts it.

- **[`search()`](https://c-ares.org/docs/ares_search.html) behaves differently from
  desktop.** It appends the resolver's search domains, and on Android there are none to
  append (the same config path that finds no servers finds no domains either). Prefer `query_dns()` in mobile code, where the name you pass is the
  name that gets queried.

- **[`Channel.set_local_ip()`](https://github.com/saghul/pycares/blob/master/docs/channel.rst)
  raises `TypeError` for IPv6 addresses.** An upstream cdef/implementation mismatch, not
  something this build introduces, and it affects every platform. IPv4 source binding
  works.

- **On iOS, c-ares reads DNS config through Apple private SPIs.**
  [`ares_sysconfig_mac.c`](https://github.com/c-ares/c-ares/blob/main/src/lib/ares_sysconfig_mac.c)
  `dlopen`s `libSystem` and `dlsym`s `dns_configuration_copy` / `dns_configuration_free` /
  `dns_configuration_notify_key`, because upstream found the public
  [`SCDynamicStore`](https://developer.apple.com/documentation/systemconfiguration/scdynamicstore)
  API returned incomplete data. Those symbol names sit in the shipped binary as plain
  strings where App Store static analysis looks. This is upstream c-ares behaviour on every Apple
  platform, and removing it would remove DNS discovery with it — but if your app is going
  through App Store review, know it is there.

- **iOS 14+ Local Network privacy can block the resolver you were handed.** iOS commonly
  reports the router's LAN address as a nameserver (a simulator run here got
  `192.168.178.1`), and querying an address on the local subnet needs
  [`NSLocalNetworkUsageDescription`](https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription)
  in `Info.plist` and the user's consent — see Apple's
  [TN3179](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy).
  The simulator does not enforce this, so it will not show up in simulator testing. Naming
  a public resolver explicitly sidesteps it.

## Build notes (maintainers)

### Recipe shape

A plain setuptools sdist with one CFFI extension, plus one patch. pycares'
[`setup.py`](https://github.com/saghul/pycares/blob/master/setup.py) builds the vendored
`deps/c-ares` with CMake before compiling the extension and links the resulting
`libcares.a` in through
[`extra_objects`](https://setuptools.pypa.io/en/latest/userguide/ext_modules.html), but its
`cmake_args` list is hardcoded and configures for the build host.
[`mobile.patch`](patches/mobile.patch) appends
`shlex.split(os.environ['FORGE_CMAKE_ARGS'])` last, so the toolchain arguments in
[`meta.yaml`](meta.yaml) win over the host defaults — including upstream's
`-DCMAKE_OSX_DEPLOYMENT_TARGET=10.12`.

That is the entire adaptation. Everything else falls out for free because `sys.platform` is
`android` / `ios` under the crossenv, so none of `setup.py`'s `darwin` / `linux` / `win32`
branches match: no `-lrt` on Android (bionic has no librt), no macOS deployment target on
iOS, and the shared defines (`HAVE_CONFIG_H`, `CARES_STATICLIB`) still apply.

[CFFI API mode](https://cffi.readthedocs.io/en/stable/overview.html#main-mode-of-usage) is
what makes this straightforward —
[`ffi.cdef`](https://cffi.readthedocs.io/en/stable/ref.html#ffi-cdef) is declarative and the
generated `_cares.c` is compiled by the cross compiler, so no host-side probing happens.

### Things that must stay true

- **`CARES_THREADS` must survive.** `import pycares` raises `RuntimeError` outright if
  [`ares_threadsafety()`](https://c-ares.org/docs/ares_threadsafety.html) is false, so a
  threadless c-ares is a dead wheel.
  [`test_import_initializes_thread_safe_cares`](tests/test_pycares.py) is the guard; check
  `Found Threads: TRUE` in the build log if it ever fails.
- **The CMake probes must run against the target.** `HAVE___SYSTEM_PROPERTY_GET` on Android
  and `HAVE_KQUEUE` / `HAVE_EPOLL` for the event thread are all configure-time. A build
  configured for the host produces a green wheel that fails at `Channel()` construction.
- **No extra link flags on either platform.** The iOS `libcares.a` resolves entirely against
  libSystem, and Android's needs only bionic. `HAVE_LIBRESOLV=1` is set on iOS and puts a
  cosmetic `-lresolv` in `libcares.pc` and the CMake export, but `CARES_USE_LIBRESOLV` is
  z/OS-only so no `res_*` symbol is ever referenced, and `setup.py` reads neither file.

### Re-verification checklist

- **Wheel hygiene:** correct `Machine` per ABI, every Android `LOAD` segment aligned
  `0x4000`, `DT_NEEDED` limited to `libc`/`libm`/`libdl` plus `libpython`, iOS
  `LC_BUILD_VERSION` platform 2 on device and 7 on the simulators, `otool -L` showing only
  libSystem and the Python framework.
- **METADATA:** `Requires-Dist: cffi` present; no `flet-*` promotion (there are no native
  deps).
- **On device:** [the recipe tests](tests/test_pycares.py), then the
  [`dns-lookup`](examples/dns-lookup) example against a real network — the tests are
  deliberately network-free, so they cannot catch a resolver that builds but cannot reach
  anything.

### Coverage gaps

[The device tests](tests/test_pycares.py) cover import (and with it `ares_library_init` and
the thread-safety gate), the servers round trip, the full
[`ares_strerror`](https://c-ares.org/docs/ares_strerror.html) table,
[`ares_inet_pton`](https://c-ares.org/docs/ares_inet_pton.html) validation,
argument validation, and one real query against a closed loopback port — which is what
exercises the event thread and the CFFI callback. They do not do a real lookup, do not
touch `search()`, `gethostbyaddr()` or `getnameinfo()`, and cannot assert anything about
system nameserver discovery, which differs per platform and per network. pycares exposes no
`ares_dns_parse`, so there is no way to push a canned wire packet through the parser
offline.
