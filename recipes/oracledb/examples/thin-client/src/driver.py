import os
import time

import oracledb

DEFAULT_DSN = "127.0.0.1:1521/FREEPDB1"

# Every form the compiled parser accepts. The alias is resolved out of the
# tnsnames.ora written by prepare_config(); the rest are self-contained.
SAMPLES = [
    ("easy connect, refused", "127.0.0.1:1521/FREEPDB1"),
    ("easy connect, unroutable", "192.0.2.1:1521/FREEPDB1"),
    ("tnsnames.ora alias", "sales"),
    (
        "TLS with parameters",
        "tcps://db.example.com:1522/hr_high?retry_count=2&retry_delay=1",
    ),
    (
        "full descriptor",
        "(DESCRIPTION=(ADDRESS_LIST=(ADDRESS=(PROTOCOL=TCP)"
        "(HOST=one.example.com)(PORT=1521))(ADDRESS=(PROTOCOL=TCP)"
        "(HOST=two.example.com)(PORT=1521)))(CONNECT_DATA=(SERVICE_NAME=sales)))",
    ),
    ("credentials in the string", "scott/tiger@127.0.0.1:1521/FREEPDB1"),
]

TNSNAMES = """\
sales =
  (DESCRIPTION =
    (RETRY_COUNT=2)(RETRY_DELAY=3)
    (ADDRESS = (PROTOCOL = TCP)(HOST = sales1.example.com)(PORT = 1521))
    (ADDRESS = (PROTOCOL = TCP)(HOST = sales2.example.com)(PORT = 1521))
    (CONNECT_DATA = (SERVICE_NAME = sales.example.com))
  )
"""


def prepare_config():
    """Write a tnsnames.ora into app storage and point the driver at it.

    A bare alias is resolved by reading tnsnames.ora out of the directory named
    by ``oracledb.defaults.config_dir``, which starts out as ``TNS_ADMIN`` and is
    unset on a phone. Generating the file keeps the example free of bundled
    assets; a real app would ship one as an asset or fetch it. Returns the
    directory so the UI can show where it landed.
    """
    directory = os.getenv("FLET_APP_STORAGE_DATA", ".")
    with open(os.path.join(directory, "tnsnames.ora"), "w") as handle:
        handle.write(TNSNAMES)
    oracledb.defaults.config_dir = directory
    return directory


def driver_facts():
    """Rows naming which driver is loaded, and how patient it is by default."""
    facts = [
        ("python-oracledb", oracledb.__version__),
        ("thin mode", str(oracledb.is_thin_mode())),
        (
            "DB-API",
            f"level {oracledb.apilevel}, threadsafety {oracledb.threadsafety}, "
            f"paramstyle {oracledb.paramstyle}",
        ),
        ("connect timeout", f"{oracledb.ConnectParams().tcp_connect_timeout:.0f} s"),
    ]
    try:
        facts.append(("Oracle Client", ".".join(map(str, oracledb.clientversion()))))
    except oracledb.Error as exc:
        facts.append(("Oracle Client", _detail(exc)))
    return facts


def parse(connect_string):
    """Take a connect string apart with the compiled parser, no network involved.

    ``ConnectParams.parse_connect_string`` is one of the Cython extensions doing
    real work offline: easy connect, a ``tcps`` URL carrying query parameters, a
    full ``DESCRIPTION``, or a bare alias looked up in tnsnames.ora all end up as
    the same set of fields, and ``get_connect_string()`` writes the descriptor the
    driver would actually put on the wire. The failures teach as much as the
    successes, so a rejection is reported rather than raised.
    """
    params = oracledb.ConnectParams()
    try:
        params.parse_connect_string(connect_string)
    except oracledb.Error as exc:
        return [("rejected", type(exc).__name__), ("code", _detail(exc))]
    parsed = [
        ("protocol", _flatten(params.protocol)),
        ("host", _flatten(params.host)),
        ("port", _flatten(params.port)),
        ("service", params.service_name or params.sid or ""),
        ("retry", f"{params.retry_count} x {params.retry_delay} s"),
    ]
    if params.wallet_location:
        parsed.append(("wallet", params.wallet_location))
    parsed.append(("descriptor", params.get_connect_string()))
    return parsed


