import flet as ft
from invoice import FEATURES, VERSIONS, run


def row(label, value):
    """One line of a results table: a label, then the value beside it."""
    return ft.Row(controls=[ft.Text(label, expand=3), ft.Text(value, expand=4)])


def main(page: ft.Page):
    """Show the XSLT-rendered statement, the validation checks and the timings.

    The two header lines are the build describing itself — lxml's version, the
    libxml2 and libxslt it is linked against, and the feature set libxml2 answers
    for at runtime. `iconv` is the one entry of that set which differs between
    the platforms, and the encoding rows at the bottom are the difference in
    practice.
    """

    def show_lines():
        """Report the invoice size the next run will build, as the slider moves."""
        caption.value = f"{int(count.value):,} line items per invoice"

    def start():
        """Hand the run to a background thread and show that it is in flight.

        Driven by the slider's on_change_end, which fires once on release;
        on_change would start a fresh run for every pixel of the drag.
        """
        count.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Run one pass, then hand the slider back whatever happened.

        page.run_thread discards anything the worker raises, so an unguarded
        failure would leave the slider disabled and the spinner turning with
        nothing on screen to say why. Several of the libxml2 pieces this app
        touches are present on a desktop build and absent on a device one, so the
        message is worth putting where it can be read — and the previous run's
        statement is worth clearing, since numbers left under a fresh error read
        as current.
        """
        try:
            result = run(int(count.value))
            report.controls = [row(*pair) for pair in result.statement]
            checks.controls = [
                *(row(*pair) for pair in result.checks),
                ft.Divider(height=1),
                *(row(*pair) for pair in result.encodings),
            ]
            footer.value = result.timings
        except Exception as error:
            report.controls = []
            checks.controls = []
            footer.value = f"{type(error).__name__}: {error}"
        count.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("lxml invoice xslt"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSIONS, size=12),
                    ft.Text(FEATURES, size=12),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    count := ft.Slider(
                        min=25,
                        max=250,
                        value=100,
                        divisions=9,
                        round=0,
                        label="{value}",
                        on_change=show_lines,
                        on_change_end=start,
                    ),
                    report := ft.Column(spacing=4),
                    ft.Divider(height=1),
                    checks := ft.Column(spacing=4),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_lines()
    start()


if __name__ == "__main__":
    ft.run(main)
