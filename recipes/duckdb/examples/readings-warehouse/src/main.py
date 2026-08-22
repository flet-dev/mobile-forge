import threading

import flet as ft
from warehouse import (
    QUERIES,
    Cancelled,
    cancel,
    describe_engine,
    ensure_readings,
    export_parquet,
    run_query,
)


def cell(value):
    """Format one result value: counts with separators, measurements to two decimals."""
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def line(*cells):
    """One row of the results table: a wide first column, then a column per value."""
    head, *rest = cells
    return ft.Row(
        controls=[ft.Text(head, expand=3), *(ft.Text(c, expand=2) for c in rest)]
    )


def main(page: ft.Page):
    """Three analytical queries over the stored million rows, plus a Parquet export."""
    busy = threading.Lock()

    def start(worker):
        """Disable the controls, then run `worker` on Flet's thread pool.

        Disabling the buttons is not the guard: `run_thread` submits to a shared pool,
        so a tap already in flight still arrives, and two `execute`s on one connection
        cross each other's results instead of raising. The lock is what makes the
        extra tap a no-op; a `con.cursor()` per thread is the other way.
        """
        if not busy.acquire(blocking=False):
            return

        def guard():
            """Refresh the count, run the worker, and report whatever it raised.

            `page.run_thread` never retrieves the worker's future, so an exception in
            there is discarded silently — a cancelled query above all, which is a
            normal outcome rather than a bug. Counting first builds the table on a
            first launch and after one the user cancelled halfway; clearing the rows
            matters as much as the message, since stale numbers under a fresh error
            read as current.
            """
            try:
                caption.value = f"{ensure_readings():,} readings stored"
                worker()
            except Cancelled:
                results.controls = []
                footer.value = "cancelled"
            except Exception as error:
                results.controls = []
                footer.value = str(error)
            finally:
                picker.disabled = False
                exporter.disabled = False
                stopper.disabled = True
                spinner.visible = False
                busy.release()
                page.update()  # auto-update does not reach background threads

        picker.disabled = True
        exporter.disabled = True
        stopper.disabled = False
        spinner.visible = True
        page.update()
        page.run_thread(guard)

    def query():
        """Lay out the selected query's rows, headers included, and time it took."""
        headers, rows, elapsed = run_query(picker.selected[0])
        results.controls = [
            line(*headers),
            ft.Divider(height=1),
            *(line(*(cell(value) for value in row)) for row in rows),
        ]
        footer.value = f"{len(rows)} rows in {elapsed:.0f} ms"

    def dump():
        """Report the Parquet round trip: what was written, read back and how fast."""
        run = export_parquet()
        footer.value = (
            f"{run['rows']:,} rows to {run['parquet_mb']:.1f} MB of zstd Parquet in "
            f"{run['written_ms']:.0f} ms; read back and averaged "
            f"({run['mean']:.2f} °C) in {run['read_ms']:.0f} ms; "
            f"db file {run['db_mb']:.1f} MB"
        )

    def pick():
        """Run whichever query the segmented button was just switched to."""
        start(query)

    def export():
        """Send the Parquet round trip off the UI thread."""
        start(dump)

    def stop():
        """Abort what is running; the worker then raises Cancelled."""
        cancel()

    body = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(describe_engine(), size=12),
            ft.Row(
                controls=[
                    caption := ft.Text(expand=True),
                    spinner := ft.ProgressRing(width=16, height=16, visible=False),
                ]
            ),
            picker := ft.SegmentedButton(
                segments=[
                    ft.Segment(value=name, label=ft.Text(name)) for name in QUERIES
                ],
                selected=[next(iter(QUERIES))],
                show_selected_icon=False,
                on_change=pick,
            ),
            ft.Row(
                controls=[
                    exporter := ft.Button(
                        "Export Parquet", icon=ft.Icons.SAVE_ALT, on_click=export
                    ),
                    stopper := ft.Button("Cancel", disabled=True, on_click=stop),
                ]
            ),
            results := ft.Column(spacing=4),
            footer := ft.Text(size=11),
        ],
    )

    page.appbar = ft.AppBar(title=ft.Text("duckdb readings"), center_title=True)
    page.add(ft.SafeArea(expand=True, content=body))

    start(query)


if __name__ == "__main__":
    ft.run(main)
