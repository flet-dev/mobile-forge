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


def test_bestpractice_loads_second_extension_and_applies_settings():
    """`apsw.bestpractice` is what consumers are told to call, and importing it
    pulls in a SECOND native extension (apsw/_unicode) that plain `import apsw`
    never loads. This exercises that import path on device, then checks the
    hooks actually reach a connection opened afterwards."""
    import sys

    import apsw
    import apsw.bestpractice

    apsw.bestpractice.apply(apsw.bestpractice.recommended)
    assert "apsw._unicode" in sys.modules, sorted(m for m in sys.modules if "apsw" in m)

    connection = apsw.Connection(":memory:")
    assert connection.pragma("foreign_keys") == 1
    assert connection.pragma("recursive_triggers") == 1

    # Double-quoted string literals must now be an error rather than a silent string.
    try:
        connection.execute('SELECT "not a column"')
    except apsw.SQLError:
        pass
    else:
        raise AssertionError("double-quoted string literals were not rejected")

    connection.close()


def test_file_database_wal_survives_reopen(tmp_path):
    """A database in a real file, in WAL mode, is the shape every consumer app
    uses. Confirm WAL engages on the device filesystem, that the -wal/-shm
    sidecars appear and are cleaned up on close, and that both the rows and the
    journal mode are still there after reopening."""
    import apsw

    path = str(tmp_path / "notes.db")

    connection = apsw.Connection(path)
    connection.set_busy_timeout(5000)
    assert connection.pragma("journal_mode", "wal") == "wal"
    connection.execute("CREATE TABLE notes(id INTEGER PRIMARY KEY, text TEXT NOT NULL)")
    connection.execute("INSERT INTO notes(text) VALUES(?)", ("written before restart",))

    sidecars = {p.name for p in tmp_path.iterdir()}
    assert "notes.db-wal" in sidecars, sidecars
    connection.close()
    assert {p.name for p in tmp_path.iterdir()} == {"notes.db"}

    reopened = apsw.Connection(path)
    assert reopened.pragma("journal_mode") == "wal"
    rows = list(reopened.execute("SELECT text FROM notes"))
    assert rows == [("written before restart",)], rows
    reopened.close()


def test_lock_serialised_connection_across_threads():
    """One Connection may be used from any thread, but NOT by two at once —
    apsw raises ThreadingViolationError rather than waiting. `page.run_thread`
    dispatches to a pool that really does overlap, so the documented pattern is
    a shared Connection behind a lock. Hammer that pattern with the same
    insert-then-read pair the example app performs, and require every write to
    land.

    An unlocked version of this loop drops rows intermittently (observed on
    desktop), which is why the lock is part of the recommendation rather than
    an optional refinement.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import apsw

    connection = apsw.Connection(":memory:")
    connection.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, n INTEGER)")
    lock = threading.Lock()
    workers, per_worker = 8, 50

    def work(worker):
        for i in range(per_worker):
            with lock:
                connection.execute("INSERT INTO t(n) VALUES(?)", (worker * 1000 + i,))
                # Materialise inside the lock: an unconsumed cursor is exactly
                # what leaves the connection busy for another thread.
                list(connection.execute("SELECT id, n FROM t ORDER BY id DESC"))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, range(workers)))

    expected = workers * per_worker
    assert connection.execute("SELECT count(*) FROM t").fetchall() == [(expected,)]
    connection.close()


def test_extensions_compiled_in():
    """The recipe relies on apsw's `enable_all_extensions`; these are the
    extensions the README promises consumers. Assert they are really present in
    the wheel rather than trusting the build configuration."""
    import apsw

    options = set(apsw.compile_options)
    expected = {
        "ENABLE_FTS3",
        "ENABLE_FTS4",
        "ENABLE_FTS5",
        "ENABLE_RTREE",
        "ENABLE_GEOPOLY",
        "ENABLE_SESSION",
        "ENABLE_PREUPDATE_HOOK",
        "ENABLE_STAT4",
        "ENABLE_DBSTAT_VTAB",
        "ENABLE_COLUMN_METADATA",
        "ENABLE_CARRAY",
        "ENABLE_PERCENTILE",
        "ENABLE_MATH_FUNCTIONS",
        "MAX_ATTACHED=125",
        "MAX_FUNCTION_ARG=1000",
        "THREADSAFE=1",
    }
    assert expected <= options, expected - options
