import flet as ft
from exchange import report


def line(label, value):
    """One row of the panel: a label on the left, a value on the right."""
    return ft.Row(
        controls=[
            ft.Text(label, size=12, expand=4),
            ft.Text(value, size=12, expand=5, selectable=True),
        ]
    )


def head(text):
    """A section heading inside the results panel."""
    return ft.Container(
        content=ft.Text(text, size=12, weight=ft.FontWeight.BOLD),
        padding=ft.Padding(0, 8, 0, 2),
    )


def main(page: ft.Page):
    """Two password fields and one panel, filled before the first frame.

    Everything runs on a worker thread: the client half of OPAQUE is memory-hard
    by design, and one run of the panel pays for four of those derivations.
    """

    def run(e=None):
        """Lock the controls and hand the whole exchange to a worker thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Run the exchange and turn its rows into controls.

        The body is wrapped because run_thread swallows exceptions: an unhandled
        raise here would leave the button disabled and the spinner turning with
        nothing on screen to say why. An empty field falls back to its hint, so
        the panel fills itself on launch.
        """
        try:
            secret = (enrolled.value or "").strip() or enrolled.hint_text
            typed = (retyped.value or "").strip() or retyped.hint_text
            results.controls = [
                head(label) if value is None else line(label, value)
                for label, value in report(secret, typed)
            ]
        except Exception as exc:
            results.controls = [line("failed", f"{type(exc).__name__}: {exc}")]
        finally:
            button.disabled = False
            spinner.visible = False
            page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("OPAQUE exchange"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        "A password registered with a server that never sees it, "
                        "then two login attempts against the record it kept.",
                        size=12,
                    ),
                    enrolled := ft.TextField(
                        label="Password at registration",
                        hint_text="correct horse battery staple",
                        dense=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_submit=run,
                    ),
                    retyped := ft.TextField(
                        label="Password typed at the second login",
                        hint_text="correct horse battery stapl",
                        dense=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_submit=run,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Run the exchange",
                                icon=ft.Icons.KEY,
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
