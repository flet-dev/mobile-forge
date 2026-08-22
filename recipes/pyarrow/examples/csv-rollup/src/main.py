import flet as ft
from orders import BUILD, round_trip


def line(label, *cells):
    """One row of the totals table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    """Show a row-count slider driving the round trip, and the per-city totals."""

    def show_rows():
        """Report the row count the next run will write, as the slider moves."""
        caption.value = f"{int(count.value):,} orders per run"

    def start():
        """Hand the round trip to a background thread and show that it is running.

        Driven by the slider's on_change_end, which fires once on release —
        on_change would start a fresh run for every pixel of the drag. The slider
        is disabled until compute() re-enables it, so two runs can never be writing
        the same CSV at the same time.
        """
        count.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Run the round trip off the UI thread and fill in the totals and footer."""
        result = round_trip(int(count.value))
        results.controls = [
            line("", "orders", "total", "mean"),
            ft.Divider(height=1),
            *(
                line(city, f"{orders:,}", f"{total:,.0f}", f"{mean:.2f}")
                for city, orders, total, mean in result["totals"]
            ),
            ft.Divider(height=1),
            line("all cities", f"{result['rows']:,}", f"{result['total']:,.0f}", ""),
        ]
        footer.value = (
            f"{result['csv_mb']:.2f} MB of CSV parsed in {result['parse_ms']:.0f} ms "
            f"into {result['arrow_mb']:.2f} MB of Arrow, "
            f"grouped in {result['group_ms']:.0f} ms"
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
                    ft.Text(BUILD, size=12),
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
