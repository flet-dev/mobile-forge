def test_adapters_have_ips():
    """getifaddrs-backed enumeration finds at least one adapter carrying an IP
    address — proves the sockaddr ctypes layout matches the platform ABI (the
    iOS runtime reports platform.system() == "iOS", which upstream ifaddr
    mis-classifies as Linux-layout, yielding zero adapters)."""
    import ifaddr

    adapters = list(ifaddr.get_adapters())
    assert adapters, "ifaddr.get_adapters() returned no adapters"
    ips = [ip for adapter in adapters for ip in adapter.ips]
    assert ips, "no adapter has any IP address"


def test_loopback_visible():
    """The IPv4 loopback address is among the enumerated IPs — a concrete
    parse-correctness check (a wrong struct layout can't produce 127.0.0.1)."""
    import ifaddr

    all_v4 = [
        ip.ip
        for adapter in ifaddr.get_adapters()
        for ip in adapter.ips
        if ip.is_IPv4
    ]
    assert "127.0.0.1" in all_v4, all_v4
