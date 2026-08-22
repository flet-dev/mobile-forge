import flet as ft
from notes import VERSIONS, all_notes, insert


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
        listing.controls = [
            ft.Text(f"{note_id}. {text}") for note_id, text in all_notes()
        ]

    def write(text):
        """Store one note and redraw the list. Runs in the thread pool."""
        insert(text)
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
            page.run_thread(write, text)

    page.appbar = ft.AppBar(title=ft.Text("apsw notes"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(VERSIONS, size=12),
                    ft.Row(
                        controls=[
                            field := ft.TextField(
                                label="New note", expand=True, on_submit=add
                            ),
                            ft.Button("Add", icon=ft.Icons.ADD, on_click=add),
                        ]
                    ),
                    listing := ft.ListView(expand=True, spacing=4),
                ]
            ),
        )
    )

    load()


if __name__ == "__main__":
    ft.run(main)
