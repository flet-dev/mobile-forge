"""Round-trip a CSV through Arrow's own reader and group it up without Acero."""

import os
import random
import time

import flet as ft
import pyarrow as pa
import pyarrow.compute as pc
from pyarrow import csv

# Flet makes FLET_APP_STORAGE_DATA the working directory on device, so a bare
# "orders.csv" would land here anyway; naming it behaves the same on desktop.
CSV_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.csv")

CITIES = ["Lagos", "Nairobi", "Cairo", "Accra", "Kigali", "Dakar"]


def write_orders(rows):
    """Invent `rows` orders and write them out with Arrow's CSV writer.

    The seed is fixed, so every install produces the same totals and two devices
    can be compared against each other directly.
    """
    rng = random.Random(20260817)
    table = pa.table(
        {
            "city": [rng.choice(CITIES) for _ in range(rows)],
            "amount": [round(rng.uniform(5.0, 500.0), 2) for _ in range(rows)],
        }
    )
    csv.write_csv(table, CSV_PATH)


def roll_up(table):
    """Count, total and average `amount` per city, largest total first.

    `table.group_by(...).aggregate(...)` is the call you would reach for, and it
    raises here: grouped aggregation runs on Acero, which these wheels are not
    built with. The kernels themselves are all present, so the grouping is done
    by hand — `pc.unique` for the distinct keys, then one boolean mask per key
    and the scalar aggregates over the rows it selects. Passing a mask is also
    why the filter is spelled `pc.equal(...)` and not `pc.field("city") == city`:
    an expression would send `Table.filter` through Acero as well.
    """
    rows = []
    for city in pc.unique(table["city"]).to_pylist():
        amounts = table.filter(pc.equal(table["city"], city))["amount"]
        rows.append(
            (city, len(amounts), pc.sum(amounts).as_py(), pc.mean(amounts).as_py())
        )
    return sorted(rows, key=lambda entry: entry[2], reverse=True)


def line(label, *cells):
    """One row of the totals table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    """Show a row-count slider driving the round trip, and the per-city totals.

    The header line is the build describing itself: how many compute functions
    this Arrow registers, and whether it carries the gzip codec — the one
    functional difference between the two mobile platforms.
    """

    def show_rows():
        """Report the row count the next run will write, as the slider moves."""
        caption.value = f"{int(count.value):,} orders per run"

    def start():
        """Hand the round trip to a background thread and show that it is running.

        Driven by the slider's on_change_end, which fires once on release —
        on_change would start a fresh run for every pixel of the drag. The
        slider is disabled until compute() re-enables it, so two runs can never
        be writing the same CSV at the same time.
        """
        count.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Write the CSV, parse it back, group it, and fill in the totals.

        Writing is mostly Python inventing random numbers and is not timed. The
        two figures in the footer are Arrow's own: the native CSV parse, and the
        hand-rolled group-by that stands in for the missing query engine.
        """
        write_orders(int(count.value))

        started = time.perf_counter()
        table = csv.read_csv(CSV_PATH)
        parsed = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        totals = roll_up(table)
        grouped = (time.perf_counter() - started) * 1000.0

        results.controls = [
            line("", "orders", "total", "mean"),
            ft.Divider(height=1),
            *(
                line(city, f"{orders:,}", f"{total:,.0f}", f"{mean:.2f}")
                for city, orders, total, mean in totals
            ),
            ft.Divider(height=1),
            line(
                "all cities",
                f"{table.num_rows:,}",
                f"{pc.sum(table['amount']).as_py():,.0f}",
                "",
            ),
        ]
        footer.value = (
            f"{os.path.getsize(CSV_PATH) / 1e6:.2f} MB of CSV parsed in {parsed:.0f} ms "
            f"into {table.nbytes / 1e6:.2f} MB of Arrow, grouped in {grouped:.0f} ms"
        )
        count.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("pyarrow csv rollup"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"pyarrow {pa.__version__} — {len(pc.list_functions())} compute "
                        f"functions, gzip codec "
                        f"{'yes' if pa.Codec.is_available('gzip') else 'no'}",
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
                    count := ft.Slider(
                        min=10_000,
                        max=100_000,
                        value=50_000,
                        divisions=9,
                        round=0,
                        label="{value}",
                        on_change=show_rows,
                        on_change_end=start,
                    ),
                    results := ft.Column(spacing=4),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_rows()
    start()


if __name__ == "__main__":
    ft.run(main)
