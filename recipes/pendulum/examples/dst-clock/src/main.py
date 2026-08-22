import platform

import flet as ft
from clock import (
    BASE_LABEL,
    INSTANT,
    MAX_DAYS,
    crossing,
    implementations,
    local_lines,
    parse_rows,
    version,
    zone_count,
    zone_rows,
)

ZONE_WEIGHTS = (5, 6, 2)

PARSE_WEIGHTS = (7, 3, 7)


def table_row(values, weights, size=11):
    """One table row: a `Text` per value, sized by weight so columns line up."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Report what this device knows about zones, then prove one day is not 24 hours.

    Nothing here is asserted in prose: the header says which parser ran, the
    first block prints three independent answers for the local zone, the zone
    table checks every conversion against the standard library, and the slider
    turns "adding a day is not adding 24 hours" into two numbers that differ.
    """

    def show_days():
        """Caption the slider's position while the thumb is still moving."""
        caption.value = f"{int(span.value)} days from {BASE_LABEL}"

    def run_crossing():
        """Recompute the crossing for the day count the slider was released on.

        Bound to `on_change_end` rather than `on_change` so one gesture means one
        recomputation. It stays on the UI thread deliberately: the work is a
        handful of date operations, it writes nothing, and a background thread
        would only add the two failure modes `page.run_thread` carries.
        """
        days = int(span.value)
        result = crossing(days)
        show_days()
        elapsed, nominal = result["elapsed"], result["nominal"]
        short = nominal - elapsed
        if short:
            verdict = f"{abs(short):g} h {'short of' if short > 0 else 'over'} nominal"
        else:
            verdict = "the two agree"
        added.value = f".add(days={days}) → {result['calendar']}"
        shifted.value = f"+ timedelta(days={days}) → {result['absolute']}"
        apart = result["apart"]
        elapsed_row.value = (
            f"{elapsed:g} h really elapsed against a nominal {days} × 24 = "
            f"{nominal:g} h — {verdict}; the two results are {apart:g} h apart"
        )

    parser_module, helpers_module = implementations()
    page.appbar = ft.AppBar(title=ft.Text("pendulum DST clock"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"pendulum {version()} · Python {platform.python_version()} · "
                        f"{page.platform.value} · parser {parser_module} · "
                        f"helpers {helpers_module}",
                        size=11,
                        selectable=True,
                    ),
                    ft.Text(
                        f"{zone_count()} named zones resolvable here",
                        size=11,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Divider(),
                    ft.Text("what this device thinks its own zone is", size=11),
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(line, size=11, selectable=True)
                            for line in local_lines()
                        ],
                    ),
                    ft.Divider(),
                    ft.Text(f"{INSTANT} seen from six zones", size=11),
                    ft.Column(
                        spacing=4,
                        controls=[
                            table_row(
                                ("zone", "local time", "vs stdlib"), ZONE_WEIGHTS
                            ),
                            ft.Divider(height=1),
                            *(table_row(row, ZONE_WEIGHTS) for row in zone_rows()),
                        ],
                    ),
                    ft.Divider(),
                    caption := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    span := ft.Slider(
                        value=4,
                        min=1,
                        max=MAX_DAYS,
                        divisions=MAX_DAYS - 1,
                        on_change=show_days,
                        on_change_end=run_crossing,
                    ),
                    added := ft.Text(size=12),
                    shifted := ft.Text(size=12),
                    elapsed_row := ft.Text(size=12),
                    ft.Divider(),
                    ft.Text("pendulum.parse, and what it hands back", size=11),
                    ft.Column(
                        spacing=4,
                        controls=[
                            table_row(("input", "type", "result"), PARSE_WEIGHTS, 10),
                            ft.Divider(height=1),
                            *(
                                table_row(row, PARSE_WEIGHTS, 10)
                                for row in parse_rows()
                            ),
                        ],
                    ),
                ],
            ),
        )
    )

    run_crossing()


if __name__ == "__main__":
    ft.run(main)
