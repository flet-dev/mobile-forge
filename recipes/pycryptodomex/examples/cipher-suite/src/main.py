import flet as ft
from suite import ALGORITHMS, NAMESPACE, VERSION, namespaces_present, seal

LABELS = {"AES-256-GCM": "AES-GCM", "ChaCha20-Poly1305": "ChaCha20"}


def row(label, value):
    """One line of the result table: a label, then the value beside it."""
    return ft.Row(
        controls=[
            ft.Text(label, size=12, expand=2),
            ft.Text(value, size=12, expand=3, selectable=True),
        ]
    )


def main(page: ft.Page):
    """Seal a message through whichever namespace the import resolved to."""
    present = namespaces_present()

    def run(e=None):
        """Lock the controls and hand the whole job to a background thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Seal and reopen the message, then rebuild the table from plain values.

        The KDF is why this is on a thread at all: scrypt is deliberately slow,
        and running it in the click handler would freeze the UI for as long as
        it takes. Exceptions are caught and shown, because `page.run_thread`
        never retrieves the worker's result and one raised here would otherwise
        surface nowhere.
        """
        try:
            out = seal(algorithm.selected[0], message.value, password.value)
        except Exception as exc:
            results.controls = [row("failed", f"{type(exc).__name__}: {exc}")]
        else:
            results.controls = [
                row("cipher came from", out["module"]),
                ft.Divider(height=1),
                row("nonce", out["nonce"]),
                row("ciphertext", out["ciphertext"]),
                row("tag", out["tag"]),
                ft.Divider(height=1),
                row("reopened", out["recovered"]),
                row("matches input", out["matched"]),
                row("modified tag", out["rejected"]),
                ft.Divider(height=1),
                row("derive + seal + open", out["elapsed"]),
            ]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Cipher suite"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"imported as {NAMESPACE} {VERSION}",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(
                        "installed here: " + " and ".join(present),
                        size=12,
                        # Two entries is the same library twice; say so loudly.
                        color=ft.Colors.ERROR if len(present) > 1 else None,
                    ),
                    message := ft.TextField(
                        label="Message",
                        value="the same library, either way",
                        dense=True,
                        autocorrect=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_submit=run,
                    ),
                    password := ft.TextField(
                        label="Password",
                        value="a passphrase",
                        dense=True,
                        password=True,
                        can_reveal_password=True,
                        on_submit=run,
                    ),
                    algorithm := ft.SegmentedButton(
                        # 0.86 types `selected` as a list, not a set.
                        selected=[ALGORITHMS[0]],
                        segments=[
                            ft.Segment(value=name, label=ft.Text(LABELS[name], size=11))
                            for name in ALGORITHMS
                        ],
                        on_change=run,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Seal and open",
                                icon=ft.Icons.LOCK_OUTLINE,
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
