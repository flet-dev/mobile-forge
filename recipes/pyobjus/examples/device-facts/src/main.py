import flet as ft
from device import LEVELS, blocked_reason, header, read_all

def heading(label):
    """A bold section label."""
    return ft.Text(label, size=12, weight=ft.FontWeight.BOLD)


def main(page: ft.Page):
    """iOS facts read through the Objective-C runtime, each next to a second reading.

    The slider picks how many calls to time; releasing it re-reads every block,
    because uptime, low-power mode and the timings all move between runs.
    Nothing on this screen needs a permission or an Info.plist usage string,
    and every value is checkable against the phone: Settings > General > About
    for the identity block.
    """
    pending = LEVELS[-1]
    panels = {
        name: ft.Text(size=12, selectable=True)
        for name in ("identity", "machine", "storage", "timing", "arguments")
    }

    def run():
        """Read every block and fill the screen. Runs off the UI thread.

        `page.run_thread` never retrieves the worker's future, so anything
        raised here would surface nowhere at all and leave the previous run's
        numbers on screen. Each block carries its own error text, and the
        closing `page.update()` is what makes any of it appear.
        """
        try:
            for name, lines in read_all(pending).items():
                panels[name].value = "\n".join(lines)
        except Exception as error:
            caption.value = f"{type(error).__name__}: {error}"
        finally:
            workload.disabled = False
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
        pending = LEVELS[int(workload.value)]
        caption.value = f"{pending} calls of each kind"
        page.update()
        page.run_thread(run)

    def preview():
        """Caption the level under the thumb while it is still moving."""
        caption.value = f"{LEVELS[int(workload.value)]} calls of each kind"

    page.appbar = ft.AppBar(title=ft.Text("iOS device facts"), center_title=True)
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
                    ft.Text(header(page.platform.value), size=11, selectable=True),
                    heading("identity: pyobjus vs raw objc_msgSend"),
                    panels["identity"],
                    heading("machine"),
                    panels["machine"],
                    heading("storage"),
                    panels["storage"],
                    caption := heading(""),
                    workload := ft.Slider(
                        value=len(LEVELS) - 1,
                        min=0,
                        max=len(LEVELS) - 1,
                        divisions=len(LEVELS) - 1,
                        on_change=preview,
                        on_change_end=start,
                    ),
                    panels["timing"],
                    heading("argument types"),
                    panels["arguments"],
                ],
            ),
        )
    )

    preview()
    start()


if __name__ == "__main__":
    ft.run(main)
