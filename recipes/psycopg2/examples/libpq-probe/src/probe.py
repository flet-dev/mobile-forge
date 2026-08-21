"""Everything this app asks of psycopg2. None of it needs a PostgreSQL server."""

import datetime
import decimal
import time
import uuid

try:
    import psycopg2
    from psycopg2 import extensions, extras

    extras.register_uuid()
    IMPORT_ERROR = None
except Exception as error:  # noqa: BLE001 - the message is the screen's content
    psycopg2 = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

# A port nothing listens on: the kernel refuses immediately, so every probe below
# returns in about a millisecond and never leaves the device.
# `user` is spelled out because libpq derives it from the operating system when
# it is missing, and iOS has no passwd entry for the app's uid — the connection
# then dies at "local user with ID 501 does not exist", before libpq has looked
# at any other keyword.
CLOSED_PORT = {"host": "127.0.0.1", "port": 1, "connect_timeout": 2, "user": "probe"}

DEFAULT_DSN = "postgresql://app@127.0.0.1:1/orders?sslmode=require&connect_timeout=2"

# Each probe sets one connection option and reads libpq's own answer. libpq
# validates these while parsing the connection string, before it opens a socket,
# and says "not compiled in" when the feature is absent from the build. Only a
# build *missing* the feature carries that sentence, so a "yes" here means the
# option was accepted and the attempt got as far as the network.
# libpq says this once it is past parsing and talking to a socket. Requiring it
# keeps an error raised *before* validation from reading as a present feature.
REACHED_NETWORK = "connection to server"

FEATURES = (
    ("TLS, sslmode=require", {"sslmode": "require"}, "SSL support is not compiled in"),
    (
        "GSSAPI, gssencmode=require",
        {"gssencmode": "require"},
        "GSSAPI support is not compiled in",
    ),
)

# What libpq supplies for a keyword the connection string leaves out. From the
# libpq documentation; the values are what make an unset `sslmode` interesting.
DEFAULTS = (
    ("port", "5432"),
    ("user", "the local operating-system account name"),
    ("sslmode", "prefer — TLS is attempted, plaintext accepted if refused"),
    ("sslrootcert", "~/.postgresql/root.crt"),
    ("connect_timeout", "none — blocks until the OS gives up on the socket"),
)

# Python values and the SQL literal psycopg2 turns each into. adapt() is the
# whole client-side half of the driver and needs no connection to run.
SAMPLES = (
    "O'Reilly & Co",
    b"\x00\x01\xff",
    decimal.Decimal("19.99"),
    datetime.datetime(2026, 8, 21, 13, 45, tzinfo=datetime.timezone.utc),
    datetime.timedelta(days=1, seconds=30),
    [1, 2, 3],
    uuid.UUID("2f1c8f7a-0000-4000-8000-00000000abcd"),
    {"a": 1},
)


def release(number):
    """A libpq version integer as its release number, e.g. 170005 -> "17.5"."""
    return f"{number // 10000}.{number % 100}"


def driver():
    """Label/value pairs describing the driver and the libpq inside it.

    Both version numbers are worth showing side by side: `__libpq_version__` is
    baked in when the extension is compiled and `libpq_version()` asks the loaded
    library at runtime. On a desktop those can disagree, because libpq is a shared
    object the operating system supplies. In these wheels libpq is linked into the
    extension, so nothing can come between them and they always match.
    """
    return [
        ("psycopg2", psycopg2.__version__),
        ("libpq compiled against", release(psycopg2.__libpq_version__)),
        ("libpq loaded", release(extensions.libpq_version())),
        ("DB-API level", f"{psycopg2.apilevel} (paramstyle {psycopg2.paramstyle})"),
        ("threadsafety", f"{psycopg2.threadsafety} — connections shared, cursors not"),
    ]


