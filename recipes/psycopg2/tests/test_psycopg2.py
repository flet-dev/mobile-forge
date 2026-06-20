import pytest


def test_import():
    """Importing psycopg2 loads its compiled _psycopg extension (libpq + OpenSSL
    statically linked) on-device and resolves all its symbols. A real query
    needs a PostgreSQL server, so this proves the wheel imports and the C
    extension initializes."""
    import psycopg2
    import psycopg2._psycopg  # the compiled extension

    assert psycopg2.__version__
    assert callable(psycopg2.connect)


def test_exception_api():
    """psycopg2 exposes the DB-API exception hierarchy callers catch."""
    import psycopg2

    for exc in ("Error", "OperationalError", "DatabaseError", "InterfaceError"):
        assert issubclass(getattr(psycopg2, exc), Exception)


def test_connect_refused():
    """Drives libpq's native connect path with no server needed: a closed local
    port refuses immediately and psycopg2 must translate that into
    OperationalError. Proves the statically-linked libpq actually *runs* on
    device, not merely that the extension loaded."""
    import psycopg2

    with pytest.raises(psycopg2.OperationalError):
        psycopg2.connect(host="127.0.0.1", port=1, connect_timeout=2)
