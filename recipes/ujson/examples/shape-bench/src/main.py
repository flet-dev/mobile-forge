import flet as ft
from shapes import COUNTS, audit, crosscheck, header, sweep, verdict

SHAPE_WEIGHTS = (5, 5, 4, 5, 4, 5)

AUDIT_WEIGHTS = (5, 6, 5)


def table_row(values, weights, size=11):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def duration(value):
    """Microseconds for a table cell: readable at 8 µs and at 80,000 µs."""
    return f"{value:,.1f}" if value < 1000 else f"{value:,.0f}"


def main(page: ft.Page):
    """Time both libraries on five payload shapes and audit the swap.

    The shape picker is the whole point: ujson is not uniformly faster, and a single
    document would let you conclude either way depending on which one you picked. Every
    number on screen is produced by this device rather than quoted from a desktop.
    """

    def start():
        """Hand one sweep to a background thread and lock the picker meanwhile.

        The guard is tested and set here rather than inside `run`, because this body is
        synchronous where `page.run_thread` only schedules: a `disabled` set inside the
        worker would not have happened yet when this handler returns and Flet pushes the
        control states, so a second tap would be accepted and two sweeps would rewrite
        the same table.
        """
        if picker.disabled:
            return
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Measure every shape at the chosen size and fill the table.

        The try/except is load-bearing: `page.run_thread` discards whatever a worker
        raises, so a mistake in here would look like a screen that quietly stopped
        updating. It clears the table on the way out as well as writing the message,
        because a previous run's timings left under an error read as though they
        described it.
        """
        try:
            choice = picker.selected[0]
            rows = sweep(choice)
            table.controls = [
                table_row(
                    ("shape", "u dumps", "json", "u loads", "json", "bytes"),
                    SHAPE_WEIGHTS,
                ),
                ft.Divider(height=1),
                *(
                    table_row(
                        (
                            row["name"],
                            duration(row["dumps"][0]),
                            duration(row["dumps"][1]),
                            duration(row["loads"][0]),
                            duration(row["loads"][1]),
                            f"{row['size_pct']:+.1f}%",
                        ),
                        SHAPE_WEIGHTS,
                    )
                    for row in rows
                ),
            ]
            checks.value = crosscheck(rows)
            summary.value = verdict(choice, rows)
        except Exception as error:
            table.controls = []
            checks.value = ""
            summary.value = f"{type(error).__name__}: {error}"

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    running, units = header(page.platform.value)
    page.appbar = ft.AppBar(title=ft.Text("ujson vs json"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(running, size=11),
                    ft.Text(units, size=11),
                    ft.Row(
                        scroll=ft.ScrollMode.AUTO,
                        controls=[
                            picker := ft.SegmentedButton(
                                segments=[
                                    ft.Segment(value=count, label=f"{int(count):,}")
                                    for count in COUNTS
                                ],
                                selected=[COUNTS[1]],
                                show_selected_icon=False,
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ],
                    ),
                    table := ft.Column(spacing=4),
                    checks := ft.Text(size=11),
                    summary := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("is the swap transparent?", size=11),
                    ft.Column(
                        spacing=4,
                        controls=[
                            table_row(("case", "ujson", "vs json"), AUDIT_WEIGHTS, 10),
                            ft.Divider(height=1),
                            *(table_row(row, AUDIT_WEIGHTS, 10) for row in audit()),
                        ],
                    ),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
