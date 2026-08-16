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
    start = time.perf_counter()

    # One 2-D draw averaged along its second axis, rather than a loop over samples:
    # the whole batch stays inside compiled code, which is what makes this cheap.
    means = rng.random((SAMPLES, draws)).mean(axis=1)
    counts, _ = np.histogram(means, bins=BINS, range=(0.0, 1.0))

    elapsed = time.perf_counter() - start
    return counts, float(means.mean()), float(means.std()), elapsed


def bars(counts):
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
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    def show_draws():
        caption.value = f"Averaging {draws.value:.0f} uniform draws per sample"

    def resample():
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
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
        button.disabled = False
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
                    caption := ft.Text(),
                    draws := ft.Slider(
                        min=1,
                        max=12,
                        value=1,
                        divisions=11,
                        round=0,
                        label="{value}",
                        on_change=show_draws,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Draw", icon=ft.Icons.CASINO, on_click=resample
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
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
