import flet as ft
from shapes import KINDS, VERSION, analyse, scene


def row(label, *cells):
    """One line of the results table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    canvas, placed = scene()

    def redraw():
        """Draw a fresh set of shapes, then segment the new scene."""
        nonlocal canvas, placed
        canvas, placed = scene()
        segment()

    def segment():
        """Lock the controls and hand the pipeline to a background thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Segment at the slider's noise level and put the annotated frame on screen.

        The body of the thread segment() starts. Push the noise up and the contour
        count runs into five figures while the total still comes back as nine: it is
        the minimum-area filter, not the threshold, that survives a ruined picture.
        At the very top of the slider the per-kind labels do slip, because noise
        roughens an outline until approxPolyDP reads a circle as four-sided.
        """
        frame, found, contours, elapsed = analyse(canvas, noise.value)
        view.src = frame
        results.controls = [
            row("", "placed", "found"),
            ft.Divider(height=1),
            *(row(kind, placed[kind], found[kind]) for kind in KINDS),
            ft.Divider(height=1),
            row("contours before filter", contours),
            row("segmented in", f"{elapsed:.0f} ms"),
            row("jpeg sent to ft.Image", f"{len(frame) / 1024:.0f} KB"),
        ]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("cv2 shape finder"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    view := ft.Image(
                        src=b"",
                        fit=ft.BoxFit.CONTAIN,
                        border_radius=8,
                        gapless_playback=True,
                    ),
                    ft.Text("Noise added before segmentation", size=12),
                    noise := ft.Slider(
                        min=0,
                        max=150,
                        value=30,
                        divisions=10,
                        round=0,
                        label="σ {value}",
                        # on_change would re-run the whole pipeline for every pixel the
                        # thumb travels; on_change_end runs it once, on release.
                        on_change_end=segment,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "New scene",
                                icon=ft.Icons.SHUFFLE,
                                on_click=redraw,
                            ),
                            spinner := ft.ProgressRing(
                                width=20,
                                height=20,
                                visible=False,
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                ],
            ),
        )
    )

    segment()


if __name__ == "__main__":
    ft.run(main)
