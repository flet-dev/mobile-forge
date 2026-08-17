"""Read a CSV of orders from app storage, group it with pandas and show the totals."""

import os
import random
from datetime import date, timedelta

import flet as ft
import pandas as pd

# FLET_APP_STORAGE_DATA is durable, app-private storage. Flet also makes it the working
# directory on device, so a bare "orders.csv" would land there too — this spells it out.
CSV_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.csv")

ROWS = 600
REGIONS = ["North", "South", "East", "West"]
PRODUCTS = ["Anvil", "Rocket", "Magnet", "Rope", "Paint"]
KEYS = {"region": "Region", "product": "Product", "month": "Month"}


def write_sample_csv():
    """Write the app's own CSV on first launch, so nothing has to be bundled or fetched."""
    rng = random.Random(20260816)  # seeded, so every install shows the same totals
    start = date(2026, 1, 1)
    pd.DataFrame(
        [
            {
                "date": start + timedelta(days=rng.randrange(180)),
                "region": rng.choice(REGIONS),
                "product": rng.choice(PRODUCTS),
                "units": rng.randrange(1, 25),
                "unit_price": round(rng.uniform(4.0, 90.0), 2),
            }
            for _ in range(ROWS)
        ]
    ).to_csv(CSV_PATH, index=False)


def load_orders():
    """Read the CSV into a frame and derive the two columns the summaries need.

    Writes the sample file first when it is missing, so a fresh install has something to
    show and every launch after that is a plain read of a file the app owns.
    """
    if not os.path.exists(CSV_PATH):
        write_sample_csv()
    orders = pd.read_csv(CSV_PATH, parse_dates=["date"])
    orders["revenue"] = orders["units"] * orders["unit_price"]
    # strftime rather than a tz conversion: named IANA zones need the tzdata package,
    # which this app does not depend on.
    orders["month"] = orders["date"].dt.strftime("%Y-%m")
    return orders


def summarise(orders, key):
    """Group the orders by one column into counts, units and revenue, biggest first.

    The three differently-aggregated columns come from a single named aggregation rather
    than three passes, and the index is reset so the group label arrives as an ordinary
    column that the table code can read like any other.
    """
    summary = orders.groupby(key).agg(
        orders=("units", "size"),
        units=("units", "sum"),
        revenue=("revenue", "sum"),
    )
    return summary.sort_values("revenue", ascending=False).reset_index()


def main(page: ft.Page):
    """Show the totals for the chosen grouping, with the CSV's full path at the foot.

    The frame is read once and kept in a closure variable, so switching between Region,
    Product and Month re-groups what is already in memory instead of re-reading the file.
    """
    orders = None

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
        """Group the frame and rebuild the table, on the thread refresh started.

        The CSV is read on the first call only, which is why the read lives here rather
        than at import time: a slow first read must not hold up the first frame. The
        header line reports which string backend pandas picked — `python`, or `pyarrow`
        if that optional package is installed.
        """
        nonlocal orders
        if orders is None:
            orders = load_orders()

        key = choice.selected[0]
        summary = summarise(orders, key)

        header.value = (
            f"pandas {pd.__version__} — {len(orders)} rows, "
            f"text columns stored as {orders[key].dtype.storage}"
        )
        results.controls = [
            ft.DataTable(
                column_spacing=16,
                columns=[
                    ft.DataColumn(ft.Text(KEYS[key])),
                    ft.DataColumn(ft.Text("Orders"), numeric=True),
                    ft.DataColumn(ft.Text("Units"), numeric=True),
                    ft.DataColumn(ft.Text("Revenue"), numeric=True),
                ],
                rows=[
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(row[key])),
                            ft.DataCell(ft.Text(f"{row['orders']}")),
                            ft.DataCell(ft.Text(f"{row['units']}")),
                            ft.DataCell(ft.Text(f"{row['revenue']:,.0f}")),
                        ]
                    )
                    for row in summary.to_dict("records")
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
                expand=True,
                controls=[
                    header := ft.Text(size=12),
                    ft.Row(
                        controls=[
                            choice := ft.SegmentedButton(
                                segments=[
                                    ft.Segment(value=column, label=ft.Text(label))
                                    for column, label in KEYS.items()
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
                    results := ft.Column(expand=True, scroll=ft.ScrollMode.AUTO),
                    ft.Text(CSV_PATH, size=10, selectable=True),
                ],
            ),
        )
    )

    refresh()


if __name__ == "__main__":
    ft.run(main)
