import flet as ft
from petals import VERSIONS, classify, load_or_fit


def main(page: ft.Page):
    """Two petal measurements, a Classify button, and the species the model predicts.

    The line at the bottom says whether this launch fitted the model or reloaded the
    one in app storage, and prints the path it lives at.
    """

    model = None

    def prepare():
        """Get the model onto `model`, then let the user classify with it.

        fit() is CPU-bound and would block the first frame, so this runs in the
        thread pool and enables Classify when it lands. run_thread swallows what a
        worker raises, so catch it here or a failed fit leaves "Fitting…" forever.
        """
        nonlocal model
        try:
            model, status.value = load_or_fit()
            button.disabled = False
        except Exception as exc:
            status.value = str(exc)
        page.update()  # auto-update does not reach background threads

    def on_classify():
        """Answer the two typed measurements, or say why they cannot be read.

        predict on a single row is fast enough to stay on the event handler, which
        is why nothing here updates the page itself.
        """
        try:
            species, confidence = classify(model, length.value, width.value)
        except (TypeError, ValueError):
            result.value = "Enter two numbers"
            return
        result.value = f"{species} — {confidence:.0%} confident"

    page.appbar = ft.AppBar(title=ft.Text("Petal classifier"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(VERSIONS, size=12),
                    ft.Row(
                        controls=[
                            length := ft.TextField(
                                label="Petal length (cm)",
                                value="4.5",
                                keyboard_type=ft.KeyboardType.NUMBER,
                                expand=True,
                            ),
                            width := ft.TextField(
                                label="Petal width (cm)",
                                value="1.4",
                                keyboard_type=ft.KeyboardType.NUMBER,
                                expand=True,
                            ),
                        ]
                    ),
                    button := ft.Button(
                        content="Classify",
                        icon=ft.Icons.SCIENCE,
                        disabled=True,
                        on_click=on_classify,
                    ),
                    result := ft.Text(size=22, weight=ft.FontWeight.BOLD),
                    status := ft.Text("Fitting…", size=11, selectable=True),
                ]
            ),
        )
    )

    page.run_thread(prepare)


if __name__ == "__main__":
    ft.run(main)
