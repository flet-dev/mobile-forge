def test_import():
    """Importing pymssql loads its compiled _mssql / _pymssql extensions
    (FreeTDS + OpenSSL linked) on-device and resolves all their symbols. A real
    query needs a SQL Server, so this proves the wheel imports and the C
    extensions initialize."""
    import pymssql
    import pymssql._mssql  # the compiled extension is a submodule of the package

    assert pymssql.__version__
    assert callable(pymssql.connect)
    assert hasattr(pymssql._mssql, "MSSQLConnection")
