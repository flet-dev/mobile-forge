import flet as ft
from device import LEVELS, banner, blocked_reason, read_all

BLOCKS = (
    ("identity: ART vs libc", "identity"),
    ("machine", "machine"),
    ("battery", "battery"),
    ("JNI round-trips", "timing"),
    ("sensors", "sensors"),
)


def main(page: ft.Page):
    """Android facts read through JNI, each printed next to a second reading of the same thing.

    The slider picks how many JNI round-trips to time; releasing it re-reads
    every block, because battery and heap move between runs. Nothing here needs
    a permission and every value is checkable against the phone: Settings >
    About phone for the identity block, the status bar for the battery one.
    """
    pending = LEVELS[-1]
    bodies = {key: ft.Column(spacing=2) for _, key in BLOCKS}
    sections = [
        control
        for title, key in BLOCKS
        for control in (ft.Text(title, size=12, weight=ft.FontWeight.BOLD), bodies[key])
    ]

    def render(result):
        """Pour each block's fact lines into its column, its error ahead of them."""
        for _, key in BLOCKS:
            lines, error = result[key]
            rows = [ft.Text(error, size=12, color=ft.Colors.ERROR)] if error else []
            bodies[key].controls = rows + [
                ft.Text(line, size=12, selectable=True) for line in lines or ()
            ]

    def run():
        """Read every block off the device and fill the screen. Runs off the UI thread.

        `page.run_thread` never looks at what the worker raised, so without the
        outer `except` a failure here would leave the screen frozen on the
        previous run's numbers with nothing to show for it. The explicit
        `page.update()` is what makes any of it appear.
        """
        try:
            render(read_all(pending))
        except Exception as error:
            caption.value = f"{type(error).__name__}: {error}"
        finally:
            workload.disabled = False
            spinner.visible = False
            page.update()

    def start():
        """Dispatch a re-read at the level the slider was released on.

        Bound to `on_change_end` so it fires once per gesture. The guard reads
        `disabled` back rather than trusting the assignment: disabling only
        queues the new state for the client, and `run_thread` submits to a
        shared pool, so a second release inside that window would put two
        workers on the same rows.
        """
        nonlocal pending
        if workload.disabled:
            return
        workload.disabled = True
        spinner.visible = True
        pending = LEVELS[int(workload.value)]
        page.update()
        page.run_thread(run)

    def preview():
        """Caption the level under the thumb while it is still moving."""
        caption.value = f"{LEVELS[int(workload.value)]} JNI round-trips"

    page.appbar = ft.AppBar(title=ft.Text("Android device facts"), center_title=True)
    blocked = blocked_reason()
    if blocked:
        page.add(
            ft.SafeArea(
                expand=True,
                content=ft.Card(
                    content=ft.Container(padding=16, content=ft.Text(blocked, size=13))
                ),
            )
        )
        return

    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(banner(page.platform.value), size=11, selectable=True),
                    ft.Row(
                        controls=[
                            caption := ft.Text(
                                size=12, weight=ft.FontWeight.BOLD, expand=True
                            ),
                            spinner := ft.ProgressRing(
                                width=14, height=14, visible=False
                            ),
                        ]
                    ),
                    workload := ft.Slider(
                        value=len(LEVELS) - 1,
                        min=0,
                        max=len(LEVELS) - 1,
                        divisions=len(LEVELS) - 1,
                        on_change=preview,
                        on_change_end=start,
                    ),
                    *sections,
                ],
            ),
        )
    )

    preview()
    start()


if __name__ == "__main__":
    ft.run(main)
