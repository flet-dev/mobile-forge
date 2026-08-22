import flet as ft
from swap import FRAME_MS, SIZES, divergences, header, measure

TIMING_WEIGHTS = (3, 3, 3, 4)

CASE_WEIGHTS = (4, 5, 5)


def table_row(values, weights, size=11):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def ratio(quick, slow):
    """How many times faster `quick` is than `slow`, from the displayed values.

    Both arguments are already rounded to what the table prints, so the ratio a
    reader computes from the two columns is the one shown. A rounded-to-zero
    numerator would make that division meaningless rather than merely imprecise.
    """
    return f"{slow / quick:.1f}x faster" if quick else "too fast to time"


def plural(records):
    """`records` with a thousands separator and the right noun after it."""
    return f"{records:,} record{'' if records == 1 else 's'}"


def main(page: ft.Page):
    """Measure the swap on this device and print what it would change."""

    def show_count():
        """Report the document size the next run will use, as the slider moves."""
        caption.value = f"{plural(SIZES[int(size.value)])} per document"

    def start():
        """Hand one run to a background thread and lock the slider while it works.

        The guard is tested and set here rather than inside `run`, because this
        body is synchronous where `run_thread` only schedules: a `disabled` set in
        the worker would not have happened yet when this handler returns and Flet
        pushes the control states, so a second release would start a second run
        over the same table.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Time both libraries on the chosen document and fill the table.

        orjson holds the GIL for the whole call, so this thread buys nothing but a
        handler that returns immediately -- the honest reason to use it here. The
        try/except is load-bearing: `run_thread` discards whatever a worker raises,
        so a mistake in here would look like a screen that quietly stopped
        updating. It clears the table as well, because timings left from the
        previous run read as though they described the error.
        """
        try:
            records = SIZES[int(size.value)]
            result = measure(records)
            fast_out, slow_out = result["dumps"]
            fast_in, slow_in = result["loads"]
            narrow, wide = result["size"]
            rows = (
                ("dumps µs", fast_out, slow_out, ratio(fast_out, slow_out)),
                ("loads µs", fast_in, slow_in, ratio(fast_in, slow_in)),
                ("output B", narrow, wide, f"{100 * (wide - narrow) // wide}% smaller"),
            )
            timings.controls = [
                table_row(
                    ("measure", "orjson", "json", "orjson vs json"), TIMING_WEIGHTS
                ),
                ft.Divider(height=1),
                *(
                    table_row((label, f"{a:,}", f"{b:,}", tail), TIMING_WEIGHTS)
                    for label, a, b, tail in rows
                ),
            ]
            checks.value = (
                f"round trip: {'identical' if result['same_object'] else 'DIFFERENT'} "
                f"objects · vs json compact: "
                f"{'identical' if result['same_bytes'] else 'DIFFERENT'} bytes"
            )
            verdict.value = (
                f"{plural(records)} · dumps saves {slow_out - fast_out:,.1f} µs and "
                f"loads saves {slow_in - fast_in:,.1f} µs per call, against a "
                f"{FRAME_MS} ms frame at 60 Hz"
            )
        except Exception as error:
            timings.controls = []
            checks.value = ""
            verdict.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    running, returns = header(page.platform.value)
    page.appbar = ft.AppBar(title=ft.Text("orjson vs json"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(running, size=11),
                    ft.Text(returns, size=11),
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
                        max=len(SIZES) - 1,
                        value=3,
                        divisions=len(SIZES) - 1,
                        on_change=show_count,
                        # on_change_end so one drag means one run, not one per pixel
                        on_change_end=start,
                    ),
                    timings := ft.Column(spacing=4),
                    checks := ft.Text(size=11),
                    verdict := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("json vs orjson, case by case", size=11),
                    ft.Column(
                        spacing=4,
                        controls=[
                            table_row(
                                ("case", "json", "orjson"), CASE_WEIGHTS, size=10
                            ),
                            ft.Divider(height=1),
                            *(
                                table_row(row, CASE_WEIGHTS, size=10)
                                for row in divergences()
                            ),
                        ],
                    ),
                ],
            ),
        )
    )

    show_count()
    start()


if __name__ == "__main__":
    ft.run(main)
