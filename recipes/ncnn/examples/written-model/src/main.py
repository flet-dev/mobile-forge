import flet as ft
from model import (
    CHANNELS,
    CORES,
    DEFAULT_THREADS,
    GPU,
    REPEATS,
    TOLERANCE,
    VERSIONS,
    cpu_summary,
    describe,
    run,
)

COLUMN_WEIGHTS = (6, 4, 4, 3)


def table_row(values):
    """One row of the results table, laid out by weight so it fits a phone."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=weight)
            for value, weight in zip(values, COLUMN_WEIGHTS)
        ]
    )


def result_row(label, difference, median_ms, ratio):
    """One measured configuration as a table row; the ratio is blank where it is moot."""
    return table_row(
        (
            label,
            f"{difference:.1e}",
            f"{median_ms:,.1f} ms",
            "—" if ratio is None else f"{ratio:.2f}x",
        )
    )


def main(page: ft.Page):
    """Write a model, run it three ways, and report what this device answered.

    Two sliders drive it: the channel count sets how much arithmetic one inference is, and
    the thread count is ncnn's one portable performance knob. Both recompute on release.
    """

    def show_channels():
        """Report the model the next round will write, as the channel slider moves."""
        caption.value = describe(CHANNELS[round(width.value)])

    def show_threads():
        """Report the thread count the next round will use, as its slider moves."""
        cores.value = cpu_summary(round(threads.value))

    def start():
        """Hand one round to a background thread and lock the sliders while it works.

        The spinner and the guard go up here, not inside the worker: `extract` holds the
        GIL, so a state change made in there would not reach the screen until the work
        was already over.
        """
        if width.disabled:
            return
        width.disabled = threads.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Run one round and rebuild every result line from it.

        The `try/except` is not optional: `page.run_thread` discards whatever a worker
        raises, so a failure in here would look like a screen that simply stopped
        updating.
        """
        try:
            result = run(CHANNELS[round(width.value)], round(threads.value))
            files.value = (
                f"wrote {result['param_bytes']:,} B of .param and "
                f"{result['bin_bytes']:,} B of .bin to {result['storage']}"
            )
            graph.value = f"ncnn read it back as {result['graph']}"
            table.controls = [
                table_row(("run", "max diff", "median", "vs 1 thread")),
                ft.Divider(height=1),
                *(result_row(*row) for row in result["rows"]),
            ]
            verdict.value = (
                f"{'PASS' if result['passed'] else 'FAIL'} · fp16 off agrees with numpy "
                f"to {result['exact_diff']:.1e} against a {TOLERANCE:.0e} tolerance · "
                f"the defaults agree to {result['default_diff']:.1e}, because they do "
                "the arithmetic in fp16"
            )
            verdict.color = ft.Colors.GREEN if result["passed"] else ft.Colors.RED
            footer.value = (
                f"diffs relative to the largest output · median of {REPEATS} inferences "
                f"· loading took {result['load_ms']:,.0f} ms · whole round "
                f"{result['round_ms']:,.0f} ms, {result['reference_ms']:,.0f} ms of it "
                f"the numpy cross-check · peak RSS {result['peak_mb']:,.0f} MB"
            )
        except Exception as error:
            table.controls = []
            files.value = graph.value = footer.value = ""
            verdict.color = ft.Colors.RED
            verdict.value = f"{type(error).__name__}: {error}"

        width.disabled = threads.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("ncnn written model"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(f"{VERSIONS} · {page.platform.value}", size=11),
                    ft.Text(GPU, size=11),
                    files := ft.Text(size=11),
                    graph := ft.Text(size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True, size=12),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    width := ft.Slider(
                        min=0,
                        max=len(CHANNELS) - 1,
                        value=3,
                        divisions=len(CHANNELS) - 1,
                        on_change=show_channels,
                        # on_change would rebuild and re-run the model for every pixel
                        # the thumb travels; on_change_end runs one round, on release.
                        on_change_end=start,
                    ),
                    cores := ft.Text(size=12),
                    threads := ft.Slider(
                        min=1,
                        max=CORES,
                        value=DEFAULT_THREADS,
                        divisions=CORES - 1,
                        on_change=show_threads,
                        on_change_end=start,
                    ),
                    verdict := ft.Text(size=12),
                    ft.Divider(),
                    table := ft.Column(spacing=2),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_channels()
    show_threads()
    start()


if __name__ == "__main__":
    ft.run(main)
