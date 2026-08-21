import ipaddress
import platform
import time
from typing import NamedTuple, Optional

import ifaddr

VERSION = (
    f"platform.system() = {platform.system()!r}  ·  Python {platform.python_version()}"
)


class Address(NamedTuple):
    """One IP address of one interface, reduced to printable values."""

    family: str
    text: str
    prefix: int
    kind: str


class Interface(NamedTuple):
    """One network interface and the addresses currently configured on it."""

    name: str
    index: Optional[int]
    addresses: list


def classify(obj):
    """Name the scope of an address the way a reader thinks about it.

    ifaddr reports no interface flags — `ifa_flags` is in the struct it parses but
    never reaches the API — so "is this loopback?" cannot be asked of the adapter
    and has to be answered from the address itself.
    """
    if obj.is_loopback:
        return "loopback"
    if obj.is_link_local:
        return "link-local"
    if obj.is_global:
        return "global"
    return "private"


def scan(include_unconfigured=False):
    """Enumerate the interfaces, and return them with the milliseconds it took.

    Everything awkward about the API is handled here. `get_adapters()` returns a
    dict view rather than a list, so it is iterated and never indexed. `IP.ip` is a
    plain string for IPv4 but a `(address, flowinfo, scope_id)` triple for IPv6, so
    the two families cannot share a formatting path — and a link-local IPv6 address
    is unusable without the scope id, which is why it is printed alongside.

    The whole scan is one `getifaddrs` call through ctypes: about 0.5 ms per call
    over a warm loop on a macOS desktop with 25 interfaces, which is why the app
    calls it on the UI thread and reports its own figure on device.
    """
    started = time.perf_counter()
    adapters = list(ifaddr.get_adapters(include_unconfigured=include_unconfigured))
    elapsed = (time.perf_counter() - started) * 1000

    found = []
    for adapter in adapters:
        addresses = []
        for ip in adapter.ips:
            raw = ip.ip[0] if ip.is_IPv6 else ip.ip
            obj = ipaddress.ip_address(raw)
            text = raw
            if ip.is_IPv6 and ip.ip[2]:
                text = f"{raw}%{ip.ip[2]}"
            addresses.append(
                Address(
                    family="IPv6" if ip.is_IPv6 else "IPv4",
                    text=text,
                    prefix=ip.network_prefix,
                    kind=classify(obj),
                )
            )
        found.append(Interface(adapter.name, adapter.index, addresses))
    return found, elapsed


def addresses_in(interface, family):
    """The interface's addresses of one family — or all of them, for "all"."""
    return [a for a in interface.addresses if family in ("all", a.family)]


def summarise(interfaces, elapsed):
    """Reduce a scan to one line of counts, and the time the call itself took."""
    v4 = sum(a.family == "IPv4" for i in interfaces for a in i.addresses)
    v6 = sum(a.family == "IPv6" for i in interfaces for a in i.addresses)
    return (
        f"{len(interfaces)} interfaces · {v4} IPv4 · {v6} IPv6 · "
        f"getifaddrs in {elapsed:.2f} ms"
    )


def lan_address(interfaces):
    """Return the IPv4 address another device on this network could reach, if any.

    This is the answer most apps came for — the one to put in a QR code or hand to
    a service advertisement. There is no guarantee it exists, so callers get None
    rather than a placeholder. An emulator hides that case: its `eth0` keeps
    10.0.2.15 even in airplane mode, so this returns an address that goes nowhere.
    """
    for interface in interfaces:
        for address in interface.addresses:
            if address.family == "IPv4" and address.kind in ("private", "global"):
                return address.text
    return None


def fingerprint(interfaces):
    """Reduce a scan to a comparable set of `name address/prefix` strings."""
    return {
        f"{interface.name} {address.text}/{address.prefix}"
        for interface in interfaces
        for address in interface.addresses
    }


def changes(before, after):
    """List what appeared and disappeared between two fingerprints."""
    return sorted(f"- {gone}" for gone in before - after) + sorted(
        f"+ {new}" for new in after - before
    )
