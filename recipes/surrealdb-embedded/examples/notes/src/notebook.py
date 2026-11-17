"""The SurrealDB side of the app: one embedded SurrealKV datastore on disk."""

import os
from pathlib import Path

from surrealdb import AsyncSurreal, RecordID


def database_path() -> Path:
    """Where the datastore lives: Flet's persistent app storage on a device."""
    root = Path(os.getenv("FLET_APP_STORAGE_DATA") or Path.home() / ".surrealdb-notes")
    root.mkdir(parents=True, exist_ok=True)
    return root / "notes.db"


async def open_notebook(path: Path) -> AsyncSurreal:
    """Open the datastore once; a second open of the same path fails on its lock."""
    db = AsyncSurreal(f"surrealkv://{path}")
    await db.connect()
    await db.use("app", "main")
    # Reading a table that was never defined raises NotFoundError, even when empty.
    await db.query(
        "DEFINE TABLE IF NOT EXISTS app_state SCHEMALESS;"
        "DEFINE TABLE IF NOT EXISTS notes SCHEMALESS;"
    )
    return db


async def count_launch(db: AsyncSurreal) -> int:
    """Increment and return a counter that only survives if the datastore does."""
    counter = RecordID("app_state", "launches")
    previous = await db.select(counter)
    launches = (previous["count"] if previous else 0) + 1
    await db.upsert(counter, {"count": launches})
    return launches


async def list_notes(db: AsyncSurreal) -> list[tuple[RecordID, str]]:
    """Every note, oldest first, as (record id, text)."""
    # query() returns one result list per statement. SurrealQL only orders by a
    # field the SELECT projects, hence `created`.
    (rows,) = await db.query("SELECT id, text, created FROM notes ORDER BY created;")
    return [(row["id"], row["text"]) for row in rows]


async def add_note(db: AsyncSurreal, text: str) -> None:
    """Store one note with a server-side timestamp to sort by."""
    await db.query(
        "CREATE notes SET text = $text, created = time::now();", {"text": text}
    )


async def delete_note(db: AsyncSurreal, note: RecordID) -> None:
    """Remove one note by its record id."""
    await db.delete(note)
