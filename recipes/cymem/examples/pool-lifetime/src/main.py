import flet as ft
from lifetime import BLOCKS, LABEL, bookkeeping, compare


def row(label, *cells):
    """One line of the comparison table: a label, then a column per strategy."""
    return ft.Row(
        controls=[ft.Text(label, expand=5), *(ft.Text(c, expand=3) for c in cells)]
    )


def mb(value):
    """Format a byte count in decimal MB, the unit package indexes quote."""
    return f"{value / 1e6:.2f} MB"


def us(value):
    """Format microseconds. One unit spans every block size the slider offers."""
    return f"{value:,.0f} us"


def main(page: ft.Page):
    """Measure a cymem Pool against a list of bytearrays and show when each frees."""

    def measure(e=None):
        """Lock the controls, raise the spinner, hand the measurement to a thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Fill the table from one measurement run at the selected size.

        Wrapped in try/finally because page.run_thread swallows exceptions: without
        it, a failure would leave the button disabled and the spinner turning.
        """
        try:
            count = int(counts.value)
            name = sizes.selected[0]
            rows = compare(count, BLOCKS[name])
            books = bookkeeping(count, BLOCKS[name])
            headline.value = f"{count:,} x {name} = {mb(count * BLOCKS[name])}"
            results.controls = [
                row("", "Pool", "bytearray"),
                ft.Divider(height=1),
                row("allocate", *(us(r["alloc_us"]) for r in rows)),
                row("release", *(us(r["free_us"]) for r in rows)),
                ft.Divider(height=1),
                row("held after allocating", *(mb(r["held"]) for r in rows)),
                row("after dropping half", *(mb(r["half"]) for r in rows)),
                row("after dropping it all", *(mb(r["empty"]) for r in rows)),
                ft.Divider(height=1),
                row("per-block overhead", *(f"{r['per_block']:.0f} B" for r in rows)),
            ]
            reported.value = (
                f"the pool reports size {books['size']} B and "
                f"{books['addresses']} addresses for {books['refs']:,} refs"
            )
        except Exception as exc:
            results.controls = [ft.Text(str(exc), color=ft.Colors.ERROR)]
        finally:
            button.disabled = False
            spinner.visible = False
            page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("cymem pool lifetime"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(LABEL, size=12),
                    headline := ft.Text(size=16, weight=ft.FontWeight.BOLD),
                    sizes := ft.SegmentedButton(
                        # Flet 0.86 takes a list here, not a set.
                        selected=["512 B"],
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name))
                            for name in BLOCKS
                        ],
                        on_change=measure,
                    ),
                    ft.Text("Blocks allocated", size=12),
                    counts := ft.Slider(
                        min=1000,
                        max=10000,
                        value=5000,
                        divisions=9,
                        round=0,
                        label="{value} blocks",
                        # on_change would re-run the whole timed pass per pixel the
                        # thumb travels; on_change_end runs it once, on release.
                        on_change_end=measure,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Measure again",
                                icon=ft.Icons.MEMORY,
                                on_click=measure,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                    reported := ft.Text(size=12, italic=True),
                ],
            ),
        )
    )

    measure()


if __name__ == "__main__":
    ft.run(main)
