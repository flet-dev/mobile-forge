import flet as ft
from keys import (
    LOADED,
    RATE_HEADER,
    SCHEMES,
    implementation,
    interop,
    measure,
    runtime,
)

RATE_WEIGHTS = (5, 4, 5)


def table_row(values):
    """One row of the rate table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=weight)
            for value, weight in zip(values, RATE_WEIGHTS)
        ]
    )


def sample_row(text):
    """One id in a monospace face, so a shared prefix lines up down the column."""
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def main(page: ft.Page):
    """Generate a batch under the chosen scheme and report what kind of key it is.

    Four questions, all answered from ids made on this device: what one id costs,
    whether the batch comes out already sorted, what instant an id carries, and
    whether a time window can be selected by comparing key text alone. `keys`
    guards its import of uuid-utils, so a missing wheel falls back to the stdlib
    columns rather than ending the session.
    """
    shown = SCHEMES[0]  # the scheme the tables currently describe

    def start():
        """Send one scheme to the thread pool and lock the picker meanwhile.

        The guard is set here rather than in the worker because `run_thread` only
        schedules: a `disabled` set inside the worker would not reach the client
        before a second tap could start an overlapping run. A tap that beats it is
        dropped, and the picker is put back to the scheme being measured because
        the client moves its own highlight the instant it is tapped.
        """
        nonlocal shown
        if picker.disabled:
            picker.selected = [shown]
            page.update()
            return
        shown = picker.selected[0]
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run, shown)

    def run(scheme):
        """Measure one scheme on a background thread and fill the panels from it.

        The scheme is passed in rather than read off the picker, because the worker
        starts after the handler returned and a tap landing in between would move
        `picker.selected` out from under it. The try/except is not optional:
        `page.run_thread` discards whatever a worker raises, so a failure without it
        looks like a screen that quietly stopped updating. Panels are cleared on that
        path so numbers from the previous scheme cannot be read as describing this one.
        """
        try:
            report = measure(scheme)
            rates.controls = [
                table_row(RATE_HEADER),
                ft.Divider(height=1),
                *(table_row(row) for row in report.rows),
            ]
            samples.controls = [sample_row(text) for text in report.samples]
            summary.value = report.summary
            ordering.value = report.ordering
            stamps.value = report.stamps
            window.value = report.window
            nodes.value = report.nodes
        except Exception as error:  # the worker must never let one escape
            rates.controls = []
            samples.controls = []
            ordering.value = stamps.value = window.value = nodes.value = ""
            summary.value = f"{type(error).__name__}: {error}"

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("uuid-utils id generator"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        implementation(),
                        size=11,
                        color=None if LOADED else ft.Colors.ERROR,
                    ),
                    ft.Text(runtime(), size=11),
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                segments=[
                                    ft.Segment(value=name, label=ft.Text(name))
                                    for name in SCHEMES
                                ],
                                selected=[SCHEMES[0]],  # a set is not serialisable
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    rates := ft.Column(spacing=4),
                    summary := ft.Text(size=11),
                    ordering := ft.Text(size=11),
                    ft.Divider(),
                    samples := ft.Column(spacing=2),
                    stamps := ft.Text(size=11),
                    window := ft.Text(size=11),
                    ft.Divider(),
                    nodes := ft.Text(size=11),
                    ft.Text(interop(), size=11),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
