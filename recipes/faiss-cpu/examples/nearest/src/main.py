import flet as ft
from search import (
    BUILD_OPTIONS,
    DEFAULT,
    SETTINGS,
    SUMMARY,
    TOLERANCE,
    VERSIONS,
    K,
    N,
    build,
    rank,
)

COLUMNS = (7, 4, 3, 7)


def table_row(cells, weight=None):
    """One line of the table, sized by expand weights so it can never overflow.

    A non-scrolling Row wider than a phone screen draws Flutter's striped overflow
    marker; weights make the four columns share whatever width there is.
    """
    return ft.Row(
        controls=[
            ft.Text(cell, size=12, weight=weight, expand=span)
            for cell, span in zip(cells, COLUMNS)
        ]
    )


def main(page: ft.Page):
    """Three indexes over one set of vectors, each graded against the exact answer.

    The header line makes the build describe itself: the SIMD level reported by
    get_compile_options() and the OpenMP thread count both differ by platform, and
    reading them off the screen beats reading them off any documentation.
    """
    state = None

    def work(job, message):
        """Run `job` in the thread pool with the slider disabled and the spinner up.

        `page.run_thread` never retrieves the worker's future, so an exception raised
        inside one would vanish without a crash, a log line or a trace — hence the
        catch. The closing `page.update()` is equally mandatory: auto-update does not
        reach background threads.
        """

        def runner():
            """The worker body: run the job, then release the controls either way."""
            try:
                job()
            except Exception as error:
                status.value = f"{type(error).__name__}: {error}"
            effort.disabled = False
            spinner.visible = False
            page.update()

        status.value = message
        effort.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(runner)

    def prepare():
        """Build the three indexes, report the numpy cross-check, then draw the table."""
        nonlocal state
        state = build()
        check.value = (
            f"{'PASS' if state['passed'] else 'FAIL'} · Flat vs numpy — recall@{K} "
            f"{state['recall']:.4f}, largest distance disagreement "
            f"{state['agreement']:.1e} against a {TOLERANCE:.0e} tolerance"
        )
        check.color = ft.Colors.GREEN if state["passed"] else ft.Colors.RED
        stored.value = state["storage"]
        draw()

    def draw():
        """Search at the slider's current effort and rebuild the results table."""
        table.controls = [
            table_row(("index", "recall", "ms", "bytes"), ft.FontWeight.BOLD),
            *(
                table_row((label, f"{recall:.4f}", f"{elapsed:.0f}", f"{size:,}"))
                for label, recall, elapsed, size in rank(state, int(effort.value))
            ),
        ]
        status.value = SUMMARY

    def on_effort_change():
        """Slider release. `on_change_end` fires once, where `on_change` fires per step."""
        work(draw, "Searching…")

    page.appbar = ft.AppBar(title=ft.Text("faiss nearest"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(f"{VERSIONS} · {page.platform.value}", size=11),
                    ft.Text(BUILD_OPTIONS, size=11, selectable=True),
                    check := ft.Text(size=14, weight=ft.FontWeight.BOLD),
                    table := ft.Column(spacing=2),
                    ft.Text("Search effort", size=12),
                    effort := ft.Slider(
                        min=0,
                        max=len(SETTINGS) - 1,
                        divisions=len(SETTINGS) - 1,
                        value=DEFAULT,
                        disabled=True,
                        on_change_end=on_effort_change,
                    ),
                    spinner := ft.ProgressRing(visible=False),
                    status := ft.Text(size=11),
                    stored := ft.Text(size=11, selectable=True),
                ],
            ),
        )
    )

    work(prepare, f"Generating {N:,} vectors and building three indexes…")


if __name__ == "__main__":
    ft.run(main)
