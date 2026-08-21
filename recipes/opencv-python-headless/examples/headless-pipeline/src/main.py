import flet as ft
from pipeline import STAGES, VERSION, gui_backend, process, scene


def stage_view(label, frame):
    """One pipeline stage: its JPEG above the name of the step that made it."""
    return ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=4,
        controls=[
            ft.Image(
                src=frame,
                width=140,
                height=140,
                border_radius=6,
                gapless_playback=True,
            ),
            ft.Text(label, size=11),
        ],
    )


def row(label, value):
    """One line of the readout: a label on the left, a measurement on the right."""
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[ft.Text(label, size=12), ft.Text(value, size=12)],
    )


def main(page: ft.Page):
    """Show a cv2 pipeline running with no window to draw it into.

    The backend line is the point of the app: it reads NONE on Android and
    nothing at all on iOS, so the three stages arrive as JPEG bytes in ft.Image
    controls rather than through cv2.imshow.
    """

    def run(e=None):
        """Lock the button, raise the spinner, and hand the work to a thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Build a scene, run the pipeline, and put every stage on screen.

        The body of the thread run() starts. run_thread swallows exceptions and
        does not carry the automatic update with it, so the handler catches its
        own failures and finishes with an explicit page.update().
        """
        try:
            stages, edge_share, elapsed = process(scene())
            strip.controls = [stage_view(name, frame) for name, frame in stages]
            readout.controls = [
                row("edge pixels", f"{edge_share * 100:.1f}%"),
                row("pipeline", f"{elapsed:.1f} ms"),
                row(
                    "jpeg on screen",
                    f"{sum(len(f) for _, f in stages) / 1000:.0f} KB",
                ),
            ]
        except Exception as exc:
            readout.controls = [ft.Text(str(exc), size=12)]
        button.disabled = False
        spinner.visible = False
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("headless pipeline"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    ft.Text(f"GUI backend: {gui_backend()}", size=12),
                    ft.Text(
                        "No backend means no cv2.imshow, so each stage below is "
                        "JPEG bytes handed to an ft.Image.",
                        size=11,
                    ),
                    strip := ft.Row(
                        wrap=True,
                        spacing=8,
                        run_spacing=8,
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[stage_view(name, b"") for name in STAGES],
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "New scene",
                                icon=ft.Icons.REFRESH,
                                on_click=run,
                            ),
                            spinner := ft.ProgressRing(
                                width=20,
                                height=20,
                                visible=False,
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
