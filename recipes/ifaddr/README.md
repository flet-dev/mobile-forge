# ifaddr

[`ifaddr`](https://github.com/pydron/ifaddr) enumerates the network interfaces a machine has
and the IP addresses configured on each of them. It is pure Python: one `getifaddrs` call
through [`ctypes`](https://docs.python.org/3/library/ctypes.html), with the returned C
structures walked by hand, so the answer comes from the kernel rather than from the network.

In a Flet app it answers the questions that come before a socket does — what address another
device on this Wi-Fi could reach you at, whether there is a usable network at all, and
whether the one you had a second ago is still there.

## Install

```toml
dependencies = [
    "flet",
    "ifaddr",
]
```

The wheels published for mobile carry a one-line iOS fix that PyPI's pure-Python wheel does
not. The symptom of ending up on the unpatched code is silent and specific:
[`get_adapters()`](https://github.com/pydron/ifaddr#lets-get-going) returns an empty list on
iOS and raises nothing.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`interface-list`](examples/interface-list) — lists every interface with its addresses and
  logs each one as it appears or disappears.

## Usage in a Flet app

One call, two loops, and the values are ready for a control:

```python
import ifaddr

for adapter in ifaddr.get_adapters():
    for ip in adapter.ips:
        if ip.is_IPv4:
            print(adapter.name, ip.ip, ip.network_prefix)
```

Most apps want a single answer out of that — the address to put in a QR code, a service
advertisement or a "connect to me at" label:

```python
import ipaddress

lan = [
    ip.ip
    for adapter in ifaddr.get_adapters()
    for ip in adapter.ips
    if ip.is_IPv4 and not ipaddress.ip_address(ip.ip).is_loopback
]
page.add(ft.Text(lan[0] if lan else "no network"))
```

### Reading a result

`get_adapters()` returns a dictionary view, not a list. Iterate it; `adapters[0]` raises
`TypeError: 'odict_values' object is not subscriptable`.

Each `Adapter` carries `name`, `nice_name` (the same string on both mobile platforms),
`index` — the interface index from `socket.if_nametoindex`, which an IPv6 multicast join
needs — and `ips`. Passing `include_unconfigured=True` also returns interfaces that have no
address; on a macOS desktop that took the count from 11 to 25.

**`IP.ip` is not one type.** For IPv4 it is a string; for IPv6 it is an
`(address, flowinfo, scope_id)` triple, so formatting it without checking `is_IPv4` /
`is_IPv6` prints `('fe80::1', 0, 14)`. The scope id is the interface index, and an `fe80::`
address is unusable without it.

Interface flags are not exposed — `ifa_flags` is in the structure ifaddr parses and never
reaches the result — so questions like "is this loopback?" are answered from the address:

```python
obj = ipaddress.ip_address(ip.ip[0] if ip.is_IPv6 else ip.ip)
kind = "loopback" if obj.is_loopback else "link-local" if obj.is_link_local else "routable"
```

### Threading

A scan is one blocking libc call, fast enough for the UI thread: about 0.5 ms per call over
a warm loop on a macOS desktop with 25 interfaces. The example reports the figure it
measures on the device it is running on.

What needs care is that nothing tells you when the answer changes. Watching for a network
coming or going means polling, and the loop belongs in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — which
holds a pool thread for as long as it runs, discards any exception its body raises, and does
not auto-update, so catch inside the loop and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). Polling is not
just ifaddr's limitation: from Android 11 an app may not `bind()` a `NETLINK_ROUTE` socket
either, so there is no lower-level notification to drop down to.

Treat every result as a snapshot. An address can disappear between the scan and the
`bind()`, so handle the socket error rather than trusting a cached string.

### Loopback is a legitimate answer

The only address a device is guaranteed to have is its own loopback. A phone in airplane
mode, one whose Wi-Fi has not associated yet, or one waiting on a captive portal has nothing
else to offer, and `get_adapters()` reports that calmly rather than raising — which is why
the recipe's device tests assert only that some adapter has some address and that
`127.0.0.1` is among them.

An emulator will not show you that state. With airplane mode enabled on an API 35 arm64
emulator, an app still received `eth0` carrying `10.0.2.15` — the NAT interface the emulator
machinery owns, which no setting inside Android takes down — alongside `lo` and a `dummy0`
link-local. Only `wlan0` disappeared. The address looks like a LAN address and routes
nowhere useful, so the branch that matters is the one an emulator will never reach. Write
that branch of the UI first.

### App size

The wheel is 12 KB and unpacks to 26 KB. All eighteen published wheels carry a
byte-identical payload of the same six Python modules and differ only in metadata — eleven
bytes between the smallest and the largest — so the figure does not move when an ABI or a
Python version is added or dropped.

### Android

Enumeration needs no [permission](https://flet.dev/docs/publish/android/#permissions):
`getifaddrs` is a bionic call rather than a framework API, and the recipe's on-device test
enumerates adapters from a stock Flet manifest with nothing added to it.

What Android withholds is everything below the IP layer. From Android 11, `getifaddrs()`
shows a non-privileged app
[only the interfaces that have an IP address](https://developer.android.com/training/articles/user-data-ids#mac-11-plus),
and no hardware addresses. The gap is wide. The same `getifaddrs()` probe on an API 35 arm64
emulator returned 26 entries spanning 16 interfaces when run from `adb shell`, and 10 entries
spanning 4 when run under an app's own uid; everything the shell saw and the app did not was
an interface with no address. So `include_unconfigured=True` has nothing extra to report on
Android, and a MAC address is out of reach twice over — the OS withholds it, and ifaddr's
parser understands `AF_INET` and `AF_INET6` and drops every other family before it reaches
the API.

Do not size your UI for a long list: what reaches the app is short. The names that do arrive
are Linux names — `lo`, `dummy0`, `eth0` and `wlan0` on that emulator — and they are not an
API. A phone adds cellular and VPN interfaces under names that vary by vendor and Android
version. Decide what an address is good for from the address, not from the name it arrived
under.

### iOS

**The iOS runtime reports `platform.system() == "iOS"`, not `"Darwin"`.** ifaddr chooses
between two `sockaddr` layouts from that string, and the Darwin layout — a leading length
byte, then a one-byte address family — is the correct one for iOS. Reading Darwin structures
with the Linux layout puts the family field in the wrong place, no address ever matches
`AF_INET` or `AF_INET6`, and `get_adapters()` returns an empty list without raising. Forcing
that mismatch on a macOS desktop reproduces it exactly: 11 adapters become 0. The mobile
wheels fix it, and on both platforms the recipe's on-device tests find real adapters with
real addresses.

**A simulator is the Mac.** Running `ifconfig` inside a booted iPhone simulator returned the
host's 25 interfaces in the host's order, and `ifconfig en0` was byte-for-byte identical to
the host's — same Wi-Fi address, same five IPv6 addresses, same flags. Whatever a simulator
shows you — an AirDrop interface, a virtual-machine bridge, a corporate VPN — belongs to the
laptop. Interface names and the presence of a cellular address have to be checked on
hardware.

### Other considerations

A desktop `flet run` uses PyPI's pure-Python wheel, which differs from the mobile ones by
exactly the one line of the platform gate above, so the behaviour matches. The *result* does
not: a workstation reports VPNs, bridges and container networks that no phone has, and it
always has a routable address. Neither a workstation nor an emulator will hand you the empty
or loopback-only case, so exercise those branches by making `get_adapters()` return them.

## Things to know

- **An interface with several addresses is normal, and IPv6 is most of them.** One Wi-Fi
  interface on a dual-stack network reported six addresses in a desktop measurement: one
  IPv4, one link-local, one unique-local and three global IPv6 addresses, two of them
  privacy addresses. Pick by scope, not by position.

- **The `netifaces` compatibility shim has exactly one function.** `from ifaddr import
  netifaces` — a plain `import ifaddr` leaves `ifaddr.netifaces` an `AttributeError` — gives
  you `interfaces()`, returning adapter names. Code ported from `netifaces` that calls
  `ifaddresses()` or `gateways()` needs rewriting against `get_adapters()`; routing and
  gateway information is outside what ifaddr collects.

- **Nothing here tells you what kind of network you are on.** Wi-Fi versus cellular, metered
  versus not, connected versus merely configured — those are platform questions, reachable
  through [`pyjnius`](../pyjnius) on Android and [`pyobjus`](../pyobjus) on iOS. An address
  in the list is not a promise that packets go anywhere.

## Build notes (maintainers)

### Recipe shape

A pure-Python package gets a recipe here for one reason: to ship a patched wheel. The fix is
a single line in `ifaddr/_shared.py` and cannot be applied from an app, so the recipe builds
the sdist into platform-tagged wheels, which outrank PyPI's `py3-none-any` at equal version.
Consumers get the fix without opting in.

That mechanism has a cost worth naming: it works only while the recipe's version keeps up. A
newer ifaddr on PyPI that this recipe has not been bumped to is a version a resolver may
prefer, and it carries no fix. The patch preamble owns the explanation of the bug;
`meta.yaml` owns the `setuptools` build requirement. Do not restate either here.

### Upgrade hazards

- **Check whether upstream has taken the fix.** If a release selects the BSD layout for
  `"iOS"` on its own, this recipe's reason to exist is gone and it should be deleted rather
  than carried — but confirm on an iOS device first, because the failure it prevents is
  silent.
- **Watch `_posix.py`.** It loads libc through `ctypes.util.find_library("c")`, which
  resolves differently on Android than on a desktop. A rewrite of that line is a
  device-test-before-merge change, not a version bump.

### Re-verification checklist

- **The patch still applies where it matters:** confirm the built wheel's `_shared.py`
  selects the BSD layout for `"iOS"`, and that the Flet iOS runtime still reports `"iOS"`.
  If that string ever becomes `"Darwin"`, the patch turns into a harmless no-op rather than
  a failure.
- **Non-empty results on both platforms.** A wrong layout raises nothing, so a successful
  import proves nothing at all; only an assertion on the contents of `get_adapters()` does.
- **Size:** re-measure the compressed and unpacked figures from the wheels rather than
  scaling these.

### Coverage gaps

The device tests assert that at least one adapter carries an address and that `127.0.0.1` is
among the IPv4 addresses. Nothing asserts IPv6 parsing, a routable LAN address,
`include_unconfigured`, `Adapter.index` or the `netifaces` shim.

Neither platform has been exercised on physical hardware. The Android run is an emulator and
the iOS run is a simulator sharing the host Mac's network stack — which still exercises the
layout fix, because the platform string comes from the iOS runtime while the ABI is Darwin's,
but it means no cellular interface has ever been enumerated by this recipe.
