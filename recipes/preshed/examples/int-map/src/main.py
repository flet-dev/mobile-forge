import flet as ft
from vocab import SIZES, VERSION, build, find, word


def mb(count):
    """Format a byte count the way the rest of the app quotes sizes: decimal MB."""
    return f"{count / 1e6:.1f} MB"


def row(label, *cells):
    """One line of the results table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    """Index the same tokens in a PreshMap and in a dict, and price both."""
    state = {"report": None}

    def measure():
        """Lock the controls and hand the indexing run to a background thread."""
        sizes.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Fill both tables at the chosen size and refill the results on screen.

        Wrapped end to end: run_thread swallows an exception, and without the
        finally the size buttons would stay greyed out with no clue why.
        """
        try:
            r = build(int(sizes.selected[0]))
            state["report"] = r
            results.controls = [
                row("", "preshed", "dict"),
                ft.Divider(height=1),
                row(f"{r.entries:,} keys", mb(r.map_bytes), mb(r.dict_bytes)),
                row("one lookup", f"{r.map_ns:.0f} ns", f"{r.dict_ns:.0f} ns"),
                row(
                    f"{r.occurrences:,} increments",
                    f"{r.presh_ms:.0f} ms",
                    f"{r.counter_ms:.0f} ms",
                ),
                ft.Divider(height=1),
                row("cells in the PreshMap", f"{r.capacity:,}"),
                row("64-bit key collisions", f"{r.collisions}"),
            ]
            look()
        except Exception as exc:
            results.controls = [ft.Text(str(exc), color=ft.Colors.ERROR)]
        finally:
            sizes.disabled = False
            spinner.visible = False
            page.update()  # auto-update does not reach background threads

    def look():
        """Hash the typed text and show where that key lands in both tables."""
        report = state["report"]
        if report is None:
            return
        digest, position, count = find(report, field.value)
        entry = (
            f"entry {position:,} of {report.entries:,}"
            if position
            else "not in this index"
        )
        answer.value = (
            f"0x{digest:016x}  ({digest})\n{entry}\n"
            f"counted {count:,} times in the stream"
        )
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("preshed int map"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    ft.Row(
                        controls=[
                            sizes := ft.SegmentedButton(
                                selected=[str(SIZES[0])],
                                allow_empty_selection=False,
                                on_change=measure,
                                segments=[
                                    ft.Segment(
                                        value=str(n), label=ft.Text(f"{n // 1000}k")
                                    )
                                    for n in SIZES
                                ],
                            ),
                            spinner := ft.ProgressRing(
                                width=18, height=18, visible=False
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                    ft.Divider(),
                    field := ft.TextField(
                        label="Hash a word into the index",
                        value=word(7),
                        dense=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_submit=look,
                        on_blur=look,
                    ),
                    answer := ft.Text(size=12, color=ft.Colors.PRIMARY),
                ],
            ),
        )
    )

    measure()


if __name__ == "__main__":
    ft.run(main)
