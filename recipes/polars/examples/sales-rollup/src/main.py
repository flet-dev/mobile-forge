"""Join a synthetic order book to a product catalogue and total it with the polars lazy API."""

import time

import flet as ft
import polars as pl

CATALOGUE = {
    "product_id": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    "product": [
        "espresso",
        "flat white",
        "croissant",
        "sourdough",
        "orange juice",
        "granola",
        "dish soap",
        "kitchen roll",
        "peas",
        "ice cream",
    ],
    "category": [
        "drinks",
        "drinks",
        "bakery",
        "bakery",
        "drinks",
        "grocery",
        "household",
        "household",
        "frozen",
        "frozen",
    ],
    "unit_price": [2.40, 3.60, 2.80, 4.10, 3.20, 5.50, 1.90, 2.60, 1.40, 4.80],
}

PRODUCTS = pl.DataFrame(CATALOGUE)
OPENING_HOURS = (7, 19)
COLUMNS = ("category", "orders", "units", "revenue")


def synthesise(rows):
    """Build the order book with polars expressions rather than Python lists.

    Every column is derived from the row index by a multiply-and-modulo, so the
    same slider position always produces the same table and a million rows cost
    milliseconds. Filling Python lists instead would dominate the timing this app
    exists to show.
    """
    return pl.DataFrame({"order_id": pl.int_range(rows, eager=True)}).with_columns(
        product_id=pl.col("order_id") * 2654435761 % PRODUCTS.height,
        quantity=pl.col("order_id") * 40503 % 4 + 1,
        hour=pl.col("order_id") * 7919 % 24,
    )


def rollup(orders):
    """Join the orders to the catalogue and total revenue per category.

    Nothing between `lazy()` and `collect()` runs when it is written: polars
    optimises the whole plan first, which is why the opening-hours filter is
    allowed to sit after the join here — it is pushed underneath it, and the
    columns the aggregation never reads are dropped before either step.
    """
    return (
        orders.lazy()
        .join(PRODUCTS.lazy(), on="product_id")
        .filter(pl.col("hour").is_between(*OPENING_HOURS))
        .with_columns(revenue=pl.col("quantity") * pl.col("unit_price"))
        .group_by("category")
        .agg(
            orders=pl.len(),
            units=pl.col("quantity").sum(),
            revenue=pl.col("revenue").sum(),
        )
        .sort("revenue", descending=True)
        .collect()
    )


def summary_table(summary):
    """Turn the collected DataFrame into a DataTable, one row per category."""
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
            for row in summary.to_dicts()
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
        """Generate, join and aggregate at the current slider value, then draw the table.

        Runs on a background thread: polars parallelises inside `collect()`, but
        that call still blocks whichever thread makes it, and on the UI thread it
        would freeze the app for the whole pipeline.
        """
        rows = int(slider.value)
        started = time.perf_counter()
        summary = rollup(synthesise(rows))
        elapsed = (time.perf_counter() - started) * 1000.0

        results.controls = [summary_table(summary)]
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
                    ft.Text(
                        f"polars {pl.__version__} — {pl.thread_pool_size()} worker threads",
                        size=12,
                    ),
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
