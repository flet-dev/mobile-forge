"""Write the app's own settings file, then measure the C loader against the pure one."""

import flet as ft
from settings import LOADERS, SNIPPET, parse_report, round_trip, version_line

WEIGHTS = (2, 5, 3, 5)


def table_row(values):
    """One row of a results table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=weight)
            for value, weight in zip(values, WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """Write a settings file of the chosen size and report what reading it costs.

    Two claims get checked on the device rather than quoted: that the C loader is
    worth switching to, and that it is a drop-in — so the table reports whether the
    two emitters agreed on the bytes, not just how fast each one was.
    """

    def show_count():
        """Report the document size the next run will write, as the slider moves."""
        caption.value = f"{int(size.value)} services per settings file"

    def start():
        """Hand a run to a background thread and lock the controls while it works.

        Driven by on_change_end, which fires once on release: the run writes a file,
        so one per pixel of the drag would put several writers on one path. The
        guard is set here rather than inside `work` because this body is
        synchronous, where `run_thread` only schedules — a `disabled` set in the
        worker would not have happened yet when Flet pushes the control states.
        """
        if size.disabled:
            return
        size.disabled = True
        parse.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Run the round trip off the UI thread and put its three results on screen.

        Neither loader releases the GIL, so this thread buys nothing but a handler
        that returns immediately. The try/except is load-bearing: `page.run_thread`
        discards whatever a worker raises, so a mistake here would look like a
        screen that quietly stopped updating. It empties the table too, because
        last run's timings would read as though they described the error.
        """
        try:
            headline, rows, ratio = round_trip(int(size.value))
            summary.value = headline
            results.controls = [
                table_row(("step", "call", "ms", "result")),
                ft.Divider(height=1),
                *(table_row(row) for row in rows),
            ]
            verdict.value = ratio
        except Exception as error:
            summary.value = ""
            results.controls = []
            verdict.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        parse.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def check():
        """Parse whatever is in the editor with each loader and compare verdicts.

        The seeded document has a tab where a space belongs — the one thing the two
        loaders genuinely disagree about — so out of the box this shows one
        rejecting a file the other accepts.
        """
        diagnosis.controls = [
            table_row(("loader", "outcome", "where", "caret")),
            ft.Divider(height=1),
            *(
                table_row((name, *parse_report(editor.value, loader)))
                for name, loader in LOADERS
            ),
        ]

    page.appbar = ft.AppBar(title=ft.Text("PyYAML settings file"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(version_line(page.platform.value), size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=25,
                        max=400,
                        value=100,
                        divisions=15,
                        round=0,
                        label="{value}",
                        on_change=show_count,
                        on_change_end=start,
                    ),
                    summary := ft.Text(),
                    results := ft.Column(spacing=4),
                    verdict := ft.Text(size=11),
                    ft.Divider(),
                    editor := ft.TextField(
                        value=SNIPPET,
                        multiline=True,
                        min_lines=5,
                        max_lines=8,
                        text_size=12,
                        label="edit this and parse it again",
                    ),
                    parse := ft.Button("Parse with both loaders", on_click=check),
                    diagnosis := ft.Column(spacing=4),
                ],
            ),
        )
    )

    show_count()
    check()
    start()


if __name__ == "__main__":
    ft.run(main)
