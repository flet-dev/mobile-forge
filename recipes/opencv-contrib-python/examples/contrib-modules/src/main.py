import flet as ft
from scan import METHODS, VERSION, binarise, inventory, photograph


def score(label, value):
    """One line of the score table: a label, and its number on the right."""
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(label, size=13),
            ft.Text(value, size=13, weight=ft.FontWeight.BOLD),
        ],
    )


def module(name, note, present):
    """One contrib function: a tick if the loaded binary really carries it.

    The row names a function rather than stopping at its module, because on the
    desktop a directory orphaned by the other OpenCV distribution imports as an
    empty module and would tick anyway. A cross beside every name is what the base
    opencv-python wheel looks like from inside the app, which is what listing both
    distributions gets you.
    """
    return ft.Row(
        controls=[
            ft.Icon(
                ft.Icons.CHECK_CIRCLE if present else ft.Icons.CANCEL,
                size=15,
                color=ft.Colors.GREEN if present else ft.Colors.RED,
            ),
            ft.Text(f"cv2.{name}", size=12, weight=ft.FontWeight.BOLD),
            ft.Text(note, size=11, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
        ]
    )


def main(page: ft.Page):
    """Threshold a badly lit page three ways and list the contrib modules present.

    `photo` and `ink` are rebound whenever the slider moves rather than recomputed
    inside the worker: the truth mask has to come from the same render the threshold
    is scored against.
    """
    photo, ink = photograph(0.6)

    def relight(e=None):
        """Re-light the page at the slider's shadow depth, then threshold it again."""
        nonlocal photo, ink
        photo, ink = photograph(shadow.value / 100)
        start()

    def start(e=None):
        """Lock the controls, raise the spinner, and hand the work to a thread."""
        picker.disabled = True
        shadow.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Threshold with the selected method and put the result on screen.

        Otsu and Adaptive come from the base OpenCV build; Sauvola is
        cv2.ximgproc.niBlackThreshold and is the reason this app depends on
        opencv-contrib-python. All three keep nearly every stroke of text; what
        separates them is how much blank paper the shadow talks them into calling ink.

        The finally clause is what keeps a base opencv-python wheel from freezing
        the app: cv2.ximgproc would be missing, run_thread would swallow the
        AttributeError, and the controls would stay disabled with the spinner up.
        """
        try:
            mask, recall, smudge, elapsed = binarise(photo, ink, picker.selected[0])
            sheet.src = mask
            results.controls = [
                score("text recovered", f"{recall:.1f} %"),
                score("blank paper called ink", f"{smudge:.1f} %"),
                score("threshold took", f"{elapsed:.1f} ms"),
                score("png sent to ft.Image", f"{len(mask) / 1000:.0f} KB"),
            ]
        except Exception as error:
            results.controls = [score(type(error).__name__, str(error))]
        finally:
            picker.disabled = False
            shadow.disabled = False
            spinner.visible = False
            page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("cv2 contrib modules"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    # expand=True on a direct child of a scrolling Column collapses
                    # the viewport on iOS; inside a Row it fills the width safely.
                    ft.Row(
                        controls=[
                            sheet := ft.Image(
                                src=b"",
                                expand=True,
                                fit=ft.BoxFit.CONTAIN,
                                border_radius=8,
                                gapless_playback=True,
                            )
                        ]
                    ),
                    picker := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name, size=12))
                            for name in METHODS
                        ],
                        selected=[METHODS[-1]],
                        show_selected_icon=False,
                        on_change=start,
                    ),
                    ft.Row(
                        controls=[
                            ft.Text("Shadow over the page", size=12),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    shadow := ft.Slider(
                        min=0,
                        max=100,
                        value=60,
                        divisions=10,
                        round=0,
                        label="{value}%",
                        # on_change would re-render the page for every pixel the thumb
                        # travels; on_change_end runs the pipeline once, on release.
                        on_change_end=relight,
                    ),
                    results := ft.Column(spacing=2),
                    ft.Divider(),
                    ft.Text("Contrib calls in this wheel", weight=ft.FontWeight.BOLD),
                    *(module(*entry) for entry in inventory()),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
