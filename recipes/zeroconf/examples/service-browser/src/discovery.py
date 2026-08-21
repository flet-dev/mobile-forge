import os
import platform
import socket
import sys
import threading
from typing import NamedTuple

import ifaddr
from zeroconf import (
    IPVersion,
    ServiceBrowser,
    ServiceInfo,
    ServiceStateChange,
    Zeroconf,
    __version__,
)

RUNTIME = (
    f"platform.system() = {platform.system()!r} · Python {platform.python_version()}"
    f" · zeroconf {__version__}"
)

OWN_TYPE = "_flet-demo._tcp.local."
OWN_PORT = 8080

# Service types worth asking about on a home or office network. The first one is
# this app itself, so there is always something to find even where nothing else
# answers.
BROWSE_TYPES = {
    OWN_TYPE: "Flet app",
    "_ipp._tcp.local.": "Printer",
    "_printer._tcp.local.": "Printer (LPD)",
    "_airplay._tcp.local.": "AirPlay",
    "_raop._tcp.local.": "AirPlay speaker",
    "_googlecast._tcp.local.": "Chromecast",
    "_http._tcp.local.": "Web interface",
}

_lock = threading.Lock()
# start() and stop() are serialised: page.run_thread hands work to a pool, so a
# fast double-tap of the switch can otherwise overlap them and leave an
# advertisement live with the switch off.
_control = threading.Lock()
_found = {}
_state = {
    "advertiser": None,
    "browser": None,
    "client": None,
    "name": "",
    "wifi": None,
    "notify": lambda: None,
}


class Service(NamedTuple):
    """One discovered service, reduced to values a control can display."""

    name: str
    kind: str
    server: str
    port: int
    addresses: list
    properties: dict
    is_self: bool


def is_android():
    """True on Android.

    `platform.system()` answers "Linux" before CPython 3.13 and "Android" from
    3.13, so the attribute is the tell that works on every version.
    """
    return hasattr(sys, "getandroidapilevel")


def lan_address():
    """The IPv4 address to advertise, or None when the device has no network.

    zeroconf's own `get_all_addresses()` is deprecated in favour of asking
    ifaddr — the interface enumerator zeroconf is built on — directly. It reads
    the interface list straight from the C library, so it costs about a
    millisecond and needs no network: the app can show an answer on its first
    frame.
    """
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if ip.is_IPv4 and not ip.ip.startswith("127."):
                return ip.ip
    return None


def acquire_multicast_lock():
    """Take Android's `WifiManager.MulticastLock`, and say what happened.

    Android's Wi-Fi stack discards incoming frames that are not addressed to
    this device, which is every mDNS announcement any other device makes. The
    lock turns that filter off. `pyproject.toml` can declare the permission it
    needs; acquiring it is code, and the Java API is reachable only through
    pyjnius, so this returns a status string rather than raising — an app that
    cannot take the lock still sends fine and may still receive on some devices.

    The lock is parked in a module global because letting it be collected is
    the same as releasing it.
    """
    if not is_android():
        return "no multicast lock applies on this platform"
    if os.getenv("FLET_JNI_READY") != "1":
        return "pyjnius unavailable — incoming multicast may be filtered"
    try:
        from jnius import autoclass

        host = os.getenv("MAIN_ACTIVITY_HOST_CLASS_NAME")
        context = autoclass(host).mActivity.getApplicationContext()
        service = autoclass("android.content.Context").WIFI_SERVICE
        lock = context.getSystemService(service).createMulticastLock("flet-mdns")
        lock.setReferenceCounted(True)
        lock.acquire()
        _state["wifi"] = lock
        return "MulticastLock acquired"
    except Exception as exc:
        return f"MulticastLock unavailable: {exc}"


def platform_note():
    """The one thing that decides whether discovery can work on this platform."""
    if is_android():
        return acquire_multicast_lock()
    if platform.system() == "iOS":
        return (
            "iOS: a simulator does not enforce the multicast entitlement, "
            "a device does"
        )
    return "desktop: nothing gates multicast here"


