import os
import platform

import flet as ft
from model import BATCHES, IMPORT_ERROR, MODEL_SUMMARY, VERSION, benchmark, describe

COLUMN_WEIGHTS = (3, 4, 4, 3)


def table_row(values):
    """One row of the thread table, laid out by weight so it fits a phone."""
    return ft.Row(
        controls=[ft.Text(v, size=11, expand=w) for v, w in zip(values, COLUMN_WEIGHTS)]
    )


def thread_table(rows):
    """The num_threads table: a header, a rule, then one line per interpreter."""
    return [
        table_row(("num_threads", "load", "invoke", "vs 1")),
        ft.Divider(height=1),
        *(
            table_row(
                (
                    f"{n} thread{'s' if n > 1 else ''}",
                    f"{load:,.1f} ms",
                    f"{invoke:,.2f} ms",
                    f"{ratio:.2f}x",
                )
            )
            for n, load, invoke, ratio in rows
        ),
    ]


def main(page: ft.Page):
    """Run the embedded model at the chosen batch size and report what came back.

    Three things go on screen that only this handset can answer: whether the
    interpreter agrees with numpy, whether XNNPACK actually attached here, and what
    `num_threads` is worth on this SoC.
    """

    def show_batch():
        """Restate the slider position as rows and bytes, on every thumb movement."""
        caption.value = describe(BATCHES[int(size.value)])

    def start():
        """Hand one round to a background thread and lock the slider while it works.

        Driven by on_change_end, which fires once on release, so one gesture means
        one run. The guard is set here rather than in the worker because this body is
        synchronous where `run_thread` only schedules.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Benchmark off the UI thread and rebuild every result line.

        `invoke()` releases the GIL for its whole duration, so the UI keeps its
        frames. The `try/except` is not optional — `page.run_thread` discards
        whatever a worker raises — and the panels are cleared on the way out so the
        previous run's numbers cannot sit under this run's error.
        """
        try:
            rows = BATCHES[int(size.value)]
            result = benchmark(rows)
            verdict.value = (
                f"{'PASS' if result['passed'] else 'FAIL'} · max|tflite - numpy| = "
                f"{result['worst']:.2e} against a {result['tolerance']:.0e} "
                f"tolerance, over {rows:,} rows"
            )
            verdict.color = ft.Colors.GREEN if result["passed"] else ft.Colors.RED
            scaling.controls = thread_table(result["rows"])
            footer.value = (
                f"median of {result['runs']} invokes · ops {result['ops']} — a "
                f"DELEGATE entry is XNNPACK · os.cpu_count() = {os.cpu_count()}"
            )
        except Exception as error:
            scaling.controls = []
            footer.value = ""
            verdict.color = ft.Colors.RED
            verdict.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(
        title=ft.Text("tflite-runtime threads and delegates"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"{VERSION} · Python {platform.python_version()} · "
                        f"{page.platform.value}",
                        size=11,
                    ),
                    ft.Text(MODEL_SUMMARY, size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=0,
                        max=len(BATCHES) - 1,
                        value=2,
                        divisions=len(BATCHES) - 1,
                        on_change=show_batch,
                        on_change_end=start,
                    ),
                    verdict := ft.Text(size=12),
                    ft.Divider(),
                    scaling := ft.Column(spacing=2),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_batch()  # derived from the slider alone, so it fills in even without a wheel

    if IMPORT_ERROR:
        verdict.value = f"tflite_runtime is not installed here — {IMPORT_ERROR}"
        verdict.color = ft.Colors.RED
        size.disabled = True
        page.update()
        return

    start()


if __name__ == "__main__":
    ft.run(main)
