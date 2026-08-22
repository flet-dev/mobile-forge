"""Fuzzy search over 4,000 in-app strings, with every number on screen checked a second way."""

import flet as ft
from search import (
    CASE_NOTE,
    CORPUS_SIZE,
    DEFAULT_QUERY,
    DEFAULT_SCORER,
    SCORER_NAMES,
    TABLE_NOTE,
    describe,
    native_origin,
    search,
)

COLUMNS = ("scorer", "top match", "score", "no processor")


def main(page: ft.Page):
    """A search box over a fixed corpus, with the header read off the device.

    Everything rapidfuzz does lives in search.py; this file is the controls, the
    thread plumbing and the failure handling.
    """

    def clear():
        """Blank every computed row, so a failure cannot leave the last answer under it."""
        results.controls = []
        table.rows = []
        for row in (caption, cross, speed):
            row.value = ""

    def render(answer):
        """Put one search's results on screen. Runs in the thread pool, not on the UI thread."""
        caption.value = answer.caption
        results.controls = [
            ft.Text(f"{rank}. {match}   {score:.1f}", size=13)
            for rank, (match, score) in enumerate(answer.ranked, 1)
        ]
        table.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(cell, size=12))
                    for cell in (name, match, f"{score:.1f}", f"{raw:.1f}")
                ]
            )
            for name, match, score, raw in answer.table
        ]
        cross.value = answer.cdist_note
        speed.value = answer.speed_note

    def work():
        """Run one search, then hand the inputs back whatever happened.

        page.run_thread never retrieves the worker's future, so anything raised here
        would vanish without a log; the blanket except puts the message in the field
        instead. rapidfuzz signals bad input with plain builtin TypeErrors rather
        than a class of its own, and an unhandled exception in a Flet handler
        produces a crash screen.
        """
        query = (field.value or "").strip()
        try:
            if query:
                field.error = None
                render(search(query, picker.value))
            else:
                clear()
                field.error = "type something to search for"
        except Exception as error:
            clear()
            field.error = f"{type(error).__name__}: {error}"
        finally:
            field.disabled = False
            picker.disabled = False
            page.update()  # auto-update does not reach background threads

    def start():
        """Send one search off the UI thread, for the field's Enter or a new scorer.

        The guard reads `disabled` back rather than trusting it to have taken effect:
        disabling only queues the new state for the client, and page.run_thread
        submits to a shared pool, so a second gesture inside that window would put
        two workers on the same rows.
        """
        if field.disabled:
            return
        field.disabled = True
        picker.disabled = True
        page.update()
        page.run_thread(work)

    page.appbar = ft.AppBar(title=ft.Text("rapidfuzz fuzzy search"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"{describe()} · {page.platform.value}", size=11, selectable=True
                    ),
                    ft.Text(f"loaded from {native_origin()}", size=11, selectable=True),
                    field := ft.TextField(
                        label=f"Search {CORPUS_SIZE:,} place names",
                        value=DEFAULT_QUERY,
                        on_submit=start,
                    ),
                    picker := ft.Dropdown(
                        label="Ranking scorer",
                        value=DEFAULT_SCORER,
                        options=[ft.DropdownOption(key=name) for name in SCORER_NAMES],
                        on_select=start,
                    ),
                    caption := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    results := ft.Column(spacing=2),
                    ft.Text(TABLE_NOTE, size=11),
                    # A DataTable this wide overflows a phone; a non-scrolling Row
                    # around it would paint Flutter's OVERFLOWED stripes instead.
                    ft.Row(
                        scroll=ft.ScrollMode.AUTO,
                        controls=[
                            table := ft.DataTable(
                                columns=[
                                    ft.DataColumn(ft.Text(head)) for head in COLUMNS
                                ],
                                column_spacing=18,
                            )
                        ],
                    ),
                    cross := ft.Text(size=12),
                    speed := ft.Text(size=12),
                    ft.Text(CASE_NOTE, size=12),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
