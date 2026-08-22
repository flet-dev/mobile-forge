import flet as ft
from hashing import (
    LONG_PASSPHRASE,
    MAX_COST,
    MIN_COST,
    THREAD_LABEL,
    boundary_rows,
    build_line,
    correctness_rows,
    cost_caption,
    cost_rows,
    cost_summary,
    measure,
    thread_report,
    truncation_report,
)

COSTS, CHECKS, BOUNDS = (2, 3, 3, 2, 3), (7, 2, 2), (5, 2, 2, 3)


def fill(column, rows, weights):
    """Put a header row, a rule, then one row per result into `column`.

    Every table in the app is a list of string tuples from `hashing`, laid out by
    weight rather than by a fixed width so the columns survive a narrow phone.
    """

    def line(values):
        """One table line: a `Text` per value."""
        return ft.Row(
            controls=[
                ft.Text(value, size=11, expand=weight)
                for value, weight in zip(values, weights)
            ]
        )

    header, *body = rows
    column.controls = [line(header), ft.Divider(height=1), *(line(row) for row in body)]


def main(page: ft.Page):
    """Answer "what cost factor can this phone afford" by measuring it.

    Each slider release times one hash and one verification at that cost and adds a
    row, with the ratio to the cost below as a gauge of how much to trust it. Three
    panels settle what a timing alone cannot: that the answers are right, that hashing
    belongs on a background thread, and what happens to a password over 72 bytes.
    """
    measured = {}

    def set_busy(busy):
        """Lock everything that can start a hash, and raise or drop the spinner."""
        for control in (cost, threads_button, as_typed, truncated):
            control.disabled = busy
        spinner.visible = busy

    def show_cost():
        """Report which cost the next run will measure, as the slider moves."""
        caption.value = cost_caption(int(cost.value))

    def start(job):
        """Lock the controls and hand `job` to a background thread.

        The re-entrancy guard is tested and set here rather than in the worker because
        `run_thread` only schedules: a `disabled` set in the worker has not happened
        yet when this handler returns and Flet pushes the control states.
        """
        if spinner.visible:
            return
        set_busy(True)
        page.update()
        page.run_thread(job)

    def run_cost():
        """Measure the slider's cost off the UI thread, then refill the table.

        `page.run_thread` discards whatever a worker raises, so without the catch a
        mistake in here would look like a screen that quietly stopped updating.
        """
        try:
            chosen = int(cost.value)
            measured[chosen] = measure(chosen)
            fill(costs, cost_rows(measured), COSTS)
            prediction.value = cost_summary(measured)
        except Exception as error:
            prediction.value = f"{type(error).__name__}: {error}"
        set_busy(False)
        page.update()  # auto-update does not reach background threads

    def run_threads():
        """Compare serial against threaded hashing, off the UI thread."""
        try:
            threads_text.value = thread_report()
        except Exception as error:
            threads_text.value = f"{type(error).__name__}: {error}"
        set_busy(False)
        page.update()

    def report_long(truncate):
        """Hash the field's contents, optionally cut to 72 bytes first, and report."""
        long_text.value = truncation_report(editor.value, truncate)

    page.appbar = ft.AppBar(title=ft.Text("bcrypt cost factor"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(build_line(page.platform.value), size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    cost := ft.Slider(
                        min=MIN_COST,
                        max=MAX_COST,
                        value=MIN_COST + 2,
                        divisions=MAX_COST - MIN_COST,
                        round=0,
                        label="{value}",
                        on_change=show_cost,
                        # on_change would queue a run per pixel of the drag.
                        on_change_end=lambda: start(run_cost),
                    ),
                    costs := ft.Column(spacing=4),
                    prediction := ft.Text(size=11),
                    ft.Divider(),
                    correctness := ft.Column(spacing=4),
                    stored_text := ft.Text(size=11),
                    ft.Divider(),
                    threads_button := ft.Button(
                        THREAD_LABEL, on_click=lambda: start(run_threads)
                    ),
                    threads_text := ft.Text(size=11),
                    ft.Divider(),
                    boundary := ft.Column(spacing=4),
                    editor := ft.TextField(
                        value=LONG_PASSPHRASE,
                        multiline=True,
                        min_lines=2,
                        max_lines=4,
                        text_size=12,
                        label="a password over 72 bytes",
                    ),
                    ft.Row(
                        wrap=True,
                        controls=[
                            as_typed := ft.Button(
                                "Hash as typed", on_click=lambda: report_long(False)
                            ),
                            truncated := ft.Button(
                                "Truncate to 72 bytes",
                                on_click=lambda: report_long(True),
                            ),
                        ],
                    ),
                    long_text := ft.Text(size=11),
                ],
            ),
        )
    )

    show_cost()
    checks, summary = correctness_rows()
    fill(correctness, checks, CHECKS)
    stored_text.value = summary
    fill(boundary, boundary_rows(), BOUNDS)
    report_long(False)
    start(run_cost)


if __name__ == "__main__":
    ft.run(main)
