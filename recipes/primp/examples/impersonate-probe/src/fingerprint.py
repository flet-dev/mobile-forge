import socket
import threading
import time

import primp

# The impersonation targets this app offers. "off" is the sentinel for a plain
# primp client, which is the interesting comparison: it is the shape a server
# looks for when it wants to turn Python away.
PROFILES = ("chrome_148", "firefox_148", "safari_26.3", "edge_148", "off")
SYSTEMS = ("android", "ios", "macos", "windows", "linux")

# Reports the JA3/JA4 hash of the TLS ClientHello it just received, plus the
# HTTP/2 (Akamai) fingerprint and the User-Agent it was sent.
PROBE_URL = "https://tls.browserleaks.com/json"
PROBE_FIELDS = (
    ("ja4", "JA4"),
    ("ja3_hash", "JA3"),
    ("akamai_hash", "HTTP/2"),
    ("user_agent", "User-Agent"),
)

VERSION = f"primp {primp.__version__}"


def client(profile, system):
    """Build a client for one impersonation target.

    `impersonate_os` is passed only alongside a profile, and for two separate
    reasons. Given a profile, primp otherwise draws an OS at random per
    client, so the same target answers as Chrome-on-macOS one run and
    Chrome-on-iPhone the next. Given no profile, an OS on its own still turns
    impersonation on -- with a browser primp picks -- which would quietly make
    the "off" row another disguise instead of the bare client it is here to
    contrast with.
    """
    if profile == "off":
        return primp.Client(timeout=15, connect_timeout=10)
    return primp.Client(
        impersonate=profile,
        impersonate_os=system,
        timeout=15,
        connect_timeout=10,
    )


def capture_head(server, sink):
    """Accept one connection, keep its request head, answer with a small 200.

    Reads to the blank line that ends the head, so nothing here depends on the
    request having a body. Every socket error is swallowed: this runs on its
    own thread, where an exception would be printed and lost, and an empty
    `sink` already tells the caller the exchange did not happen.
    """
    try:
        connection, _ = server.accept()
        with connection:
            connection.settimeout(10)
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 16384:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                head += chunk
            sink.append(head.split(b"\r\n\r\n")[0].decode("latin-1"))
            connection.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
            )
    except OSError:
        return


def echo(profile, system):
    """Request a loopback socket and return the request head it received.

    The listener is a bare socket rather than an HTTP server because the point
    is the literal bytes in the order primp wrote them, and anything that
    parses a request hands back its own ordering instead. 127.0.0.1 is an
    address literal, so no name is resolved and nothing leaves the device:
    this panel works with the radio off.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.settimeout(10)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    sink = []
    listener = threading.Thread(target=capture_head, args=(server, sink), daemon=True)
    listener.start()
    try:
        started = time.perf_counter()
        response = client(profile, system).get(
            f"http://127.0.0.1:{server.getsockname()[1]}/"
        )
        elapsed = (time.perf_counter() - started) * 1e3
        listener.join(timeout=10)
    finally:
        server.close()
    if not sink:
        raise RuntimeError("the loopback socket received nothing")
    # HTTP line endings are CRLF; a text control has no use for the CR.
    return sink[0].replace("\r\n", "\n"), response.status_code, elapsed


def probe(profile, system):
    """Ask a public endpoint what this client's TLS handshake looked like.

    This is the half a local socket cannot show: JA3 and JA4 are hashes of the
    ClientHello -- cipher suites, extensions, curves, ALPN -- which only the
    server on the other side of the handshake gets to see. Needs the network,
    and the caller is expected to catch the failure when there is none.
    """
    started = time.perf_counter()
    payload = client(profile, system).get(PROBE_URL).json()
    elapsed = (time.perf_counter() - started) * 1e3
    rows = [
        (label, str(payload.get(key) or "(not sent)")) for key, label in PROBE_FIELDS
    ]
    return rows, elapsed
