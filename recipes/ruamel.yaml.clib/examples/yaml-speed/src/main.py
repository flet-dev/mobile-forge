import flet as ft
from yamlbench import RECORD_COUNTS, backend, comment_demo, measure, report

# "monospace" is a generic family that Android maps and iOS does not, and the
# timing columns only line up in a real fixed-width face; Courier backs it up.
MONO = {"font_family": "monospace", "font_family_fallback": ["Courier"]}


def heading(text):
    """The title of one of the panels."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def panel(caption, body):
    """A captioned, boxed block of YAML text."""
    return ft.Column(
        spacing=4,
        controls=[
            ft.Text(caption, size=11, color=ft.Colors.PRIMARY),
            ft.Container(
                padding=8,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                content=ft.Text(body.rstrip(), size=10, **MONO),
            ),
        ],
    )


def main(page: ft.Page):
    """Show which parser is live, time both of them, and price the difference.

    The banner is the part worth copying into a real app: nothing else on screen
    would look any different if the compiled parser had failed to ship.
    """
    info = backend()
    demo = comment_demo()
    state = {"records": RECORD_COUNTS[1]}

    def start(e=None):
        """Raise the spinner and hand the timing run to a worker thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Time both parsers on the chosen document and fill in the table.

        page.run_thread swallows exceptions, so the worker catches its own and
        shows them, and it ends with an explicit page.update() because
        auto-update does not reach a background thread.
        """
        try:
            table.value, note.value = report(measure(state["records"]))
            note.color = None
        except Exception as exc:
            note.value = str(exc)
            note.color = ft.Colors.ERROR
        button.disabled = False
        spinner.visible = False
        page.update()

    def pick(e):
        """Adopt the document size chosen in the segmented button and re-run."""
        state["records"] = int(e.control.selected[0])
        start()

    page.appbar = ft.AppBar(title=ft.Text("YAML speed"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        info["label"],
                        size=12,
                        color=(
                            ft.Colors.PRIMARY
                            if info["accelerated"]
                            else ft.Colors.ERROR
                        ),
                    ),
                    heading("The same document, both parsers"),
                    ft.Text("host records", size=11, color=ft.Colors.OUTLINE),
                    ft.SegmentedButton(
                        selected=[str(state["records"])],
                        on_change=pick,
                        segments=[
                            ft.Segment(value=str(count), label=ft.Text(str(count)))
                            for count in RECORD_COUNTS
                        ],
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Measure", icon=ft.Icons.SPEED, on_click=start
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    table := ft.Text(size=12, **MONO),
                    note := ft.Text(size=11),
                    ft.Divider(height=20),
                    heading("What the compiled path throws away"),
                    panel("on disk", demo["source"]),
                    panel("re-emitted by YAML()", demo["round_trip"]),
                    panel('re-emitted by YAML(typ="safe")', demo["safe"]),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
