import flet as ft
from markup import AVAILABLE, ENGINES, PRESETS, absent_report, analyse, versions


def main(page: ft.Page):
    """Parse the bundled page on every engine or selector change, off the UI thread.

    The first pass goes through `page.run_thread` as well, so the layout reaches
    the client before any parsing starts rather than after it.
    """

    def line(label, value):
        """One label/value row, sized so neither column can overflow a phone."""
        return ft.Row(
            controls=[
                ft.Text(label, size=11, expand=2, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(value, size=11, expand=5, selectable=True),
            ]
        )

    def heading(text):
        """A section title inside the scrolling column."""
        return ft.Text(text, size=12, weight=ft.FontWeight.BOLD)

    def refresh(engine, selector):
        """Run one pass and move every control that depends on it."""
        found = analyse(engine, selector)
        header.value = versions(engine, page.platform.value)
        matched.controls = [line(*pair) for pair in found["matches"]]
        scraped.controls = [line(*pair) for pair in found["records"]]
        repaired.controls = [line(*pair) for pair in found["repairs"]]
        compared.controls = [line(*pair) for pair in found["comparison"]]

    def busy(state):
        """Lock or release every control that can start a pass.

        All three, not just the engine button: `run_thread` submits to a shared
        pool, so a second tap during a pass would genuinely run beside the first
        and write these same controls — and a pass lasts about as long as its
        two timed benchmarks, wide enough to hit by tapping two chips in a row.
        """
        engines.disabled = chips.disabled = field.disabled = state

    def worker(engine, selector):
        """One pass off the event loop thread.

        `page.run_thread` never retrieves the worker's future, so an exception
        raised here would vanish without a log or a crash — hence the except.
        Auto-update does not reach a background thread either, so the explicit
        `page.update()` is what redraws the screen.
        """
        try:
            refresh(engine, selector)
        except Exception as error:
            matched.controls = [line("failed", f"{type(error).__name__}: {error}")]
        finally:
            busy(False)
            page.update()

    def rebuild():
        """Start a pass on the current engine and selector, unless one is running.

        `busy` only greys the controls once its patch reaches the client a frame
        later, so the guard is what actually stops a fast double tap.
        """
        if engines.disabled:
            return
        busy(True)
        page.run_thread(worker, engines.selected[0], field.value.strip() or "li.post")

    def preset(value):
        """Put a preset selector in the field and run it."""

        def apply():
            """The chip's handler; `value` is bound per chip rather than by the loop."""
            field.value = value
            rebuild()

        return apply

    page.appbar = ft.AppBar(title=ft.Text("selectolax page scrape"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    header := ft.Text(size=11),
                    note := ft.Text(size=11, visible=False),
                    engines := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name))
                            for name in ENGINES
                        ],
                        selected=[ENGINES[0]],
                        on_change=rebuild,
                    ),
                    field := ft.TextField(
                        label="CSS selector",
                        value=PRESETS[0],
                        dense=True,
                        text_size=12,
                        autocorrect=False,
                        capitalization=ft.TextCapitalization.NONE,
                        prefix_icon=ft.Icons.SEARCH,
                        on_submit=rebuild,
                    ),
                    chips := ft.Row(
                        scroll=ft.ScrollMode.AUTO,
                        controls=[
                            ft.Chip(label=ft.Text(css, size=10), on_click=preset(css))
                            for css in PRESETS
                        ],
                    ),
                    matched := ft.Column(spacing=2),
                    ft.Divider(height=12),
                    heading("scraped from the page"),
                    scraped := ft.Column(spacing=2),
                    ft.Divider(height=12),
                    heading("what the parser repaired"),
                    repaired := ft.Column(spacing=2),
                    ft.Divider(height=12),
                    heading("against html.parser"),
                    compared := ft.Column(spacing=2),
                ],
            ),
        )
    )

    if not AVAILABLE:
        header.value, note.value, summary = absent_report()
        note.visible = True
        busy(True)
        matched.controls = [line(*pair) for pair in summary]
        return

    rebuild()


if __name__ == "__main__":
    ft.run(main)
