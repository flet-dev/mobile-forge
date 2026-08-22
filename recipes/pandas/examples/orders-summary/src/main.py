import flet as ft
from orders import CSV_PATH, GROUPINGS, VERSION, summarise


def main(page: ft.Page):
    """Show the totals for the chosen grouping, with the CSV's full path at the foot."""

    def refresh():
        """Put the screen into its loading state and run the grouping off the UI thread.

        Disabling the selector for the duration keeps a second tap from starting a
        parallel group-by that could finish out of order and overwrite the newer table.
        """
        results.controls = []
        choice.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Group the orders and rebuild the table, on the thread `refresh` started.

        The CSV is read on the first call only — the frame is kept in `orders.py` — which
        is why the read happens here rather than at import time: a slow first read must
        not hold up the first frame.
        """
        key = choice.selected[0]
        rows, count, storage = summarise(key)

        header.value = f"{VERSION} — {count} rows, text columns stored as {storage}"
        results.controls = [
            ft.DataTable(
                column_spacing=16,
                columns=[
                    ft.DataColumn(ft.Text(GROUPINGS[key])),
                    ft.DataColumn(ft.Text("Orders"), numeric=True),
                    ft.DataColumn(ft.Text("Units"), numeric=True),
                    ft.DataColumn(ft.Text("Revenue"), numeric=True),
                ],
                rows=[
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(row["label"])),
                            ft.DataCell(ft.Text(f"{row['orders']}")),
                            ft.DataCell(ft.Text(f"{row['units']}")),
                            ft.DataCell(ft.Text(f"{row['revenue']:,.0f}")),
                        ]
                    )
                    for row in rows
                ],
            )
        ]
        choice.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("pandas orders"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    header := ft.Text(size=12),
                    ft.Row(
                        controls=[
                            choice := ft.SegmentedButton(
                                segments=[
                                    ft.Segment(value=column, label=ft.Text(label))
                                    for column, label in GROUPINGS.items()
                                ],
                                selected=["region"],
                                show_selected_icon=False,
                                on_change=refresh,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=0),
                    ft.Text(CSV_PATH, size=10, selectable=True),
                ],
            ),
        )
    )

    refresh()


if __name__ == "__main__":
    ft.run(main)
