import flet as ft
from notebook import (
    add_note,
    count_launch,
    database_path,
    delete_note,
    list_notes,
    open_notebook,
)
from surrealdb import AsyncSurreal, RecordID, SurrealError


async def main(page: ft.Page):
    page.appbar = ft.AppBar(title=ft.Text("Offline notes"), center_title=True)
    status = ft.Text("Opening the database…")
    entry = ft.TextField(label="New note", multiline=True, expand=True)
    save = ft.Button("Save", disabled=True)
    notes = ft.Column()
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[status, ft.Row([entry, save]), ft.Divider(), notes],
                scroll=ft.ScrollMode.AUTO,
            ),
        )
    )

    path = database_path()
    try:
        db: AsyncSurreal = await open_notebook(path)
        launches = await count_launch(db)
    except (SurrealError, OSError) as exc:
        status.value = f"Database failed: {exc}"
        status.color = ft.Colors.RED
        page.update()
        return

    async def refresh():
        """Rebuild the list from the datastore, so it always shows what is on disk."""
        notes.controls = [
            ft.Row(
                controls=[
                    ft.Text(text, expand=True),
                    ft.IconButton(
                        ft.Icons.DELETE_OUTLINE,
                        on_click=lambda _, n=note: page.run_task(remove, n),
                    ),
                ]
            )
            for note, text in await list_notes(db)
        ]
        count = len(notes.controls)
        status.value = f"Launch #{launches} · {count} note{'' if count == 1 else 's'} in {path.name}"
        page.update()

    async def remove(note: RecordID):
        await delete_note(db, note)
        await refresh()

    async def store(_: ft.Event[ft.Button]):
        text = (entry.value or "").strip()
        if not text:
            return
        await add_note(db, text)
        entry.value = ""
        await refresh()

    async def close(_: ft.Event[ft.Page]):
        await db.close()

    save.on_click = store
    save.disabled = False
    page.on_disconnect = close
    await refresh()


ft.run(main)
