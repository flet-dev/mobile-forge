import platform

import flet as ft
from bakeoff import (
    HAVE_BROTLI,
    PAYLOADS,
    integrity,
    library,
    measure,
    payload,
    small_rows,
    summarise,
    verified,
)

CODEC_WEIGHTS = (5, 4, 3, 4, 4)

SMALL_WEIGHTS = (6, 3, 3, 3, 3)


def table_row(values, weights, size=10):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Run the whole comparison on this device and show what each codec costs.

    Everything on screen is computed here rather than bundled, and every frame is
    verified against the source before its numbers are shown. When brotli itself
    is missing the app degrades instead of crashing: the stdlib codecs still run
    and the header says what the import raised.
    """
    shown = PAYLOADS[0]  # the payload the table on screen describes

    def start():
        """Send one comparison to the thread pool and lock the picker while it runs.

        The guard is set here, in the synchronous handler, rather than in the
        worker: `run_thread` only schedules, so a `disabled` set inside the worker
        would not have taken effect before a second tap could start an
        overlapping run.

        A tap that beat that `disabled` to the client is dropped, and the picker
        is put back to the payload being measured. The client moves its own
        highlight the instant it is tapped, so without the reset the button would
        name one payload while the table below described another.
        """
        nonlocal shown
        if picker.disabled:
            picker.selected = [shown]
            page.update()
            return
        shown = picker.selected[0]  # SegmentedButton.selected is a list
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run, shown)

    def run(name):
        """Measure one payload, then the short inputs and the bit flips.

        The payload is passed in rather than read off the picker, because the
        worker starts after the handler returns and a tap landing in between
        moves `picker.selected` out from under it.

        Wrapped in try/except because `page.run_thread` discards whatever a worker
        raises - without this, a failure would look like a screen that quietly
        stopped updating. Both tables are cleared on the error path, since numbers
        left from the previous run would read as though they described the error.
        """
        try:
            data = payload(name)
            rows, results, replay = measure(data)
            table.controls = [
                table_row(
                    ("codec", "bytes", "ratio", "write ms", "read ms"), CODEC_WEIGHTS
                ),
                ft.Divider(height=1),
                *(table_row(row, CODEC_WEIGHTS) for row in rows),
            ]
            summary.value = summarise(data, results)
            checks.value = verified(data, results, replay)
            small.controls = [
                table_row(
                    ("short input", "raw", "brotli", "zlib 9", "gzip 9"), SMALL_WEIGHTS
                ),
                ft.Divider(height=1),
                *(table_row(row, SMALL_WEIGHTS) for row in small_rows()),
            ]
            damage.value = integrity(data)
        except Exception as error:  # the worker must never let one escape
            table.controls = []
            small.controls = []
            checks.value = ""
            damage.value = ""
            summary.value = f"{type(error).__name__}: {error}"

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("brotli bake-off"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        library(),
                        size=11,
                        color=None if HAVE_BROTLI else ft.Colors.ERROR,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} - {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                segments=[
                                    ft.Segment(value=name, label=ft.Text(name))
                                    for name in PAYLOADS
                                ],
                                selected=[PAYLOADS[0]],
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    table := ft.Column(spacing=4),
                    summary := ft.Text(size=11),
                    checks := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("short inputs, in bytes", size=11),
                    small := ft.Column(spacing=4),
                    ft.Divider(),
                    damage := ft.Text(size=11),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
