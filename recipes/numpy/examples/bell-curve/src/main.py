"""Watch a bell curve appear as numpy averages more and more uniform draws."""

import time

import flet as ft
import numpy as np

SAMPLES = 100_000
BINS = 25
BAR_HEIGHT = 160

BLAS = np.show_config(mode="dicts")["Build Dependencies"]["blas"]["name"]
LONGDOUBLE = np.dtype(np.longdouble).itemsize * 8

rng = np.random.default_rng()


def sample(draws):
    """Average `draws` uniform values 100,000 times, and bin the means.

    Returns the bin counts, the mean and standard deviation of those means, and
    how long the work took — the elapsed time is reported on screen because how
    cheap this is on a phone is half of what the app is demonstrating.
    """
    start = time.perf_counter()

    # One 2-D draw averaged along its second axis, rather than a loop over samples:
    # the whole batch stays inside compiled code, which is what makes this cheap.
    means = rng.random((SAMPLES, draws)).mean(axis=1)
    counts, _ = np.histogram(means, bins=BINS, range=(0.0, 1.0))

    elapsed = time.perf_counter() - start
    return counts, float(means.mean()), float(means.std()), elapsed


def bars(counts):
    """Turn bin counts into Containers, scaled so the tallest bin fills the row.

    Plain Container heights rather than a chart, which keeps the app's
    dependencies down to Flet and numpy.
    """
    # Cast out of numpy scalars here: what crosses into a Flet control is plain Python.
    scale = BAR_HEIGHT / float(counts.max())
    return [
        ft.Container(
            height=max(2.0, scale * float(count)),
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
    behind it (`none` on device) and how wide `long double` is, the one thing
    that differs between the Android and iOS wheels.
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

        The body of the thread resample() starts. The predicted column is the
        central limit theorem's own answer for k uniform draws: a mean of 0.5 and
        a standard deviation of 1/sqrt(12k), which the measured pair tracks to
        within a fraction of a percent.
        """
        k = int(draws.value)
        counts, mean, std, elapsed = sample(k)
        histogram.controls = bars(counts)
        results.controls = [
            row("", "measured", "predicted"),
            ft.Divider(height=1),
            row("mean", f"{mean:.4f}", "0.5000"),
            row("std dev", f"{std:.4f}", f"{1.0 / np.sqrt(12.0 * k):.4f}"),
            ft.Divider(height=1),
            row("array", f"{SAMPLES:,} × {k}"),
            row("sampled and binned in", f"{elapsed * 1e3:.1f} ms"),
        ]
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("numpy bell curve"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"numpy {np.__version__} — BLAS {BLAS} — "
                        f"long double {LONGDOUBLE}-bit",
                        size=12,
                    ),
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
