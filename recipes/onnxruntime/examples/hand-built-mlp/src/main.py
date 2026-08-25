import flet as ft
from model import (
    BATCHES,
    CPUS,
    LAYERS,
    PROVIDERS,
    RUNS,
    SUMMARY,
    TOLERANCE,
    VERSIONS,
    evaluate,
)

COLUMNS = (3, 4, 4, 3)


def table_row(values, size=11):
    """One row of the thread-scaling table, laid out by weight so it fits a phone."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, COLUMNS)
        ]
    )


def main(page: ft.Page):
    """Run the hand-built graph at the chosen batch size and report what came back.

    Three things go on screen that a phone can only answer for itself: which execution
    providers this build actually has, whether the graph agrees with numpy to a tolerance,
    and what `intra_op_num_threads` is worth on this SoC. The slider picks the batch size
    and releasing it recomputes everything.
    """

    def show_batch():
        """Report the batch size the next run will use, as the slider moves."""
        rows = BATCHES[int(size.value)]
        caption.value = (
            f"{rows:,} row{'s' if rows > 1 else ''} of {LAYERS[0][0]} features"
        )

    def start():
        """Hand one measurement round to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end, which fires once on release, so one gesture
        means one run. The guard is set here rather than in the worker because this body is
        synchronous where `run_thread` only schedules — a `disabled` set inside the worker
        would not have taken effect before Flet pushed the control states.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Evaluate one batch and rebuild every result line.

        Worth a thread: `sess.run` releases the GIL for the whole computation, so the UI
        keeps its frames while this works. The `try/except` is not optional — `page.run_thread`
        discards whatever a worker raises, so a failure in here would look like a screen
        that simply stopped updating — and the panels are cleared on the way out so the
        previous run's numbers cannot sit under this run's error.
        """
        try:
            result = evaluate(BATCHES[int(size.value)])
            verdict.value = (
                f"{'PASS' if result['passed'] else 'FAIL'} · max|ort - numpy| = "
                f"{result['worst']:.2e} against a {TOLERANCE:.0e} tolerance · top class "
                f"agrees on {result['agreed']:,}/{result['batch']:,} rows"
            )
            verdict.color = ft.Colors.GREEN if result["passed"] else ft.Colors.RED

            baseline = result["rows"][0]["median_ms"]
            scaling.controls = [
                table_row(("intra_op", "session", "inference", "vs 1")),
                ft.Divider(height=1),
                *(
                    table_row(
                        (
                            f"{row['intra_op']} thread"
                            + ("s" if row["intra_op"] > 1 else ""),
                            f"{row['build_ms']:,.1f} ms",
                            f"{row['median_ms']:,.1f} ms",
                            f"{baseline / row['median_ms']:.2f}x",
                        )
                    )
                    for row in result["rows"]
                ),
            ]
            footer.value = (
                f"median of {RUNS} runs at batch {result['batch']:,} · session providers "
                f"{result['rows'][0]['providers']} · os.cpu_count() = {CPUS}"
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
        title=ft.Text("onnxruntime hand-built MLP"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(f"{VERSIONS} · {page.platform.value}", size=11),
                    ft.Text(PROVIDERS, size=11),
                    ft.Text(SUMMARY, size=11),
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
                        value=3,
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

    show_batch()
    start()


if __name__ == "__main__":
    ft.run(main)
