def test_versions():
    """The C extension exposes the apsw build version and the version of the
    SQLite it statically embedded. This test confirms that the two versions
    are consistent with each other.

    Example:
        apsw.apswversion()      -> "3.53.2.0"
        apsw.sqlitelibversion() -> "3.53.2"
    """
    import apsw

    assert apsw.apswversion().startswith(apsw.sqlitelibversion())


def test_in_memory_roundtrip():
    """Open an in-memory database and run a CREATE/INSERT/SELECT round-trip
    through the embedded SQLite engine to confirm it is fully functional."""
    import apsw

    connection = apsw.Connection(":memory:")
    cursor = connection.cursor()

    cursor.execute("CREATE TABLE fruit(id INTEGER PRIMARY KEY, name TEXT, qty INTEGER)")
    cursor.executemany(
        "INSERT INTO fruit(name, qty) VALUES(?, ?)",
        [("apple", 3), ("banana", 7), ("cherry", 12)],
    )

    rows = list(cursor.execute("SELECT name, qty FROM fruit ORDER BY qty"))
    assert rows == [("apple", 3), ("banana", 7), ("cherry", 12)], rows

    total = cursor.execute("SELECT sum(qty) FROM fruit").fetchall()
    assert total == [(22,)], total

    connection.close()
