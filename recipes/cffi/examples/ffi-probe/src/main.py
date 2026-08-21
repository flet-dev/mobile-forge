import flet as ft
from probe import VERSION, calls, compiler_only, sort_in_c, widths


def row(label, value):
    """One line of a table: a label on the left, the value it produced on the right."""
    return ft.Row(
        controls=[
            ft.Text(label, expand=3, size=12),
            ft.Text(str(value), expand=2, size=12, color=ft.Colors.PRIMARY),
        ]
    )


def heading(text):
    """A section title above a table."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def refused(label, reason):
    """A feature that raised, shown with the exception it actually produced."""
    return ft.Column(
        spacing=0,
        controls=[
            ft.Text(label, size=12),
            ft.Text(reason, size=11, color=ft.Colors.ERROR),
        ],
    )


def main(page: ft.Page):
    def sort():
        """Lock the button, raise the spinner, hand the sort to a thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(measure)

    def measure():
        """Run the sort and price what crossing the FFI boundary costs.

        qsort is a single call into C, but the comparator driving it is a Python
        function reached through a libffi closure, once per comparison. The
        per-crossing figure is the number to remember: each one is cheap and
        there are a few hundred thousand of them, which is why a loop that calls
        C that many times belongs in C instead.
        """
        in_c, in_python, crossings, agreed = sort_in_c(int(size.value))
        results.controls = [
            row("qsort with a Python comparator", f"{in_c:.0f} ms"),
            row("sorted() on the same list", f"{in_python:.1f} ms"),
            row("calls back into Python", f"{crossings:,}"),
            row("per crossing", f"{in_c * 1000 / crossings:.2f} µs"),
            row("both orders agree", "yes" if agreed else "no"),
        ]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("FFI probe"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    heading("Called through ffi.dlopen(None)"),
                    *(row(label, value) for label, value in calls()),
                    ft.Divider(),
                    heading("sizeof, as this slice reports it"),
                    *(row(name, f"{width} bytes") for name, width in widths()),
                    ft.Divider(),
                    heading("Sorting in C with a Python comparator"),
                    size := ft.Slider(
                        min=5000,
                        max=50000,
                        value=20000,
                        divisions=9,
                        round=0,
                        label="{value} ints",
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Sort in C", icon=ft.Icons.SORT, on_click=sort
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                    ft.Divider(),
                    heading("Refused without a compiler"),
                    *(refused(label, reason) for label, reason in compiler_only()),
                ],
            ),
        )
    )

    sort()


if __name__ == "__main__":
    ft.run(main)
