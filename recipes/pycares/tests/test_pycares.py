"""pycares wraps c-ares (vendored, statically linked into pycares/_cares*.so)
through CFFI. These tests stay off the network: everything either runs
in-process or talks to a loopback port with nothing listening on it."""

import threading

import pycares


def _noop_sock_state_cb(fd, readable, writable):
    """Suppresses the c-ares event thread so a channel stays inert."""


def test_import_initializes_thread_safe_cares():
    """Importing pycares runs ares_library_init() and hard-fails unless c-ares
    reports thread safety, so a successful import already proves the vendored
    library is the cross-compiled one and that CARES_THREADS survived."""
    assert isinstance(pycares.ARES_VERSION, str) and pycares.ARES_VERSION
    assert pycares.ARES_SOCKET_BAD == -1
    assert pycares.QUERY_TYPE_A != pycares.QUERY_TYPE_AAAA


def test_servers_roundtrip():
    """Explicit nameservers survive ares_set_servers_csv/ares_get_servers_csv.
    This is the supported way to configure a channel on a platform where c-ares
    cannot read the system resolver config — which is every Android build."""
    channel = pycares.Channel(
        servers=["8.8.8.8", "1.1.1.1"], sock_state_cb=_noop_sock_state_cb
    )
    try:
        # c-ares echoes back the port it filled in, e.g. "8.8.8.8:53".
        servers = channel.servers
        assert len(servers) == 2, servers
        assert servers[0].startswith("8.8.8.8"), servers
        assert servers[1].startswith("1.1.1.1"), servers

        channel.servers = ["9.9.9.9"]
        assert channel.servers[0].startswith("9.9.9.9"), channel.servers
    finally:
        channel.close()


def test_strerror_covers_every_error_code():
    """Every code in the errno table maps to a message through ares_strerror()."""
    assert pycares.errno.errorcode[pycares.errno.ARES_ENOTFOUND] == "ARES_ENOTFOUND"
    for code in pycares.errno.errorcode:
        message = pycares.errno.strerror(code)
        assert isinstance(message, str) and message, code


def test_address_parsing_rejects_garbage():
    """Address arguments go through ares_inet_pton in the extension; malformed
    input must raise rather than reach the resolver."""
    channel = pycares.Channel(sock_state_cb=_noop_sock_state_cb)
    try:
        channel.set_local_ip("127.0.0.1")

        for bad in ("not-an-ip", "999.999.999.999"):
            try:
                channel.set_local_ip(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"set_local_ip({bad!r}) did not raise")
    finally:
        channel.close()


def test_query_argument_validation():
    """Query type/class and callable checks happen in Python, before any
    ares_query_dnsrec call — so they hold even with no servers configured."""
    channel = pycares.Channel(sock_state_cb=_noop_sock_state_cb)
    try:
        for kwargs in (
            {"query_type": -1},
            {"query_type": pycares.QUERY_TYPE_A, "query_class": -1},
        ):
            try:
                channel.query("example.com", callback=lambda *a: None, **kwargs)
            except ValueError:
                pass
            else:
                raise AssertionError(f"query({kwargs}) did not raise")

        try:
            channel.query("example.com", pycares.QUERY_TYPE_A, callback=None)
        except TypeError:
            pass
        else:
            raise AssertionError("non-callable callback did not raise")
    finally:
        channel.close()


def test_query_against_closed_local_port_reports_error():
    """A query aimed at a loopback port with nothing listening drives the whole
    stack — socket setup, the c-ares event thread (epoll on Android, kqueue on
    iOS) and the CFFI callback back into Python — and must deliver a failure to
    the callback rather than hang or crash."""
    done = threading.Event()
    seen = []

    def on_result(result, errorno):
        seen.append((result, errorno))
        done.set()

    channel = pycares.Channel(
        servers=["127.0.0.1"],
        udp_port=1,
        tcp_port=1,
        timeout=0.5,
        tries=1,
        flags=pycares.ARES_FLAG_NOSEARCH,
    )
    try:
        channel.query("example.invalid", pycares.QUERY_TYPE_A, callback=on_result)
        assert done.wait(30), "callback never fired"
    finally:
        channel.close()

    result, errorno = seen[0]
    assert result is None
    assert errorno in (
        pycares.errno.ARES_ECONNREFUSED,
        pycares.errno.ARES_ETIMEOUT,
        pycares.errno.ARES_ESERVFAIL,
    ), pycares.errno.strerror(errorno)
