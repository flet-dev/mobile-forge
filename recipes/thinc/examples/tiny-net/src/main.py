import flet as ft
from net import VERSION, backend, gemm_race, train


def row(label, value):
    """One line of the results table: a label on the left, its value on the right."""
    return ft.Row(controls=[ft.Text(label, expand=3), ft.Text(value, expand=4)])


def main(page: ft.Page):
    """Train a thinc network on device and report the backend it ran on.

    Nothing here is a form waiting for input: the app trains once on startup so the
    first screen already carries an accuracy, a timing and the name of the ops class
    that produced them.
    """

    def relearn(_=None):
        """Lock the controls and hand a fresh training run to a background thread."""
        button.disabled = True
        width.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Train at the slider's hidden width and put every number on screen.

        Wrapped whole, because page.run_thread swallows exceptions: without the
        except clause a failure inside thinc would leave the button disabled for the
        rest of the session with nothing on screen to explain it.
        """
        try:
            info, trained, race = backend(), train(width.value), gemm_race()
            table.controls = [
                *(row(key, value) for key, value in info.items()),
                ft.Divider(height=1),
                *(row(key, value) for key, value in trained.items()),
                ft.Divider(height=1),
                *(row(key, value) for key, value in race.items()),
            ]
            status.value = ""
        except Exception as exc:
            status.value = str(exc)
        button.disabled = False
        width.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("thinc tiny net"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    ft.Text("Hidden layer width", size=12),
                    width := ft.Slider(
                        min=8,
                        max=128,
                        value=64,
                        divisions=15,
                        round=0,
                        label="{value} units",
                        # The width is written into the resolved config, so releasing
                        # the thumb rebuilds the model rather than resizing one.
                        on_change_end=relearn,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Train again",
                                icon=ft.Icons.MODEL_TRAINING,
                                on_click=relearn,
                            ),
                            spinner := ft.ProgressRing(
                                width=20,
                                height=20,
                                visible=False,
                            ),
                        ]
                    ),
                    status := ft.Text("", size=12, color=ft.Colors.ERROR),
                    table := ft.Column(spacing=4),
                ],
            ),
        )
    )

    relearn()


if __name__ == "__main__":
    ft.run(main)
