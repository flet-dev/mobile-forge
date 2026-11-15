"""Offline notes and a persistent launch counter for Android restart testing."""

import json
import os
from pathlib import Path

import flet as ft
from surrealdb import AsyncSurreal, RecordID, SurrealError


async def main(page: ft.Page) -> None:
    page.title = "Embedded SurrealDB"
    page.padding = 24
    status = ft.Text("Opening the local SurrealKV database…")
    page.add(ft.Text("Offline notes", size=28), status)

    # Flet sets this to persistent, app-private storage on mobile.
    data_dir = Path(
        os.environ.get("FLET_APP_STORAGE_DATA", str(Path.home() / ".surrealdb-notes"))
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "surrealdb"
    try:
        # Keep this connection alive for all event handlers, not one per click.
        db = AsyncSurreal(f"surrealkv://{db_path}")
        await db.connect()
        await db.use("app", "main")
        await db.query(
            "DEFINE TABLE IF NOT EXISTS app_state SCHEMALESS;"
            "DEFINE TABLE IF NOT EXISTS notes SCHEMALESS;"
        )
        counter_id = RecordID("app_state", "launches")
        previous = await db.select(counter_id)
        launches = (previous["count"] if previous else 0) + 1
        await db.upsert(counter_id, {"count": launches})
        persisted = await db.select(counter_id)
        assert persisted["count"] == launches
        print(
            "SURREALDB_STARTUP "
            + json.dumps({"launches": launches, "path": str(db_path)}),
            flush=True,
        )
    except Exception as exc:
        status.value = f"Database failed: {exc}"
        page.update()
        raise

    status.value = f"Embedded engine ready · persistent launch #{launches}"
    entry = ft.TextField(label="New note", multiline=True)
    notes = ft.Column()
    feedback = ft.Text()

    async def refresh() -> None:
        rows = await db.select("notes")
        notes.controls.clear()
        for row in rows:
            record = row["id"]

            async def delete_note(
                event: ft.ControlEvent, record_id: RecordID = record
            ) -> None:
                try:
                    await db.delete(record_id)
                    await refresh()
                except (SurrealError, OSError) as exc:
                    feedback.value = str(exc)
                    page.update()

            notes.controls.append(
                ft.Row(
                    [
                        ft.Text(row["text"], expand=True),
                        ft.TextButton("Delete", on_click=delete_note),
                    ]
                )
            )
        page.update()

    async def save_note(event: ft.ControlEvent) -> None:
        text = (entry.value or "").strip()
        if not text:
            return
        try:
            await db.create("notes", {"text": text})
            entry.value = ""
            feedback.value = "Saved on this device — no server or network."
            await refresh()
        except (SurrealError, OSError) as exc:
            feedback.value = str(exc)
            page.update()

    async def close_database(event: ft.ControlEvent) -> None:
        await db.close()

    page.on_disconnect = close_database
    page.add(entry, ft.Button("Save note", on_click=save_note), feedback, notes)
    await refresh()


ft.run(main)