def attempt(connect_string, timeout=5.0):
    """Run the thin driver's real network path and report exactly how it ended.

    Nothing is listening at any of the sample addresses, which is the point: the
    socket, the connect packet and the error handling in ``thin_impl`` all run on
    the device, and what comes back is an ordinary Python exception carrying an
    error code rather than a native crash. Never raises — the outcome is the
    return value, so the caller can put it straight on screen.

    ``OSError`` is in the except clause alongside ``oracledb.Error`` because name
    resolution happens before the driver's own error handling: a host that does
    not resolve arrives as a bare ``socket.gaierror``.
    """
    started = time.perf_counter()
    try:
        connection = oracledb.connect(
            user="demo",
            password="demo",
            dsn=connect_string,
            tcp_connect_timeout=timeout,
        )
    except (oracledb.Error, OSError) as exc:
        outcome = [
            ("raised", type(exc).__name__),
            ("base class", _dbapi_base(exc)),
            ("detail", _detail(exc)),
        ]
    else:
        with connection:
            outcome = [("connected", connection.version)]
    outcome.append(("took", f"{(time.perf_counter() - started) * 1000:.0f} ms"))
    return outcome


def load_oracle_client():
    """Ask for thick mode, which is the one thing a phone cannot give you.

    Thick mode is ODPI-C dlopening the Oracle Instant Client — ``libclntsh.so``
    on Android, ``libclntsh.dylib`` on iOS. No wheel ships it and Oracle
    publishes no mobile build, so the lookup fails and the driver stays thin. The
    ``thick_impl`` extension itself loaded at ``import oracledb`` without any of
    that, because it links only libpython and the C runtime.
    """
    try:
        oracledb.init_oracle_client()
    except oracledb.Error as exc:
        return [
            ("raised", type(exc).__name__),
            ("detail", _detail(exc)),
        ]
    return [
        ("loaded", "thick mode is now active"),
        ("client", ".".join(map(str, oracledb.clientversion()))),
    ]


def api_type_groups():
    """Which Oracle types each DB-API type constant stands for.

    ``cursor.description`` hands back a ``DbType`` per column, and comparing it to
    ``oracledb.STRING`` or ``oracledb.NUMBER`` is the portable way to branch on
    one: a single ``ApiType`` compares equal to several database types. The rows
    are computed by asking every ``DB_TYPE_*`` constant that question, not copied
    out of the documentation.

    The last row is the reason this is worth printing: the five DB-API constants
    do not partition Oracle's types. Roughly half of them — the LOBs, JSON,
    vectors, objects, intervals, booleans — match none of the five, so a
    ``description`` branch written only on ``STRING``/``NUMBER``/... silently
    falls through for those columns.
    """
    names = sorted(name for name in dir(oracledb) if name.startswith("DB_TYPE_"))
    groups = []
    grouped = set()
    for group in ("STRING", "NUMBER", "DATETIME", "BINARY", "ROWID"):
        api_type = getattr(oracledb, group)
        members = [name for name in names if getattr(oracledb, name) == api_type]
        grouped.update(members)
        groups.append((group, ", ".join(_short(name) for name in members)))
    rest = [name for name in names if name not in grouped]
    groups.append(
        (f"none of the five ({len(rest)})", ", ".join(_short(name) for name in rest))
    )
    return groups


def _short(name):
    """DB_TYPE_VARCHAR reads as VARCHAR once the panel says what it is listing."""
    return name[len("DB_TYPE_") :]


def _flatten(value):
    """Address fields come back as a list when the descriptor lists several."""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return "" if value is None else str(value)


def _detail(exc):
    """The driver's message on one line, prefixed by its DPY- or DPI- code."""
    return " ".join(str(exc).split())


def _dbapi_base(exc):
    """The class an ``except`` clause one level broader would have to name.

    For a driver error that is a DB-API class such as ``DatabaseError``; for a
    failure raised before the driver gets involved it is ``OSError``, which is
    the distinction this row exists to make visible.
    """
    return type(exc).__mro__[1].__name__
