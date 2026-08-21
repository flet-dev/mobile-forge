import os
import socket
import struct
import threading

import pymssql

PRELOGIN = 0x12
LOGIN7 = 0x10
REPLY = 0x04

ENCRYPT_OFF, ENCRYPT_ON, ENCRYPT_NOT_SUP, ENCRYPT_REQ = 0, 1, 2, 3
ENCRYPTION_NAMES = {
    ENCRYPT_OFF: "OFF — I can do TLS, you decide",
    ENCRYPT_ON: "ON — I want TLS",
    ENCRYPT_NOT_SUP: "NOT_SUP — I have no TLS",
    ENCRYPT_REQ: "REQ — TLS or nothing",
}
LOGIN7_FIELDS = ("host", "user", "password", "app", "server", "", "library")
TDS_NAMES = {0x74000004: "7.4", 0x730B0003: "7.3", 0x72090002: "7.2"}

SCENARIOS = (
    ("stock connect(), server has no TLS", {}),
    ("stock connect(), server offers TLS", {"answer": ENCRYPT_ON}),
    ('connect(encryption="require")', {"encryption": "require"}),
    ("freetds.conf: encryption = require", {"via_conf": True}),
)


def driver_facts():
    """Everything the driver can state about itself with no server in reach."""
    return [
        ("FreeTDS", pymssql.get_freetds_version()),
        ("pymssql", pymssql.__version__),
        ("DB-API", f"{pymssql.apilevel}, paramstyle {pymssql.paramstyle}"),
        (
            "threadsafety",
            f"{pymssql.threadsafety} — share the module, not a connection",
        ),
        ("max connections", str(pymssql.get_max_connections())),
    ]


def parse_server(server, port):
    """Apply the five lines pymssql runs over ``server`` before handing it to FreeTDS.

    They explain most surprises: a named instance discards the ``port`` argument
    entirely, and so does any colon already in the string — which is why a bare
    IPv6 literal never reaches its port.
    """
    notes = []
    instance = ""
    if "\\" in server:
        server, instance = server.split("\\")
        notes.append(
            f"named instance {instance!r}: port argument ignored, "
            "FreeTDS asks SQL Browser on UDP 1434"
        )
    if server in (".", "(local)"):
        server = "localhost"
        notes.append("'.' and '(local)' mean localhost — the phone itself")
    if ":" in server:
        notes.append(
            "a colon in the server string wins over the port argument, "
            "which is why a bare IPv6 literal never gets one"
        )
    server = server + "\\" + instance if instance else server
    if ":" not in server and not instance:
        server = f"{server}:{port}"
    return server, notes


def connect_error(server, port):
    """Make a real connection attempt and report the exception as screen rows.

    ``pymssql`` wraps every FreeTDS failure: a database-side one becomes
    ``OperationalError`` and a driver-side one ``InterfaceError``. The payload is
    a single argument holding ``(db-lib number, message bytes)`` — and that number
    is stale here, because DB-Library only replaces it for an error of higher
    severity and every connection failure is severity 9.
    """
    try:
        pymssql.connect(
            server=server,
            port=str(port),
            user="probe",
            password="probe",
            login_timeout=5,
        ).close()
    except pymssql.Error as exc:
        number, text = exc.args[0]
        lines = text.decode(errors="replace").strip().splitlines()
        return [
            ("raised", _qualname(exc)),
            ("caught by", "pymssql.Error"),
            ("args[0][0]", str(number)),
        ] + [("", line) for line in lines]
    except Exception as exc:  # e.g. "a\\b\\c", which pymssql fails to split
        return [
            ("raised", _qualname(exc)),
            ("caught by", "nothing in pymssql's hierarchy"),
            ("", str(exc)),
        ]
    return [("raised", "nothing — the connection succeeded")]


def run_probes(scratch_dir):
    """Run every scenario in :data:`SCENARIOS` against a socket in this process.

    Each entry comes back as ``(heading, [(label, value), ...])``, ready for the
    app to lay out without knowing anything about TDS.
    """
    return [probe(label, scratch_dir, **kwargs) for label, kwargs in SCENARIOS]


def probe(label, scratch_dir, encryption=None, answer=ENCRYPT_NOT_SUP, via_conf=False):
    """Log in to a listener we own, and report what the driver put on the wire.

    The listener speaks just enough TDS to answer the PRELOGIN packet, which is
    where the whole encryption question is settled: the client states what it can
    do, the server states what it will do, and only then does a login packet or a
    TLS ClientHello follow. Reading the client's byte is a direct answer to "was
    this FreeTDS built with TLS" — a build without it can only say NOT_SUP.
    """
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(8)
    port = listener.getsockname()[1]
    seen = {"label": label}

    thread = threading.Thread(target=_serve, args=(listener, answer, seen), daemon=True)
    thread.start()

    server, restore = "127.0.0.1", None
    if via_conf:
        server = "warehouse"
        restore = os.environ.get("FREETDSCONF")
        os.environ["FREETDSCONF"] = _write_conf(scratch_dir, port)
    try:
        pymssql.connect(
            server=server,
            port=str(port),
            user="probe",
            password="probe",
            login_timeout=6,
            encryption=encryption,
        )
    except Exception as exc:
        seen["error"] = f"{type(exc).__name__}: {_first_line(exc)}"
    finally:
        if via_conf:
            os.environ.pop("FREETDSCONF", None)
            if restore is not None:
                os.environ["FREETDSCONF"] = restore
    thread.join(10)
    listener.close()
    return _describe(seen)


