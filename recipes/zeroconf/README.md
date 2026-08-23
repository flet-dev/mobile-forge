# zeroconf

[`zeroconf`](https://python-zeroconf.readthedocs.io/en/latest/) is a complete mDNS and DNS-SD
implementation — the protocol behind Bonjour and Avahi. It answers the question no HTTP
request can: what is on this Wi-Fi network right now. Printers, AirPlay receivers,
Chromecasts and other copies of your own app announce themselves on a multicast address, and
`zeroconf` both listens for those announcements and makes one on your behalf — no server, no
account, no address typed in by the user.

What decides whether any of this works is not the library: both mobile platforms restrict
multicast, differently, and one restriction cannot be satisfied from `pyproject.toml` at all.

## Install

```toml
dependencies = [
    "flet",
    "zeroconf",
]

[tool.flet.android.permission]
"android.permission.CHANGE_WIFI_MULTICAST_STATE" = true

[tool.flet.ios.info]
NSLocalNetworkUsageDescription = "This app finds printers and speakers on your network."
NSBonjourServices = ["_ipp._tcp", "_http._tcp"]
```

The Android [permission](https://flet.dev/docs/publish/android/#permissions) is
[protection level `normal`](https://developer.android.com/reference/android/Manifest.permission#CHANGE_WIFI_MULTICAST_STATE)
— install-time, no prompt — and permits the code under [Android](#android). The iOS keys drive
the local-network privacy prompt;
[`NSBonjourServices`](https://developer.apple.com/documentation/bundleresources/information-property-list/nsbonjourservices)
must name every type the app browses, as bare `_type._proto` with no `.local.` suffix — `flet
build` takes arrays there as well as strings, booleans and numbers. iOS needs one thing more
that no `pyproject.toml` entry expresses; see [iOS](#ios).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`service-browser`](examples/service-browser) — advertises the device and lists the mDNS
  services answering on the network, with the platform's multicast verdict on screen.

## Usage in a Flet app

Browsing is a callback API: create one `Zeroconf`, hand a
[`ServiceBrowser`](https://python-zeroconf.readthedocs.io/en/latest/api.html) the types you
care about, and resolve each name into an address and port.

```python
from zeroconf import ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

def on_change(zeroconf, service_type, name, state_change, **kwargs):
    if state_change is ServiceStateChange.Added:
        info = zeroconf.get_service_info(service_type, name, timeout=3000)
        page.run_thread(lambda: show(name, info.parsed_scoped_addresses(), info.port))

zc = Zeroconf()
browser = ServiceBrowser(zc, ["_ipp._tcp.local."], handlers=[on_change])
zc.register_service(ServiceInfo(  # advertise this device on the same instance
    "_myapp._tcp.local.", "Living room._myapp._tcp.local.",
    addresses=[socket.inet_aton(lan_ip)], port=8080,
    properties={"version": "1"}, server="myapp-1.local.",
))
```

Finish with `zc.unregister_all_services()` and `zc.close()`.

### Threading

`zeroconf` brings its own threads and none belong to Flet. `Zeroconf()` constructed in under
2 ms on a macOS desktop and started a daemon thread running an asyncio loop; each
`ServiceBrowser` starts another. **Your handler runs on the browser's thread**, which carries
no Flet context, so it must not touch a control. Hand the UI work back with
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — it posts
through the session's event loop with `call_soon_threadsafe`, so it is safe from any thread —
and end that function with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), which a background
thread never gets for free. `run_thread` drops the future it creates, so an exception in the
body surfaces nowhere you can see it: catch inside.

The blocking calls belong in `run_thread` behind a spinner, not in an event handler.
`register_service()` probes for a name clash before announcing: 1.7 s on that same desktop.
`get_service_info()` blocks up to its timeout, given in milliseconds — `3000`, its default, is
three seconds — and returns `None` when no reply arrives, an expected outcome rather than an
error. And because `run_thread` hands work to a pool, two quick taps can run start and stop at
once and leave an advertisement live after the app believes it stopped: serialise them behind
one lock, since a disabled button is feedback rather than a guard. For an `async` app,
`zeroconf.asyncio.AsyncZeroconf` is the same functionality against your own loop; this recipe's
tests do not exercise it.

### Android

Sending works out of the box. **Receiving does not, on many devices, until something holds a
[`WifiManager.MulticastLock`](https://developer.android.com/reference/android/net/wifi/WifiManager.MulticastLock).**
The Wi-Fi stack discards frames not addressed to this device, which is every announcement
every other device makes; the lock turns that filter off. The manifest half is the permission
above; the other half is code, reachable through [`pyjnius`](../pyjnius):

```python
import os

from jnius import autoclass

host = autoclass(os.getenv("MAIN_ACTIVITY_HOST_CLASS_NAME"))
context = host.mActivity.getApplicationContext()
wifi = context.getSystemService(autoclass("android.content.Context").WIFI_SERVICE)
lock = wifi.createMulticastLock("mdns")
lock.setReferenceCounted(True)
lock.acquire()
```

Keep a reference to `lock` while you want to receive — letting it be collected is the same as
releasing it — and release it when browsing stops, because an unfiltered Wi-Fi receiver costs
battery. Guard the import on `os.getenv("FLET_JNI_READY") == "1"`, and declare pyjnius under
[`[tool.flet.android] dependencies`](https://flet.dev/docs/publish/#app-dependencies).

Failure without the lock is silent and device-dependent: the advertisement still goes out,
`Zeroconf()` still constructs, and the callback simply never fires. An emulator reproduces
neither the problem nor the fix, its network being the emulator's NAT rather than a Wi-Fi
driver. Android's own `NsdManager` needs no lock, but it reports through a Java listener
interface — and implementing a Java interface from Python is the one thing pyjnius cannot do
in a Flet app.

### iOS

**A device requires an entitlement a Flet build cannot currently produce, and nothing you can
run will show you that.** Apple's
[TN3179](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy)
puts sending and receiving UDP multicast in the column requiring
[`com.apple.developer.networking.multicast`](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.networking.multicast),
covers BSD Sockets as well as Network framework — sockets are what `zeroconf` uses — and adds
that browsing arbitrary or all-advertised service types needs it too. It also records that the
entitlement is not required on macOS and that the simulator does not support local network
privacy, so a green simulator run says nothing about a phone.

Nor is it a checkbox. Apple's reference says the entitlement requires permission from Apple
before it can be used — a form behind the developer login, granted to the team rather than to
one App ID — after which it is applied through signing, from Xcode's capabilities editor under
automatic signing or from a provisioning profile that carries it. Flet 0.86.5 cannot express it
either: `flet build` reads `[tool.flet.macos.entitlement]` and writes a macOS entitlements file,
the CLI has no iOS counterpart to that key, and `[tool.flet.ios.info]` reaches `Info.plist`
only. An approved developer still has to add the entitlement in the generated Xcode project,
outside the `flet build` flow. The two `Info.plist` keys above buy the local-network privacy
prompt, which the platform wants in addition to the entitlement rather than instead of it.

Whatever a blocked send raises, it raises on zeroconf's own threads, so an app denied multicast
looks exactly like an app on a quiet network — build the UI so the two can be told apart. No
test here has run on an iOS device, so that failure mode comes from Apple's documentation
rather than from anything this recipe observed. If real devices matter more than this package,
the entitlement-free route is the system's own Bonjour APIs, where discovery happens in the OS
instead of in your process: a different API, reached through [`pyobjus`](../pyobjus), browsing
only the service types you declare.

### App size

The wheel is approximately 1.5–1.7 MB compressed and 3.0–5.2 MB unpacked per architecture,
across the Android arm64-v8a, armeabi-v7a and x86_64 slices and the iOS device slice. Around
nine tenths of the unpacked bytes are eighteen compiled accelerator extensions, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
worth removing. On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI; packaging and compression decide what reaches the APK.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel of the same version, with the same Python API.
The environment is not the same: a laptop has no multicast filter and no entitlement check, so
discovery that works perfectly there tells you nothing about either phone.

## Things to know

- **The handler is called entirely by keyword, so its first parameter must be named
  `zeroconf`.** Name it `zc` and the browser thread dies on the first result with
  `TypeError: on_change() missing 1 required positional argument: 'zc'` — naming your parameter,
  not the one it wanted, on stderr rather than anywhere on screen.

- **`ip_version` picks the sockets, not what comes back in the records.**
  `Zeroconf(ip_version=IPVersion.V4Only)` opens IPv4 sockets, but a resolved `ServiceInfo`
  still carries every address the other device advertised, and
  [`parsed_scoped_addresses()`](https://python-zeroconf.readthedocs.io/en/latest/api.html)
  defaults to `IPVersion.All`. A printer on the test network answered with one IPv4 address and
  three IPv6 ones — one link-local, one unique-local and one global. Pass the version you want,
  or a phone screen fills with addresses the app cannot use.

- **TXT values are strings, or `None`.**
  [`ServiceInfo.decoded_properties`](https://python-zeroconf.readthedocs.io/en/latest/api.html)
  returns `dict[str, str | None]`: registering `properties={"n": 1}` and reading it back gives
  `'1'`, while a key with no value and a key with an empty value both give `None`. A TXT record
  that is one zero-length string — what a printer on the test network sends for `_http._tcp` —
  decodes to `{'': None}`, a single empty-string key. Drop empty keys and `None` values before
  displaying them.

- **Ask only for the service types you can use.** The DNS-SD meta-query
  `_services._dns-sd._udp.local.`, run from a macOS desktop, returned nineteen service types
  within two seconds — largely one router and one printer advertising several protocols each.
  That count belongs to that network, but the shape holds: enumerating everything costs radio
  time, and on iOS each type has to be declared in `NSBonjourServices` anyway.

- **Withdraw your advertisement before you exit.** `unregister_all_services()` sends a goodbye
  packet, about 250 ms on a macOS desktop; skip it and other devices keep offering a dead
  service until its TTL expires. A suspended app runs no code and refreshes no announcements,
  so tie discovery to
  [`page.on_app_lifecycle_state_change`](https://flet.dev/docs/controls/page/#flet.Page.on_app_lifecycle_state_change).
- **Licensing:** [LGPL-2.1-or-later](https://spdx.org/licenses/LGPL-2.1-or-later.html), including
  the compiled accelerators. Unlike most native recipes here it links no separate C library — the
  extension modules are Cython-compiled from zeroconf's own LGPL sources, so the licence covers
  the whole package rather than a dependency hiding behind it. For an open-source app that is the
  end of it. For a closed-source one, LGPL section 6 asks that a user be able to relink your app
  against their own build; compiled modules inside a signed APK or IPA do not offer that on their
  own, and section 6a (shipping your object files) is the usual answer where it matters. The
  licence text ships in the wheel under `dist-info/licenses/`. Flagging it, not advising you — we
  are not lawyers.

## Build notes (maintainers)

### Recipe shape

The package is Cython-accelerated pure Python: the modules under `zeroconf/` are themselves the
Cython sources with `.pxd` sidecars, generating self-contained C with no external library to
build first. Hence a plain `meta.yaml`, a `cython` build requirement, no `build.sh`.

One thing about the build is dangerous, and it is why `REQUIRE_CYTHON` and
`patches/require-cython-fail-loud.patch` both exist: upstream treats the extensions as optional
and catches compile errors, so a failed cross-compile can still produce a green build and a
silently pure-Python wheel. The patch preamble owns the mechanism; what follows is that
`tests/test_zeroconf.py::test_cython_extensions_compiled` is load-bearing.

`ifaddr` is a runtime dependency with its own recipe here, carrying an iOS fix PyPI's wheel
lacks. Building `zeroconf` in CI without prebuilding `ifaddr` lets a resolve pick the unpatched
wheel, and on iOS that produces an empty adapter list rather than an error.

### Upgrade hazards

- **`build_ext.py` is the patch target.** A restructure of it upstream, or a move off the
  `poetry-core` build-script hook, silently turns the patch into a green build with no
  extensions in the wheel.
- **`Requires-Dist: ifaddr (>=0.1.7)` is a floor that can rise** past the version the `ifaddr`
  recipe builds, which breaks mobile resolution. Bump both together.
- **`zeroconf/_services/__init__` ships as a native extension** — a package whose `__init__`
  *is* the `.so`. It loads on both platforms with the serious_python Flet currently ships; if
  that regresses, the import error names `zeroconf._services` and the fallback is a one-line
  patch dropping the module from `TO_CYTHONIZE`.

### Re-verification checklist

- **Eighteen compiled extensions per slice**, and a deliberate compile break to confirm the
  patch still turns it into a red build rather than a pure-Python wheel.
- **The platform claims, re-read from their sources.** TN3179, the multicast entitlement
  reference, Android's `MulticastLock` page, and the absent iOS entitlement key read off flet
  0.86.5's `build_base.py` are consumer-facing facts that can change without anything failing.
  Confirm too that `flet build` still accepts array `Info.plist` values, since
  `NSBonjourServices` is a list.
- **Size:** re-measure from the built wheels rather than scaling these figures.

### Coverage gaps

The device tests cover the compiled-extension origins, a DNS wire-format round trip through the
compiled codecs, `ifaddr` enumeration, `Zeroconf` construction and shutdown, and a same-process
register-and-browse cycle over real multicast sockets. They have run on an Android emulator and
an iOS simulator, and neither is evidence for what the package is for: no test has discovered a
second device on a real LAN, exercised the `MulticastLock` path, or run on an iOS device with
the entitlement. IPv6, `AsyncZeroconf` and goodbye packets seen from a second host are
untested.
