"""Total a synthetic order book with polars, sized by a slider and run off the UI thread."""

import flet as ft
from orders import COLUMNS, VERSION, summarise


def summary_table(totals):
    """Turn the rolled-up rows into a DataTable, one row per category."""
    return ft.DataTable(
        column_spacing=18,
        columns=[ft.DataColumn(name, numeric=name != "category") for name in COLUMNS],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(row["category"]),
                    ft.DataCell(f"{row['orders']:,}"),
                    ft.DataCell(f"{row['units']:,}"),
                    ft.DataCell(f"{row['revenue']:,.0f}"),
                ]
            )
            for row in totals
        ],
    )


def main(page: ft.Page):
    """Show a row-count slider and the per-category totals polars computes from it.

    The header reports the size of polars' own worker pool, which is what makes
    the aggregation parallel; the footer reports how long the pipeline took, so
    moving the slider shows how that scales.
    """

    def show_rows():
        """Report the order count the next run will use, while the slider moves."""
        caption.value = f"{int(slider.value):,} orders"

    def start():
        """Kick off a run when the slider is released, not on every pixel of the drag.

        The slider is disabled until compute() re-enables it, so two runs cannot
        overlap and fill the table in the wrong order.
        """
        slider.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Roll up at the current slider value, then draw the table.

        Runs on a background thread: polars parallelises inside `collect()`, but
        that call still blocks whichever thread makes it, and on the UI thread it
        would freeze the app for the whole pipeline.
        """
        rows = int(slider.value)
        totals, elapsed = summarise(rows)

        results.controls = [summary_table(totals)]
        footer.value = f"joined and grouped {rows:,} orders in {elapsed:.0f} ms"
        slider.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("polars sales rollup"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(VERSION, size=12),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    slider := ft.Slider(
                        min=50_000,
                        max=1_000_000,
                        value=250_000,
                        divisions=19,
                        on_change=show_rows,
                        on_change_end=start,
                    ),
                    # A table is the one control that reliably outgrows a phone,
                    # so let it scroll sideways instead of overflowing.
                    results := ft.Row(scroll=ft.ScrollMode.AUTO),
                    footer := ft.Text(size=12),
                ]
            ),
        )
    )

    show_rows()
    start()


if __name__ == "__main__":
    ft.run(main)