def _write_conf(scratch_dir, port):
    """Write the one freetds.conf setting that pymssql's own API cannot reach.

    FreeTDS reads this file per connection, so an app can write it at startup and
    point ``$FREETDSCONF`` at it. The section name becomes the ``server`` value.
    """
    path = os.path.join(scratch_dir, "freetds.conf")
    settings = f"[warehouse]\nhost = 127.0.0.1\nport = {port}\nencryption = require\n"
    with open(path, "w") as handle:
        handle.write(settings)
    return path


def _serve(listener, answer, seen):
    """Accept one login, keep the two packets the client sends, then hang up.

    The reply goes out before the client's bytes are parsed, and the ``except``
    is deliberately wide. A peer that accepts and then falls silent leaves
    ``connect()`` retrying the TDS version list forever — past ``login_timeout``,
    with no exception — so nothing in here may skip the answer or the close.
    """
    try:
        conn, _ = listener.accept()
    except OSError:
        return
    conn.settimeout(8)
    try:
        kind, body = _read_packet(conn)
        conn.sendall(_prelogin_answer(answer))
        if kind == PRELOGIN:
            seen["offered"] = _prelogin_options(body).get(1, b"\xff")[0]
        seen["kind"], seen["body"] = _read_packet(conn)
    except Exception as exc:
        seen["socket_error"] = str(exc)
    finally:
        conn.close()


def _read_packet(conn):
    """Read one TDS packet: an eight-byte header whose length covers the header."""
    head = _read_exactly(conn, 8)
    if len(head) < 8:
        return None, b""
    kind, _status, length = struct.unpack(">BBH", head[:4])
    return kind, _read_exactly(conn, length - 8)


def _read_exactly(conn, count):
    """Read ``count`` bytes, or fewer if the peer closes first."""
    buffer = b""
    while len(buffer) < count:
        chunk = conn.recv(count - len(buffer))
        if not chunk:
            break
        buffer += chunk
    return buffer


def _prelogin_options(body):
    """Split a PRELOGIN body into its {token: value} options."""
    options, index = {}, 0
    while index < len(body) and body[index] != 0xFF:
        offset, length = struct.unpack_from(">HH", body, index + 1)
        options[body[index]] = body[offset : offset + length]
        index += 5
    return options


def _prelogin_answer(encryption):
    """Build a server PRELOGIN reply carrying a version and an encryption byte."""
    options = bytes([0, 0, 11, 0, 6, 1, 0, 17, 0, 1, 0xFF])
    body = options + bytes([16, 0, 0, 0, 0, 0]) + bytes([encryption])
    return struct.pack(">BBHHBB", REPLY, 1, 8 + len(body), 0, 1, 0) + body


def _describe(seen):
    """Turn the captured bytes into the heading and rows the app puts on screen."""
    offered = ENCRYPTION_NAMES.get(seen.get("offered"), "nothing readable")
    rows = [("offered", offered)]
    body, kind = seen.get("body", b""), seen.get("kind")
    if kind == LOGIN7:
        version = struct.unpack_from("<I", body, 4)[0]
        name = TDS_NAMES.get(version, hex(version))
        rows.append(("then sent", f"LOGIN7 in the clear, TDS {name}"))
        rows += _login7_fields(body)
    elif body[:1] == b"\x16":
        rows.append(("then sent", f"TLS ClientHello, {len(body)} bytes"))
        rows.append(("offers", _client_hello_versions(body)))
    else:
        rows.append(("then sent", "nothing — the driver hung up before logging in"))
    rows.append(("ended as", seen.get("error", "-")))
    return seen["label"], rows


def _login7_fields(body):
    """Pull the readable strings out of a login packet.

    Everything here crossed the network as UTF-16 text. The password is not
    encrypted, only nibble-swapped and XORed with 0xA5 — undoing it is the two
    lines below, which is the whole reason the encryption byte matters.
    """
    base = 4 * 6 + 4 + 4 + 4
    fields = []
    for index, name in enumerate(LOGIN7_FIELDS):
        offset, length = struct.unpack_from("<HH", body, base + index * 4)
        raw = body[offset : offset + length * 2]
        if not name or not raw:
            continue
        if name == "password":
            raw = bytes((((b ^ 0xA5) & 0x0F) << 4) | ((b ^ 0xA5) >> 4) for b in raw)
        fields.append((name, raw.decode("utf-16-le", "replace")))
    return fields


def _client_hello_versions(body):
    """Report the TLS versions a ClientHello lists in its supported_versions."""
    hello = body[9 : 9 + int.from_bytes(body[6:9], "big")]
    index = 2 + 32
    index += 1 + hello[index]
    index += 2 + struct.unpack_from(">H", hello, index)[0]
    index += 1 + hello[index]
    end = index + 2 + struct.unpack_from(">H", hello, index)[0]
    index += 2
    names = []
    while index + 4 <= end:
        kind, length = struct.unpack_from(">HH", hello, index)
        if kind == 0x002B:
            names = [
                f"TLS 1.{hello[index + 6 + step] - 1}"
                for step in range(0, hello[index + 4], 2)
            ]
        index += 4 + length
    return ", ".join(names) or "no supported_versions extension"


def _qualname(exc):
    """The importable name of an exception class, module included."""
    return f"{type(exc).__module__}.{type(exc).__name__}"


def _first_line(exc):
    """The useful line of a pymssql exception, without the DB-Lib preamble."""
    payload = exc.args[0] if exc.args else ""
    text = (
        payload[1].decode("utf-8", "replace")
        if isinstance(payload, tuple)
        else str(exc)
    )
    lines = [line for line in text.splitlines() if not line.startswith("DB-Lib")]
    return (lines or text.splitlines() or [""])[0]
