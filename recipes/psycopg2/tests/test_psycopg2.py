import pytest

# A port nothing listens on: the kernel refuses immediately, so these probes
# return in about a millisecond and never leave the device. `user` is spelled out
# because libpq otherwise derives it from the operating system, and iOS has no
# passwd entry for the app's uid — the connection dies at "local user with ID 501
# does not exist" before any other keyword is judged.
CLOSED_PORT = {"host": "127.0.0.1", "port": 1, "connect_timeout": 2, "user": "probe"}


def test_import():
    """Importing psycopg2 loads the compiled `psycopg2._psycopg` extension, which
    is the only native object in the wheel and carries libpq statically linked
    inside it. The extension is built BIND_NOW, so the import either resolves
    every libpq symbol — and, on the legs where OpenSSL is borrowed from the Flet
    runtime rather than folded in, every OpenSSL symbol too — or fails here."""
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
        psycopg2.connect(**CLOSED_PORT)


def test_compiled_in_features():
    """Pins the feature set the wheel documents, read from the binary itself.

    libpq validates connection keywords while parsing, before opening a socket,
    and rejects one whose feature was configured out. flet-libpq builds
    --with-openssl --without-gssapi, so `sslmode=require` must survive parsing
    and fail on the network instead, while `gssencmode=require` must be refused
    outright. A support-tree or configure change that silently flips either one
    lands here. This asserts a property of *these* wheels: pre-validating it on
    a desktop against psycopg2-binary fails, because that build has GSSAPI."""
    import psycopg2

    with pytest.raises(psycopg2.OperationalError) as tls:
        psycopg2.connect(**CLOSED_PORT, sslmode="require")
    assert "not compiled in" not in str(tls.value)

    with pytest.raises(psycopg2.OperationalError) as gss:
        psycopg2.connect(**CLOSED_PORT, gssencmode="require")
    assert "GSSAPI support is not compiled in" in str(gss.value)
