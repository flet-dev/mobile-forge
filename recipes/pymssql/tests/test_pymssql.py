import pytest


def test_import():
    """Importing pymssql loads its compiled _mssql/_pymssql extensions
    (FreeTDS + OpenSSL linked) on-device and resolves all their symbols. A real
    query needs a SQL Server, so this proves the wheel imports and the C
    extensions initialize."""
    import pymssql
    import pymssql._mssql  # the compiled extension is a submodule of the package

    assert pymssql.__version__
    assert callable(pymssql.connect)
    assert hasattr(pymssql._mssql, "MSSQLConnection")


def test_connect_refused():
    """Drives FreeTDS's native connect path with no server needed: a closed
    local port refuses immediately, and pymssql must translate that into its own
    exception. This proves the statically-linked TDS code actually *runs* on device."""
    import pymssql

    with pytest.raises(pymssql.Error):
        pymssql.connect(
            server="127.0.0.1", port=1, user="x", password="y", login_timeout=2
        )
