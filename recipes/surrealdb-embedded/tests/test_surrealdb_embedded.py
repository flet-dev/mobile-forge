import asyncio
import importlib.util
import sys
from pathlib import Path

from surrealdb import AsyncSurreal, RecordID, Surreal
from surrealdb_embedded import SyncEmbeddedDB


def test_native_engine() -> None:
    """Load the native binding and initialize an in-memory engine."""
    native = importlib.util.find_spec("surrealdb_embedded._ext")
    assert native is not None
    print(f"SURREALDB_RUNTIME python={sys.version} native={native.origin}", flush=True)
    with SyncEmbeddedDB("mem://") as db:
        db.connect()


def test_sync_crud() -> None:
    """Run create, select, update, query and delete through the Python SDK."""
    record = RecordID("notes", "smoke")
    with Surreal("mem://") as db:
        db.use("app", "main")
        db.create(record, {"text": "Saved locally", "count": 1})
        assert db.select(record).execute()["text"] == "Saved locally"
        db.update(record, {"text": "Updated", "count": 2})
        assert db.select(record).execute()["count"] == 2
        assert db.query("RETURN 6 * 7;").execute() == [42]
        db.delete(record).execute()
        assert not db.select(record).execute()


def test_persistent_database(tmp_path: Path) -> None:
    """Keep a SurrealKV record after closing and reopening its datastore."""
    url = f"surrealkv://{tmp_path / 'database'}"
    record = RecordID("notes", "persistent")
    with Surreal(url) as db:
        db.use("app", "main")
        db.create(record, {"text": "Survives reopen"})
    with Surreal(url) as db:
        db.use("app", "main")
        assert db.select(record).execute()["text"] == "Survives reopen"


def test_async_sdk() -> None:
    """Run the asynchronous binding in a real Python event loop."""

    async def exercise() -> None:
        async with AsyncSurreal("mem://") as db:
            await db.use("app", "main")
            record = RecordID("notes", "async")
            await db.create(record, {"text": "Async native engine"})
            assert (await db.select(record))["text"] == "Async native engine"
            await db.delete(record)

    asyncio.run(exercise())
