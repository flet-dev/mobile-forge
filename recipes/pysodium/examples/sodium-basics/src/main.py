import flet as ft
from vault import (
    costs,
    forgeries,
    keypair,
    master_key,
    seal,
    start,
    stash,
    unseal,
    unstash,
)


def line(label, value):
    """One row of the results panel: a label on the left, a value on the right."""
    return ft.Row(
        controls=[
            ft.Text(label, size=12, expand=3),
            ft.Text(value, size=12, expand=4, selectable=True),
        ]
    )


def main(page: ft.Page):
    """One panel, filled before the first frame rather than on a tap.

    libsodium is initialised and the identity loaded here, at the top, because
    every handler below assumes both have already happened.
    """
    libsodium = start()
    master, created = master_key()
    public_key, secret_key = keypair(master)

    def run(e=None):
        """Lock the controls and hand the whole sequence to a worker thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Seal the note, open it, stash it, then try to forge it.

        The body is wrapped because run_thread swallows exceptions: without the
        try/except a raise here would leave the button disabled and the spinner
        turning with nothing on screen to say why.
        """
        try:
            note = (field.value or "").strip() or field.hint_text
            sealed = seal(note, public_key)
            opened = unseal(sealed, public_key, secret_key)
            nonce, box = stash(note, master)
            tried, refused, leaked = forgeries(sealed, public_key, secret_key)
            measured = costs(master, public_key, secret_key)
            results.controls = [
                line("libsodium", libsodium),
                line("master key", "created just now" if created else "loaded"),
                line("sealed note", f"{len(sealed)} bytes from {len(note)} of text"),
                line("opened", opened),
                line("stashed", f"{len(nonce)}-byte nonce + {len(box)}-byte box"),
                line("stash opened", unstash(nonce, box, master)),
                ft.Divider(height=1),
                line("bits flipped", str(tried)),
                line("refused", f"{refused}  ({leaked} decoded)"),
                ft.Divider(height=1),
                *(line(label, f"{us:.0f} µs") for label, us in measured),
            ]
        except Exception as exc:
            results.controls = [line("failed", f"{type(exc).__name__}: {exc}")]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Sodium basics"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        "A note sealed to this device's public key, opened again, "
                        "then attacked one bit at a time.",
                        size=12,
                    ),
                    field := ft.TextField(
                        label="Note to seal",
                        hint_text="meet me at the old lighthouse",
                        dense=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_submit=run,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Seal and attack",
                                icon=ft.Icons.LOCK,
                                on_click=run,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                ],
            ),
        )
    )

    run()


if __name__ == "__main__":
    ft.run(main)
