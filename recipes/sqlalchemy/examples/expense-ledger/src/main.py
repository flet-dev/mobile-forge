"""An expense ledger the SQLAlchemy ORM keeps in a SQLite file in app storage."""

import decimal
import threading

import flet as ft
from ledger import (
    DEFAULT_ROWS,
    capabilities,
    compare,
    largest,
    reseed,
    rollup,
    storage_line,
)

WEIGHTS = (3, 2, 3, 2)


def cell(value):
    """Format one aggregate value: counts with separators, money at two decimals."""
    if isinstance(value, decimal.Decimal):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def line(*values):
    """One row of the rollup table, weighted so four columns fit a phone width."""
    return ft.Row(
        controls=[
            ft.Text(cell(value), size=11, expand=weight)
            for value, weight in zip(values, WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """A slider that reseeds the ledger, and the per-category rollup of what it wrote.

    Reseeding writes a file, so it runs on Flet's thread pool rather than the UI thread.
    The engine's default QueuePool is what makes that legal: for a file database
    SQLAlchemy passes `check_same_thread=False`, then checks each sqlite3 connection out
    to one thread at a time.
    """
    busy = threading.Lock()

    def render(rows, totals, note):
        """Show the rollup with the ungrouped totals underneath, then the three lines."""
        results.controls = [
            line("Category", "Expenses", "Total", "Average"),
            ft.Divider(height=1),
            *(line(*row) for row in rows),
            ft.Divider(height=1),
            line("All", *totals),
        ]
        storage.value = storage_line()
        detail.value = largest()
        footer.value = note

    def start(worker):
        """Disable the controls and hand `worker` to Flet's thread pool.

        Disabling them is not enough on its own: `run_thread` submits to a shared pool,
        so a tap already in flight still arrives, and with `pool_size=1` a second worker
        would sit on the connection pool for its 30 s timeout. The non-blocking lock is
        what makes the extra tap a no-op.
        """
        if not busy.acquire(blocking=False):
            return

        def guard():
            """Run the worker and report whatever it raised.

            Load-bearing: `page.run_thread` never retrieves the worker's future, so an
            exception there is discarded with no crash and no log line — the screen
            simply stops changing. The table is cleared alongside the message, because
            numbers from the previous run left under a fresh error read as current.
            """
            try:
                worker()
            except Exception as error:
                results.controls = []
                detail.value = ""
                footer.value = str(error)
            finally:
                slider.disabled = False
                comparer.disabled = False
                spinner.visible = False
                busy.release()
                page.update()  # auto-update does not reach background threads

        slider.disabled = True
        comparer.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(guard)

    def rewrite():
        """Rewrite the ledger at the slider's size, then show what it wrote."""
        render(*reseed(int(slider.value)))

    def refresh():
        """Roll up whatever is already stored, seeding first if the ledger is empty."""
        rows, totals = rollup()
        if not rows:
            rewrite()
            return
        render(rows, totals, f"{totals[0]:,} expenses already stored")

    def timings():
        """Put the ORM-versus-Core comparison in the footer."""
        footer.value = compare()

    def resize():
        """Update the caption only — on_change fires continuously while dragging."""
        caption.value = f"{int(slider.value):,} expenses"

    page.appbar = ft.AppBar(title=ft.Text("sqlalchemy ledger"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(capabilities(), size=11),
                    storage := ft.Text(size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(f"{DEFAULT_ROWS:,} expenses", expand=True),
                            spinner := ft.ProgressRing(width=16, height=16, visible=False),
                        ]
                    ),
                    slider := ft.Slider(
                        min=1000,
                        max=20000,
                        divisions=19,
                        value=DEFAULT_ROWS,
                        label="{value}",
                        on_change=resize,
                        on_change_end=lambda: start(rewrite),
                    ),
                    comparer := ft.Button(
                        "Compare ORM vs Core",
                        icon=ft.Icons.SPEED,
                        on_click=lambda: start(timings),
                    ),
                    results := ft.Column(spacing=2),
                    detail := ft.Text(size=11),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    start(refresh)


if __name__ == "__main__":
    ft.run(main)
