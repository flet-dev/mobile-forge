import flet as ft
from clip import clip_path, library_versions, probe, thumbnails, write_clip


def still(label, jpeg):
    """One filmstrip cell: a decoded frame above the timestamp it was taken at."""
    return ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=4,
        controls=[
            ft.Image(src=jpeg, width=140, border_radius=6, gapless_playback=True),
            ft.Text(label, size=11),
        ],
    )


def row(label, value):
    """One line of the probe readout: label on the left, what was read on the right."""
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[ft.Text(label, size=12), ft.Text(value, size=12, selectable=True)],
    )


def main(page: ft.Page):
    def run():
        """Lock the button, raise the spinner, and hand the work to a thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Write the clip, probe it, extract stills, and update the page.

        run_thread swallows exceptions and does not carry an automatic update
        with it, so this catches its own failures and ends with page.update().
        """
        try:
            path = clip_path()
            elapsed = write_clip(path)
            readout.controls = [row(*pair) for pair in probe(path)]
            readout.controls.append(row("encoded in", f"{elapsed:.2f} s"))
            strip.controls = [still(label, jpeg) for label, jpeg in thumbnails(path)]
        except Exception as exc:
            readout.controls = [ft.Text(str(exc), size=12, selectable=True)]
        button.disabled = False
        spinner.visible = False
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("clip roundtrip"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(library_versions(), size=11),
                    ft.Text(
                        "Writes a 3-second MP4 into app storage, reopens it, and "
                        "seeks to four points to pull the frames below.",
                        size=11,
                    ),
                    strip := ft.Row(
                        wrap=True,
                        spacing=8,
                        run_spacing=8,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Write a clip",
                                icon=ft.Icons.MOVIE_CREATION,
                                on_click=run,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    readout := ft.Column(spacing=2),
                ],
            ),
        )
    )

    run()


if __name__ == "__main__":
    ft.run(main)
