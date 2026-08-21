import flet as ft
from serializers import (
    COUNTS,
    HEADLINE,
    bench,
    gc_after_bad_read,
    make_records,
    store,
    two_msgpacks,
    vendored,
)


def row(label, *cells):
    """One line of a table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=4, size=12)]
        + [ft.Text(cell, expand=3, size=12) for cell in cells]
    )


def heading(text):
    """A section title for one of the static panels below the results."""
    return ft.Text(text, size=12, weight=ft.FontWeight.BOLD)


def main(page: ft.Page):
    """Build the page and run the round trips once, before anything is touched.

    The three panels below the results are static: which module each format
    actually resolves to, and what the two msgpack implementations in this
    process do with the same values. They are read once at build time because
    none of it can change while the app is running.
    """

    def run():
        """Lock the picker and hand the round trips to a background thread."""
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Time every format at the chosen record count and fill both tables.

        YAML is the reason this cannot run on the UI thread: ruamel.yaml is pure
        Python and takes hundreds of times longer than the compiled formats for
        the same records. The body is wrapped so that a raise cannot leave the
        picker disabled and the spinner turning -- page.run_thread swallows the
        exception, and nothing else would ever re-enable the controls.
        """
        try:
            records = make_records(int(picker.selected[0]))
            results.controls = [
                row("", "bytes", "dump", "load", "same"),
                ft.Divider(height=1),
                *(
                    row(
                        label,
                        f"{size / 1000:.1f} kB",
                        f"{encoded:.1f} ms",
                        f"{decoded:.1f} ms",
                        "yes" if exact else "no",
                    )
                    for label, size, encoded, decoded, exact in bench(records)
                ),
            ]
            files.controls = [
                row(name, f"{size / 1000:.1f} kB", f"{count} read")
                for name, size, count in store(records)
            ]
        except Exception as error:
            results.controls = [ft.Text(f"{type(error).__name__}: {error}", size=12)]
        finally:
            picker.disabled = False
            spinner.visible = False
            page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Serial toolbox"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(HEADLINE, size=11),
                    picker := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=count, label=ft.Text(count))
                            for count in COUNTS
                        ],
                        # selected is a list in Flet 0.86, not a set.
                        selected=[COUNTS[0]],
                        show_selected_icon=False,
                        on_change=run,
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(
                                "records, through each format", size=11, expand=True
                            ),
                            spinner := ft.ProgressRing(
                                width=14, height=14, visible=False
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                    row(
                        "gc on after a bad msgpack read",
                        "yes" if gc_after_bad_read() else "no",
                    ),
                    ft.Divider(),
                    heading("Same records through the file API"),
                    files := ft.Column(spacing=4),
                    ft.Divider(),
                    heading("Vendored inside srsly"),
                    *(row(*entry) for entry in vendored()),
                    ft.Divider(),
                    heading("Two msgpacks in this process"),
                    *(row(*entry) for entry in two_msgpacks()),
                ],
            ),
        )
    )

    run()


if __name__ == "__main__":
    ft.run(main)
