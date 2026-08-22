"""Watch a bell curve appear as numpy averages more and more uniform draws."""

import flet as ft
from distribution import BUILD, SAMPLES, sample

BAR_HEIGHT = 160


def bars(counts):
    """Turn bin counts into Containers, scaled so the tallest bin fills the row.

    Plain Container heights rather than a chart, which keeps the app's
    dependencies down to Flet and numpy.
    """
    scale = BAR_HEIGHT / max(counts)
    return [
        ft.Container(
            height=max(2.0, scale * count),
            bgcolor=ft.Colors.PRIMARY,
            border_radius=2,
            expand=True,
        )
        for count in counts
    ]


def row(label, *cells):
    """One line of the results table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    """Show the histogram, a slider for the draws behind each sample, and a table.

    The table sets the measured mean and standard deviation against what theory
    predicts. The header line reports what the wheel actually is: which BLAS sits
    behind it (`none` on device) and how wide `long double` is, which is where
    the Android and iOS wheels' arithmetic parts company.
    """

    def show_draws():
        """Keep the caption in step with the slider, which moves as it is dragged."""
        caption.value = f"Averaging {draws.value:.0f} uniform draws per sample"

    def resample():
        """Start a sampling run on a background thread, so the UI stays live."""
        # Driven by on_change_end, which fires once when the slider is released.
        # on_change fires for every pixel of the drag and would start a fresh
        # 100,000-sample run each time.
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Sample at the slider's setting, then refill the histogram and table.

        The body of the thread resample() starts. Everything on screen here is a
        plain Python number: the casting happens in distribution.py, so the UI
        never has to defend itself against a numpy scalar.
        """
        k = int(draws.value)
        run = sample(k)
        histogram.controls = bars(run["counts"])
        results.controls = [
            row("", "measured", "predicted"),
            ft.Divider(height=1),
            row("mean", f"{run['mean']:.4f}", "0.5000"),
            row("std dev", f"{run['std']:.4f}", f"{run['predicted']:.4f}"),
            ft.Divider(height=1),
            row("array", f"{SAMPLES:,} × {k}", f"{run['megabytes']:.1f} MB"),
            row("sampled and binned in", f"{run['milliseconds']:.1f} ms"),
        ]
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("numpy bell curve"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(BUILD, size=12),
                    histogram := ft.Row(
                        spacing=2,
                        height=BAR_HEIGHT,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    draws := ft.Slider(
                        min=1,
                        max=12,
                        value=1,
                        divisions=11,
                        round=0,
                        label="{value}",
                        on_change=show_draws,
                        on_change_end=resample,
                    ),
                    results := ft.Column(spacing=4),
                ]
            ),
        )
    )

    show_draws()
    resample()


if __name__ == "__main__":
    ft.run(main)
