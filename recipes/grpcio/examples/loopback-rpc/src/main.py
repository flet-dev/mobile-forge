import flet as ft
from loopback import PAYLOAD_KIB, VERSION, run_checks, start, transitions


def check_row(label, ok, detail, elapsed):
    """Lay one check out as a verdict line with its detail wrapping underneath.

    Two lines rather than one wide Row: the details are long enough that a
    non-scrolling Row would show Flutter's overflow stripes on a phone.
    """
    return ft.Column(
        spacing=2,
        controls=[
            ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.CHECK_CIRCLE if ok else ft.Icons.ERROR,
                        color=ft.Colors.GREEN if ok else ft.Colors.RED,
                        size=16,
                    ),
                    ft.Text(label, expand=True, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{elapsed:.1f} ms"),
                ]
            ),
            ft.Text(detail, size=11),
        ],
    )


def main(page: ft.Page):
    """Build the loopback stack once, then run its checks on every slider release.

    `main` is deliberately synchronous: gRPC's blocking API releases the GIL for the
    whole of a call, so the natural home for the work is a `page.run_thread` worker and
    there is no event loop to keep anything on.
    """
    calls, lines = start()

    def run_suite():
        """Run the checks on a worker thread, adding each row as its verdict lands.

        The tally is counted off the rows rather than asked for up front, so the footer
        can only ever report checks that actually ran. It ends in an explicit
        `page.update()` — and so does every row — because Flet's auto-update fires
        around event handlers, not inside a worker thread.
        """
        size = int(slider.value) * 1024
        results.controls = []
        footer.value = f"running at {size:,} B…"
        page.update()

        passed = count = 0
        total = 0.0
        try:
            for label, ok, detail, elapsed in run_checks(calls, size):
                passed += ok
                count += 1
                total += elapsed
                results.controls.append(check_row(label, ok, detail, elapsed))
                page.update()
            footer.value = (
                f"{passed}/{count} checks passed · {total:.1f} ms in total · "
                f"channel {transitions()}"
            )
        finally:
            slider.disabled = False
            page.update()

    def describe():
        """Keep the caption in step with the slider as it is dragged."""
        caption.value = f"{int(slider.value)} KiB per payload"

    def rerun():
        """Re-run the suite in a worker thread when the slider is released.

        The disable happens here rather than inside `run_suite`, and is read back as the
        re-entrancy guard: `run_thread` only schedules, so a flag set in the worker has
        not happened yet when this handler returns and Flet pushes the slider's state.
        Two releases in that window would queue two runs into one results column.
        """
        if slider.disabled:
            return
        slider.disabled = True
        page.run_thread(run_suite)

    page.appbar = ft.AppBar(title=ft.Text("gRPC loopback"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(f"{VERSION} on {page.platform.value}", size=12),
                    *(ft.Text(line, size=12) for line in lines),
                    caption := ft.Text(f"{PAYLOAD_KIB} KiB per payload"),
                    slider := ft.Slider(
                        min=1,
                        max=64,
                        value=PAYLOAD_KIB,
                        divisions=63,
                        label="{value} KiB",
                        on_change=describe,
                        on_change_end=rerun,
                    ),
                    results := ft.Column(spacing=8),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    slider.disabled = True
    page.run_thread(run_suite)


if __name__ == "__main__":
    ft.run(main)
