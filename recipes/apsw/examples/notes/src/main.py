"""Persistent notes stored in SQLite by apsw — one screen, one table, one connection."""

import os
import sqlite3  # stdlib — used only to contrast the two SQLite engines on screen
import threading

import apsw
import apsw.bestpractice
import flet as ft

# Must run before any connection is opened: these are connection hooks, so they apply
# only to connections created afterwards (WAL, foreign keys, a 100 ms busy timeout,
# and double-quoted string literals rejected).
apsw.bestpractice.apply(apsw.bestpractice.recommended)

# FLET_APP_STORAGE_DATA is durable, app-private storage. Flet also makes it the working
# directory on device, so a bare "notes.db" would land there too — this spells it out.
db = apsw.Connection(os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "notes.db"))
db.set_busy_timeout(5000)  # 100 ms (the bestpractice default) is thin for a UI app
db.execute("CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, text TEXT)")

# This Connection may be used from any thread, but not by two at the same time: apsw
# raises ThreadingViolationError ("the Connection is busy in another thread") rather
# than waiting. Flet's thread pool can overlap handlers, so serialise every use.
db_lock = threading.Lock()


def main(page: ft.Page):
    """A field to type a note into, an Add button, and the rows already in the table.

    The header prints the SQLite apsw embeds next to the one the stdlib sees, which is
    the quickest way to see how far apart they are on a given device.
    """

    def load():
        """Rebuild the list from the table.

        Leaves the update to the caller: this runs both at startup, where auto-update
        covers it, and from a worker thread, where it does not.
        """
        with db_lock:
            # Materialise inside the lock: an unconsumed cursor keeps the
            # connection busy, which is what another thread would collide with.
            rows = list(db.execute("SELECT id, text FROM notes ORDER BY id DESC"))
        notes.controls = [ft.Text(f"{note_id}. {text}") for note_id, text in rows]

    def insert(text: str):
        """Write one note and redraw the list. Runs in the thread pool."""
        with db_lock:
            db.execute("INSERT INTO notes(text) VALUES(?)", (text,))
        load()
        page.update()  # auto-update does not reach background threads

    def add():
        """Take the typed note and send the write off the UI thread.

        Serves both the button and the field's on_submit, and clears the field before
        dispatching so a second tap cannot resend the same text.
        """
        text = (field.value or "").strip()
        if text:
            field.value = ""
            page.run_thread(insert, text)

    page.appbar = ft.AppBar(title=ft.Text("apsw notes"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"apsw {apsw.apswversion()} embeds SQLite "
                        f"{apsw.sqlitelibversion()} — the stdlib sqlite3 here sees "
                        f"{sqlite3.sqlite_version}",
                        size=12,
                    ),
                    ft.Row(
                        controls=[
                            field := ft.TextField(
                                label="New note", expand=True, on_submit=add
                            ),
                            ft.Button("Add", icon=ft.Icons.ADD, on_click=add),
                        ]
                    ),
                    notes := ft.ListView(expand=True, spacing=4),
                ]
            ),
        )
    )

    load()


if __name__ == "__main__":
    ft.run(main)
