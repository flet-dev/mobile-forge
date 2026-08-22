"""Decode one document three ways on this device and show which one validates it."""

import flet as ft
from orders import SIZES, benchmark, codec_line, malformed_report, plural, runtime_line

TIMING_WEIGHTS = (6, 3, 3, 3)

PANEL_WEIGHTS = (3, 10)


def table_row(values, weights, size=11):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Time three decoders on identical bytes, then show what each did with bad data.

    The timing table is only half the point: the column that matters is the last one,
    where msgspec is the only decoder that checked the document against a type. The
    panel underneath is the other half — the same three libraries on a document with
    one wrong field, where the two fast parsers hand back a wrong-typed value and say
    nothing.
    """

    def show_count():
        """Report the document size the next run will use, as the slider moves."""
        caption.value = f"{plural(SIZES[int(size.value)])} per document"

    def start():
        """Hand one run to a background thread and lock the slider while it works.

        The guard is tested and set here rather than inside `run` because this body is
        synchronous where `run_thread` only schedules: a `disabled` set inside the
        worker has not happened yet when this handler returns and Flet pushes the
        control states, so a second release would be accepted and two runs would
        rewrite the same table.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Put one benchmark on screen, clearing the last one if this one fails.

        The try/except is load-bearing: `page.run_thread` discards whatever a worker
        raises, so a mistake in here would look like a screen that quietly stopped
        updating. It clears the table on the way out, because timings left from the
        previous run read as though they described the error.
        """
        try:
            report = benchmark(SIZES[int(size.value)])
            head, *body = report.timings
            timings.controls = [
                table_row(head, TIMING_WEIGHTS),
                ft.Divider(height=1),
                *(table_row(line, TIMING_WEIGHTS) for line in body),
            ]
            payload_line.value = report.payload
            checks.value = report.checks
            aborts.value = report.aborts
        except Exception as error:
            timings.controls = []
            payload_line.value = ""
            checks.value = ""
            aborts.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def fill_panel():
        """Build the malformed-input panel from the calls made on this device."""
        panel.controls = []
        for label, outcomes in malformed_report():
            panel.controls.append(ft.Text(label, size=11, weight=ft.FontWeight.BOLD))
            panel.controls.extend(
                table_row(line, PANEL_WEIGHTS, 10) for line in outcomes
            )

    page.appbar = ft.AppBar(title=ft.Text("msgspec three ways"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(runtime_line(page.platform.value), size=11),
                    ft.Text(codec_line(), size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=0,
                        max=len(SIZES) - 1,
                        value=3,
                        divisions=len(SIZES) - 1,
                        on_change=show_count,
                        on_change_end=start,
                    ),
                    timings := ft.Column(spacing=4),
                    payload_line := ft.Text(size=11),
                    checks := ft.Text(size=11),
                    aborts := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("one record sent wrong, three libraries", size=11),
                    panel := ft.Column(spacing=2),
                ],
            ),
        )
    )

    show_count()
    fill_panel()
    start()


if __name__ == "__main__":
    ft.run(main)
