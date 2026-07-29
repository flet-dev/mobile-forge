import socket
import threading


def test_import():
    """zeroconf imports and exposes its primary public API classes."""
    from zeroconf import (  # noqa: F401
        IPVersion,
        ServiceBrowser,
        ServiceInfo,
        ServiceListener,
        Zeroconf,
    )


def test_cython_extensions_compiled():
    """The Cython accelerator modules are real compiled extensions, not the
    pure-Python fallback (upstream's build swallows compile errors by design,
    so a broken cross-compile would otherwise ship silently as pure Python).
    zeroconf._services is a subpackage whose __init__ IS the native extension,
    which also exercises serious-python's native-__init__ loading path."""
    import zeroconf._cache
    import zeroconf._dns
    import zeroconf._protocol.incoming
    import zeroconf._protocol.outgoing
    import zeroconf._services
    import zeroconf._services.browser
    import zeroconf._utils.time

    for mod in (
        zeroconf._dns,
        zeroconf._cache,
        zeroconf._protocol.incoming,
        zeroconf._protocol.outgoing,
        zeroconf._services,
        zeroconf._services.browser,
        zeroconf._utils.time,
    ):
        origin = mod.__spec__.origin
        assert origin and not origin.endswith(".py"), (
            f"{mod.__name__} loaded from {origin!r} — pure-Python fallback, "
            "the compiled extension is missing or was not used"
        )


def test_dns_wire_roundtrip():
    """DNS records survive serialization to mDNS wire format and back —
    exercises the compiled outgoing/incoming protocol codecs without any
    network access."""
    from zeroconf import const, current_time_millis
    from zeroconf._dns import DNSPointer, DNSText
    from zeroconf._protocol.incoming import DNSIncoming
    from zeroconf._protocol.outgoing import DNSOutgoing

    type_ = "_forgetest._tcp.local."
    name = "wire-roundtrip._forgetest._tcp.local."
    now = current_time_millis()

    out = DNSOutgoing(const._FLAGS_QR_RESPONSE | const._FLAGS_AA)
    out.add_answer_at_time(
        DNSPointer(type_, const._TYPE_PTR, const._CLASS_IN, const._DNS_OTHER_TTL, name),
        now,
    )
    out.add_answer_at_time(
        DNSText(
            name,
            const._TYPE_TXT,
            const._CLASS_IN | const._CLASS_UNIQUE,
            const._DNS_OTHER_TTL,
            b"\x09forge=yes",
        ),
        now,
    )

    packets = out.packets()
    assert packets, "DNSOutgoing produced no packets"

    parsed = DNSIncoming(packets[0])
    assert parsed.valid, "round-tripped packet failed to parse"
    answers = parsed.answers()
    names = {answer.name for answer in answers}
    assert type_ in names and name in names, names
    texts = [a for a in answers if a.type == const._TYPE_TXT]
    assert texts and texts[0].text == b"\x09forge=yes"


def test_ifaddr_enumerates_adapters():
    """zeroconf's interface-enumeration dependency (ifaddr, ctypes getifaddrs)
    can list at least one adapter with an IP address on this platform."""
    import ifaddr

    adapters = ifaddr.get_adapters()
    assert adapters, "ifaddr.get_adapters() returned no adapters"
    assert any(adapter.ips for adapter in adapters), "no adapter has any IP address"


def test_socket_lifecycle():
    """A Zeroconf instance can be constructed (opens multicast sockets and sets
    the mDNS socket options) and shut down cleanly."""
    from zeroconf import IPVersion, Zeroconf

    zc = Zeroconf(ip_version=IPVersion.V4Only)
    try:
        assert zc.started
    finally:
        zc.close()


def test_register_and_browse_loopback():
    """A service registered by one Zeroconf instance is discovered by a browser
    on a second instance in the same process — a full register/announce/query/
    response cycle over real multicast sockets, no external network required
    (mDNS multicast loops back on the local host)."""
    from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

    type_ = "_forgetest._tcp.local."
    svc_name = "zc-recipe-test._forgetest._tcp.local."

    found = threading.Event()

    def on_change(zeroconf, service_type, name, state_change, **kwargs):
        if state_change is ServiceStateChange.Added and name == svc_name:
            found.set()

    server = Zeroconf(ip_version=IPVersion.V4Only)
    client = Zeroconf(ip_version=IPVersion.V4Only)
    browser = None
    try:
        info = ServiceInfo(
            type_,
            svc_name,
            addresses=[socket.inet_aton("127.0.0.1")],
            port=8080,
            properties={"from": "mobile-forge"},
            server="zc-recipe-test.local.",
        )
        server.register_service(info)
        browser = ServiceBrowser(client, type_, handlers=[on_change])
        assert found.wait(timeout=20), "registered service was not discovered within 20s"
    finally:
        if browser is not None:
            browser.cancel()
        server.unregister_all_services()
        client.close()
        server.close()
