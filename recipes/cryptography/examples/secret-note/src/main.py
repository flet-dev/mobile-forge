import flet as ft
from vault import VERSIONS, WrongPassphrase, is_sealed, seal, unseal


def main(page: ft.Page):
    """A passphrase field, the note, Lock and Unlock, and a status line.

    Every handler that derives a key runs on a background thread, so each one ends
    by calling finish() rather than returning a value.
    """

    def start(handler):
        """Check the passphrase, then hand the derivation to the thread pool.

        Both buttons come through here so the empty-passphrase case and the interim
        status are written once. scrypt is slow by design and never belongs on the
        UI thread.
        """
        if not (passphrase.value or "").strip():
            passphrase.error = "Enter a passphrase"
            page.update()
            return
        passphrase.error = None
        status.value = "Deriving key…"
        page.update()
        page.run_thread(handler)

    def lock():
        """Seal the note and take the plaintext off the screen."""
        written, ms = seal(passphrase.value.strip(), note.value or "")
        note.value = ""
        note.read_only = True
        unlock_button.disabled = False
        finish(f"Sealed {written} bytes of ciphertext · {ms:.0f} ms")

    def unlock():
        """Reopen the sealed note, or report that the passphrase was wrong.

        A wrong passphrase is an ordinary outcome, not a failure. Left uncaught in
        a worker thread it would surface nowhere at all: page.run_thread never
        retrieves the future.
        """
        try:
            text, ms = unseal(passphrase.value.strip())
        except WrongPassphrase:
            passphrase.error = "Wrong passphrase"
            finish("")
            return
        note.value = text
        note.read_only = False
        finish(f"Opened {len(text)} characters · {ms:.0f} ms")

    def finish(message):
        """Land a background handler's outcome on the screen."""
        status.value = message
        page.update()  # auto-update does not reach background threads

    def refresh():
        """Show whether a vault already exists, which is all the app knows at start.

        The note stays read-only while it is sealed: the field is empty then, and
        typing into it would look like editing the note rather than replacing it.
        """
        sealed = is_sealed()
        note.read_only = sealed
        unlock_button.disabled = not sealed
        status.value = "Sealed — unlock it." if sealed else "Nothing sealed yet."
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("Secret note"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSIONS, size=12),
                    passphrase := ft.TextField(
                        label="Passphrase",
                        password=True,
                        can_reveal_password=True,
                    ),
                    note := ft.TextField(label="Note", multiline=True, min_lines=3),
                    ft.Row(
                        controls=[
                            ft.Button(
                                "Lock",
                                icon=ft.Icons.LOCK,
                                on_click=lambda: start(lock),
                            ),
                            unlock_button := ft.Button(
                                "Unlock",
                                icon=ft.Icons.KEY,
                                on_click=lambda: start(unlock),
                            ),
                        ]
                    ),
                    status := ft.Text(size=12),
                ],
            ),
        )
    )

    refresh()


if __name__ == "__main__":
    ft.run(main)
