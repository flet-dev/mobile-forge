import flet as ft
from waveform import TRUE, VERSION, analyse


def row(label, *cells):
    """One line of the results table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    """Show a noise slider, a Fit button, and a table of true against fitted values.

    The header line reports the scipy build the app is running on, including the
    BLAS it is linked against.
    """

    def show_noise():
        """Report the noise the next fit will use; the slider sets it, Fit runs it."""
        caption.value = f"Noise added before filtering: {noise.value:.1f}"

    def fit():
        """Run the analysis on a background thread, so the UI stays live.

        The button stays disabled until compute() re-enables it, which keeps two
        fits from overlapping and writing the table in the wrong order.
        """
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Fit at the slider's noise level and fill in the results table.

        The body of the thread fit() starts. Push the noise up and the fitted
        amplitude starts to wander while the frequency holds: the spectrum peak
        survives noise that the tail of a decaying signal does not.
        """
        peak, fitted, error = analyse(noise.value)
        results.controls = [
            row("", "true", "fitted"),
            ft.Divider(height=1),
            *(
                row(name, f"{value:.4f}", f"{fitted[name]:.4f}")
                for name, value in TRUE.items()
            ),
            ft.Divider(height=1),
            row("spectrum peak", f"{peak:.4f} Hz"),
            row("rms error", f"{error:.2e}"),
        ]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("scipy signal fit"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    caption := ft.Text(),
                    noise := ft.Slider(
                        min=0.0,
                        max=4.0,
                        value=1.0,
                        divisions=8,
                        round=1,
                        label="{value}",
                        on_change=show_noise,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Fit", icon=ft.Icons.SHOW_CHART, on_click=fit
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

    show_noise()
    fit()


if __name__ == "__main__":
    ft.run(main)
