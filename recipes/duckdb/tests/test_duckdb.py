def test_import_version():
    """Loads the _duckdb pybind11 C++ extension (the canary that the big C++
    engine cross-compiled and links its C++ runtime)."""
    import duckdb

    assert duckdb.__version__


def test_in_memory_query():
    """duckdb is an in-process OLAP engine — no server needed. Open an in-memory
    database and run a CREATE/INSERT/SELECT round-trip through the engine."""
    import duckdb

    con = duckdb.connect(":memory:")
    try:
        assert con.execute("SELECT 42").fetchone() == (42,)

        con.execute("CREATE TABLE t(id INTEGER, name VARCHAR)")
        con.executemany("INSERT INTO t VALUES (?, ?)", [(1, "apple"), (2, "banana")])
        rows = con.execute("SELECT id, name FROM t ORDER BY id").fetchall()
        assert rows == [(1, "apple"), (2, "banana")], rows

        # an aggregate to exercise the analytical engine path
        total = con.execute("SELECT sum(id) FROM t").fetchone()
        assert total == (3,), total
    finally:
        con.close()