def _describe(service_type, name, info):
    """Turn a resolved `ServiceInfo` into a `Service`.

    Two fields need help. TXT values arrive as `str`, or as `None` for a key
    carrying no value — a printer on the test network answered
    `_http._tcp` with an empty TXT record, which decodes to a single
    empty-string key — so both shapes are dropped before the UI sees them.
    And `parsed_scoped_addresses()` defaults to `IPVersion.All`: asking for
    V4-only sockets does not filter what other devices put in their own
    records, and the same printer offers three IPv6 addresses to go with its
    one IPv4.
    """
    instance = name[: -len(service_type) - 1] if name.endswith(service_type) else name
    properties = {
        key: value
        for key, value in info.decoded_properties.items()
        if key and value is not None
    }
    return Service(
        name=instance,
        kind=BROWSE_TYPES.get(service_type, service_type),
        server=info.server or "",
        port=info.port or 0,
        addresses=info.parsed_scoped_addresses(IPVersion.V4Only),
        properties=properties,
        is_self=name == _state["name"],
    )


def _on_change(zeroconf, service_type, name, state_change, **kwargs):
    """Record one change, then tell the app.

    Every argument is passed by keyword, so the first parameter has to be named
    `zeroconf` however little the name suits it. The call arrives on the
    `ServiceBrowser`'s own thread — not the Flet UI thread and not zeroconf's
    event loop — so `get_service_info` may block here to fetch the SRV and TXT
    records the browser has so far only learned the name of.
    """
    if state_change is ServiceStateChange.Removed:
        with _lock:
            _found.pop(name, None)
    else:
        info = zeroconf.get_service_info(service_type, name, timeout=3000)
        if info is not None:
            with _lock:
                _found[name] = _describe(service_type, name, info)
    _state["notify"]()


def start(notify):
    """Advertise this device, browse for everything in `BROWSE_TYPES`, and
    return the advertised name with a note about this platform.

    Two `Zeroconf` instances rather than one: the advertisement is published by
    the first and discovered by the second, so it has to leave a multicast
    socket and come back in. That round trip proves the library and the sockets
    work — but a host loops its own multicast back internally, above the Wi-Fi
    driver, so it proves nothing about frames sent by other devices. Only a
    second device on the network answers that question.

    `register_service()` blocks while it probes for a name clash and announces:
    about 1.7 s measured on a macOS desktop, which is why the caller runs this
    on a background thread.
    """
    with _control:
        _state["notify"] = notify
        note = platform_note()
        address = lan_address() or "127.0.0.1"
        instance = f"Flet on {platform.system()} {os.getpid()}"
        name = f"{instance}.{OWN_TYPE}"

        advertiser = Zeroconf(ip_version=IPVersion.V4Only)
        client = Zeroconf(ip_version=IPVersion.V4Only)
        _state.update(advertiser=advertiser, client=client, name=name)
        advertiser.register_service(
            ServiceInfo(
                OWN_TYPE,
                name,
                addresses=[socket.inet_aton(address)],
                port=OWN_PORT,
                properties={"app": "service-browser", "address": address},
                server=f"flet-{os.getpid()}.local.",
            )
        )
        _state["browser"] = ServiceBrowser(
            client, list(BROWSE_TYPES), handlers=[_on_change]
        )
        return instance, note


def stop():
    """Withdraw the advertisement, close both instances and release the lock.

    Closing matters more on a phone than on a desktop: the sockets, the two
    event-loop threads and — on Android — the battery cost of an unfiltered
    Wi-Fi receiver all live until this runs. `unregister_all_services()` sends
    the goodbye packet that stops other devices offering a service that has
    gone; it took about 250 ms on a macOS desktop.
    """
    with _control:
        if _state["browser"] is not None:
            _state["browser"].cancel()
        if _state["advertiser"] is not None:
            _state["advertiser"].unregister_all_services()
            _state["advertiser"].close()
        if _state["client"] is not None:
            _state["client"].close()
        if _state["wifi"] is not None:
            _state["wifi"].release()
        _state.update(
            advertiser=None,
            client=None,
            browser=None,
            wifi=None,
            name="",
            notify=lambda: None,
        )
        with _lock:
            _found.clear()


def snapshot():
    """The services found so far, this app first and the rest by name."""
    with _lock:
        found = list(_found.values())
    return sorted(found, key=lambda s: (not s.is_self, s.kind, s.name.lower()))
