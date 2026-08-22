"""Validate a JSON order feed and refuse the records that do not fit the schema."""

import textwrap
import time

import flet as ft
from feed import (
    build_line,
    deepest_nesting,
    make_feed,
    rollup,
    round_trip,
    validate_feed,
)

TOTAL_COLUMNS = (2, 2, 2, 3)
REJECTION_COLUMNS = (3, 3, 6, 3)


def table(header, rows, weights):
    """A header line, a rule, then one line per row, sized by relative width.

    `weights` are `expand` values, one per column, so a phone-width table keeps
    its columns aligned without any fixed pixel sizes.
    """

    def line(values):
        """One line of the table: a `Text` per value at its column's weight."""
        return ft.Row(
            controls=[
                ft.Text(value, size=11, expand=weight)
                for value, weight in zip(values, weights)
            ]
        )

    return [line(header), ft.Divider(height=1), *(line(values) for values in rows)]


def main(page: ft.Page):
    """Show a feed size driving a validation run, and what each run made of it.

    Everything on screen is computed from the one `validate_json` call in
    `feed.validate_feed` and the `ValidationError` it raises: the survivor
    count, the `Decimal` revenue per currency, and a rejection table built out
    of `errors(include_url=False)`.
    """

    def show_count():
        """Report the feed size the next run will validate, as the slider moves."""
        caption.value = f"{int(size.value):,} records per feed"

    def start():
        """Hand a run to a background thread and show that one is in flight.

        Driven by the slider's on_change_end, which fires once on release —
        on_change would start a fresh run for every pixel of the drag.
        """
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Generate a feed, validate it, and fill the screen in from the result.

        Validation holds the GIL from start to finish, so this thread buys
        responsiveness only in the sense that the event handler returns
        immediately. The try/except is not decoration: `page.run_thread`
        discards whatever a worker raises, so without it a mistake in here would
        show up as a screen that quietly stopped updating.
        """
        try:
            payload = make_feed(int(size.value))

            started = time.perf_counter()
            orders, problems, rejected = validate_feed(payload)
            elapsed = (time.perf_counter() - started) * 1000.0

            summary.value = (
                f"{len(orders):,} valid, {len(rejected)} records rejected over "
                f"{len(problems)} errors — {len(payload) / 1000:.0f} KB validated "
                f"and salvaged in {elapsed:.0f} ms"
            )
            totals.controls = table(
                ("currency", "orders", "lines", "revenue"),
                [
                    (currency, f"{count:,}", f"{lines:,}", f"{revenue:,.2f}")
                    for currency, (count, lines, revenue) in rollup(orders)
                ],
                TOTAL_COLUMNS,
            )
            rejections.controls = table(
                ("where", "error", "message", "input"),
                [
                    (
                        ".".join(str(part) for part in problem["loc"]),
                        problem["type"],
                        problem["msg"],
                        textwrap.shorten(repr(problem["input"]), 32, placeholder="…"),
                    )
                    for problem in problems
                ],
                REJECTION_COLUMNS,
            )

            written, through_rust, through_stdlib = round_trip(orders)
            footer.value = (
                f"survivors re-serialised to {written / 1000:.0f} KB, then read back: "
                f"validate_json {through_rust:.1f} ms against json.loads + "
                f"validate_python {through_stdlib:.1f} ms — deepest JSON nesting "
                f"accepted on this device: {deepest_nesting()}"
            )
        except Exception as error:
            footer.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("pydantic feed validator"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(build_line(), size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=200,
                        max=2000,
                        value=500,
                        divisions=9,
                        round=0,
                        label="{value}",
                        on_change=show_count,
                        on_change_end=start,
                    ),
                    summary := ft.Text(),
                    totals := ft.Column(spacing=4),
                    rejections := ft.Column(spacing=4),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_count()
    start()


if __name__ == "__main__":
    ft.run(main)
