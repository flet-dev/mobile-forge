import flet as ft
from escaping import VERSION, bench, renderings, replacements

SAMPLE = "<script>steal()</script> Tom & 'Jerry' say \"hi\""


def code(text, **kwargs):
    """Monospace text: every fragment on screen is shown as literal source."""
    return ft.Text(
        text,
        size=11,
        font_family="monospace",
        font_family_fallback=["Courier"],
        selectable=True,
        **kwargs,
    )


def panel(title, source, html, smuggled):
    """One rendering: how it was built, what came out, and what got in.

    The border and the count are the verdict. `smuggled` is elements the input
    contributed, so zero means the input landed as text and anything else means
    it landed as markup.
    """
    tone = ft.Colors.ERROR if smuggled else ft.Colors.PRIMARY
    plural = "" if smuggled == 1 else "s"
    note = "text only" if not smuggled else f"{smuggled} live tag{plural} from input"
    return ft.Container(
        padding=10,
        border_radius=8,
        border=ft.Border.all(1, tone),
        content=ft.Column(
            spacing=4,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(title, size=12, weight=ft.FontWeight.BOLD),
                        ft.Text(note, size=11, color=tone),
                    ],
                ),
                code(source, color=ft.Colors.ON_SURFACE_VARIANT),
                code(html),
            ],
        ),
    )


def main(page: ft.Page):
    """Build one comment four ways from the same input, and time both engines."""

    def show():
        """Rebuild the four fragments for whatever is in the field."""
        panels.controls = [panel(*row) for row in renderings(field.value)]
        page.update()

    def measure():
        """Lock the button and hand the timing loop to a background thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(timed)

    def timed():
        """Time the engines on the current value and report microseconds per call.

        The ratio is printed as a bare multiple, not as "x faster": paste a long
        value with one `&` in it and the C accelerator comes out below 1.
        """
        rows, speedup = bench(field.value)
        lines = [f"{label:24s}{micros:7.3f} us/call" for label, micros in rows]
        if speedup:
            lines.append(f"{'C vs pure-Python':24s}{speedup:7.2f}x")
        timing.value = "\n".join(lines)
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Escape inspector"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=11),
                    field := ft.TextField(
                        label="Untrusted input",
                        value=SAMPLE,
                        dense=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_change=show,
                    ),
                    panels := ft.Column(spacing=8),
                    ft.Divider(),
                    ft.Text(
                        "escape() rewrites five characters, and no others", size=12
                    ),
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Row(controls=[code(c, expand=1), code(e, expand=4)])
                            for c, e in replacements()
                        ],
                    ),
                    ft.Divider(),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Time the engines",
                                icon=ft.Icons.SPEED,
                                on_click=measure,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    timing := code(""),
                ],
            ),
        )
    )

    show()


if __name__ == "__main__":
    ft.run(main)
