# apsw = Another Python SQLite Wrapper. It ships a SQLite amalgamation
# statically compiled into its C extension, so the round-trip below proves
# both that the .so loads on-device and that the embedded SQLite engine works.
# https://rogerbinns.github.io/apsw/
def test_versions():
    """The C extension exposes the apsw build version and the version of the
    SQLite it statically embedded. Both must import and report sane values."""
    import apsw

    apsw_ver = apsw.apswversion()
    sqlite_ver = apsw.sqlitelibversion()
    print("apsw version:", apsw_ver)
    print("embedded SQLite version:", sqlite_ver)

    assert apsw_ver.startswith("3.53.2"), apsw_ver
    # apsw 3.53.2.0 pairs with the SQLite 3.53.2 amalgamation.
    assert sqlite_ver.startswith("3.53.2"), sqlite_ver


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