def features():
    """Ask the binary which optional pieces of libpq were compiled into it.

    Each entry is (name, present, what libpq said). A connection to the closed
    port cannot succeed, so the message is always an error — the question is
    *which* error. Getting the option rejected as "not compiled in" means the
    feature is absent; anything else, including the refusal of the TCP connection
    itself, means libpq accepted the option and the feature is there.

    The two answers are not symmetric. PostgreSQL compiles the rejection out of a
    build that has the feature, so a present feature never says so in words: the
    evidence is that the option survived parsing and the failure that came back
    is about the network instead.

    `present` is None when libpq failed before it validated the keyword, which
    answers neither question — treating that as a "yes" is how this probe once
    reported GSSAPI as compiled into a build that does not have it.
    """
    found = []
    for label, option, absent in FEATURES:
        try:
            psycopg2.connect(**CLOSED_PORT, **option).close()
            said = "connected"
        except psycopg2.Error as error:
            said = " ".join(str(error).split())
        if absent in said:
            present = False
        elif said == "connected" or REACHED_NETWORK in said:
            present = True
        else:
            present = None
        found.append((label, present, said))
    return found


def normalise(dsn):
    """Split a connection string into keywords, and list what libpq will fill in.

    `parse_dsn` is `PQconninfoParse`: it accepts both the URI and the
    `key=value` form, validates every keyword, and returns only what was actually
    written down. Purely local — it is the same parse the connection would do,
    minus the connecting. Returns the keywords (password redacted), the defaults
    that apply because a keyword is missing, and a verdict on the transport.
    """
    settings = extensions.parse_dsn(dsn)
    shown = {
        key: ("*" * 8 if key == "password" else value)
        for key, value in sorted(settings.items())
    }
    filled = [(key, value) for key, value in DEFAULTS if key not in settings]
    return shown, filled, transport(settings.get("sslmode"))


def transport(sslmode):
    """What the chosen sslmode actually guarantees, as (verdict, is it enough).

    Three groups, and the split that matters is not encrypted/unencrypted: it is
    whether the server is *authenticated*. `require` encrypts and then trusts
    whoever answered, so it stops a passive listener and not an interception.
    """
    if sslmode in ("verify-ca", "verify-full"):
        return (
            f"sslmode={sslmode}: encrypted, and the server certificate is checked",
            True,
        )
    if sslmode == "require":
        return "sslmode=require: encrypted, but the server is not authenticated", False
    if sslmode is None:
        return "sslmode unset: defaults to prefer, so plaintext is accepted", False
    return f"sslmode={sslmode}: plaintext is accepted", False


def attempt(dsn):
    """Connect, expect it to fail, and report exactly how — this is the point.

    An app that reaches a database over a mobile network gets this path far more
    often than it gets a connection, so the exception class is part of the API.
    Everything libpq cannot do lands as `OperationalError`: a refused port, a
    name that will not resolve, an expired `connect_timeout`, a rejected
    password. Note what is *not* there — `pgcode` is None, because a SQLSTATE
    comes from a server and no server was reached.
    """
    started = time.perf_counter()
    try:
        psycopg2.connect(dsn).close()
        outcome = [("result", "connected — there is a server on that address")]
    except psycopg2.Error as error:
        outcome = [
            ("exception", f"psycopg2.{type(error).__name__}"),
            (
                "caught by",
                " → ".join(base.__name__ for base in type(error).__mro__[1:4]),
            ),
            ("pgcode", repr(error.pgcode)),
            ("diag.sqlstate", repr(error.diag.sqlstate)),
            ("message", " ".join(str(error).split())),
        ]
    return outcome + [("took", f"{(time.perf_counter() - started) * 1000:.0f} ms")]


def literals():
    """Every sample value beside the SQL literal psycopg2 would send for it.

    `adapt` is client-side and runs offline, which also means it runs without the
    server settings that decide how to escape: with nothing connected psycopg2
    assumes `standard_conforming_strings` is off, so `bytes` arrives as octal
    with every backslash doubled rather than in the hex form a connection-aware
    adapter picks. A type with no adapter registered raises `ProgrammingError`
    here rather than producing bad SQL — `dict` is the one in this list, and
    `psycopg2.extras.Json` is the wrapper that fixes it.
    """
    rows = []
    for value in SAMPLES:
        try:
            sql = extensions.adapt(value).getquoted().decode("utf-8", "replace")
        except psycopg2.Error as error:
            sql = f"{type(error).__name__}: {error}"
        rows.append((f"{type(value).__name__}  {value!r}", sql))
    return rows
