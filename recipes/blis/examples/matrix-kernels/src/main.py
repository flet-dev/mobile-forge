import flet as ft
from kernels import BUILD, JOBS, SIZES, THREADS, measure


def line(label, *cells):
    """One row of the results table: a label, then a column per figure."""
    return ft.Row(
        controls=[ft.Text(label, expand=4), *(ft.Text(c, expand=3) for c in cells)]
    )


def choices(values, selected):
    """A row of exclusive choices, pre-selected. `selected` is a list, not a set."""
    return ft.SegmentedButton(
        segments=[ft.Segment(value=str(v), label=ft.Text(str(v))) for v in values],
        selected=[str(selected)],
        show_selected_icon=False,
    )


def main(page: ft.Page):
    """Measure BLIS against numpy at a chosen matrix size and thread count.

    The run takes long enough on a phone to be worth a worker thread, and every
    path back to the UI goes through finish(), which is the only place the
    button is released and page.update() is called.
    """

    def start():
        """Lock the button, raise the spinner and hand the run to a worker."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(guard)

    def guard():
        """Publish a failure as a row; run_thread would swallow it and hang the UI."""
        try:
            run()
        except Exception as exc:
            finish([line("failed", str(exc))])

    def finish(controls):
        """Publish a finished table and release the button."""
        results.controls = controls
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def run():
        """Measure at the current settings and lay the numbers out.

        The relative difference is the check worth making: BLIS and numpy sum
        the same products in a different order, so the results agree to about
        float32's precision rather than bit for bit.
        """
        size = int(matrix.selected[0])
        threads = int(workers.selected[0])
        found = measure(size, threads)
        finish(
            [
                line(f"{size} x {size} x {size}", "blis", "numpy"),
                ft.Divider(height=1),
                *(
                    line(
                        dtype,
                        f"{blis_ms:.2f} ms · {blis_rate:.1f} GF/s",
                        f"{numpy_ms:.2f} ms · {numpy_rate:.1f} GF/s",
                    )
                    for dtype, (
                        blis_ms,
                        blis_rate,
                        numpy_ms,
                        numpy_rate,
                        _,
                    ) in found["rates"].items()
                ),
                ft.Divider(height=1),
                line("largest relative difference", f"{found['difference']:.1e}"),
                line("second gemm into the same out", f"{found['accumulated']:.2f}x"),
                line("serial baseline", f"{JOBS} gemms · {found['serial_ms']:.1f} ms"),
                line(
                    f"across {threads} thread(s)",
                    f"{found['parallel_ms']:.1f} ms · {found['speedup']:.2f}x",
                ),
            ]
        )

    page.appbar = ft.AppBar(title=ft.Text("BLIS matrix kernels"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(BUILD, size=11),
                    ft.Text("Square matrix size", size=12),
                    matrix := choices(SIZES, 256),
                    ft.Text("Python threads sharing the work", size=12),
                    workers := choices(THREADS, 2),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Measure",
                                icon=ft.Icons.SPEED,
                                on_click=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
