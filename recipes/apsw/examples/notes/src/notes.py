"""The database half of the app: one apsw connection, one table, one lock."""

import os
import sqlite3  # stdlib — used only to contrast the two SQLite engines on screen
import threading

import apsw
import apsw.bestpractice

# Must run before any connection is opened: these are connection hooks, so they apply
# only to connections created afterwards (WAL, foreign keys, a 100 ms busy timeout,
# and double-quoted string literals rejected).
apsw.bestpractice.apply(apsw.bestpractice.recommended)

VERSIONS = (
    f"apsw {apsw.apswversion()} embeds SQLite {apsw.sqlitelibversion()} — "
    f"the stdlib sqlite3 here sees {sqlite3.sqlite_version}"
)

# FLET_APP_STORAGE_DATA is durable, app-private storage. Flet also makes it the working
# directory on device, so a bare "notes.db" would land there too — this spells it out.
_db = apsw.Connection(os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "notes.db"))
_db.set_busy_timeout(5000)  # 100 ms (the bestpractice default) is thin for a UI app
_db.execute("CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, text TEXT)")

# This Connection may be used from any thread, but not by two at the same time: apsw
# raises ThreadingViolationError ("the Connection is busy in another thread") rather
# than waiting. Flet's thread pool can overlap handlers, so every use is serialised
# here, in the one place that owns the connection.
_lock = threading.Lock()


def insert(text):
    """Write one note. Safe to call from a worker thread."""
    with _lock:
        _db.execute("INSERT INTO notes(text) VALUES(?)", (text,))


def all_notes():
    """Return every note as (id, text) pairs, newest first.

    The rows are materialised inside the lock deliberately: an unconsumed cursor keeps
    the connection busy, which is exactly what another thread would collide with.
    Returning a plain list means the caller never holds one open.
    """
    with _lock:
        return list(_db.execute("SELECT id, text FROM notes ORDER BY id DESC"))
