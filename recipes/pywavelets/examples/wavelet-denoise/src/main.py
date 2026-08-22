"""Wavelet denoising, with an on-screen check that the transform itself loses nothing."""

import threading

import flet as ft
from denoise import SIGNALS, WAVELETS, analyse


def band_row(label, share):
    """One bar of the energy breakdown: band name, filled bar, percentage."""
    return ft.Row(
        controls=[
            ft.Text(label, size=12, width=28),
            ft.ProgressBar(value=share, expand=True),
            ft.Text(f"{100.0 * share:5.2f}%", size=12, width=52),
        ]
    )


def main(page: ft.Page):
    """Pick a signal, a wavelet and a noise level; every number below is computed from them."""
    lock = threading.Lock()

    def recompute():
        """Redo the whole pipeline and redraw.

        Runs in Flet's thread pool, which can overlap two runs, so the lock stops their
        writes from interleaving into the same controls and the explicit page.update() at
        the end does what auto-update does not reach.
        """
        with lock:
            wavelet = wavelets.selected[0]
            sigma = round(noise.value, 2)
            result = analyse(signal.value, wavelet, sigma)

            worst = max(result["signal_residual"], result["image_residual"])
            check.value = (
                f"round trip: signal {result['signal_residual']:.1e}"
                f"   image {result['image_residual']:.1e}"
            )
            check.color = ft.Colors.RED if worst > 1e-9 else ft.Colors.GREEN

            signal_before, signal_after = result["signal_snr"]
            image_before, image_after = result["image_snr"]
            report.value = (
                f"{wavelet} · sigma {sigma:.2f} · "
                f"signal {signal_before:.1f} -> {signal_after:.1f} dB · "
                f"image {image_before:.1f} -> {image_after:.1f} dB"
            )

            bands.controls = [
                band_row(label, share) for label, share in result["bands"]
            ]
            before.src = result["noisy_png"]
            after.src = result["restored_png"]
        page.update()

    def refresh():
        """Send the recompute off the UI thread — the 2-D transforms are far too slow for it."""
        page.run_thread(recompute)

    page.appbar = ft.AppBar(title=ft.Text("Wavelet denoise"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    signal := ft.Dropdown(
                        label="Signal",
                        value=SIGNALS[0],
                        options=[ft.DropdownOption(key=s, text=s) for s in SIGNALS],
                        on_select=refresh,
                    ),
                    wavelets := ft.SegmentedButton(
                        selected=["db4"],
                        segments=[
                            ft.Segment(value=w, label=ft.Text(w, size=11))
                            for w in WAVELETS
                        ],
                        on_change=refresh,
                    ),
                    noise := ft.Slider(
                        min=0.05,
                        max=0.40,
                        divisions=7,
                        round=2,
                        value=0.10,
                        label="sigma {value}",
                        # on_change would rerun the pipeline for every pixel the thumb
                        # travels; on_change_end runs it once, on release.
                        on_change_end=refresh,
                    ),
                    check := ft.Text(size=15, weight=ft.FontWeight.BOLD),
                    report := ft.Text(size=12),
                    bands := ft.Column(spacing=2),
                    ft.Row(
                        controls=[
                            ft.Text(
                                caption,
                                size=11,
                                expand=True,
                                text_align=ft.TextAlign.CENTER,
                            )
                            for caption in ("noisy", "denoised")
                        ]
                    ),
                    ft.Row(
                        controls=[
                            before := ft.Image(
                                src=b"",
                                height=170,
                                expand=True,
                                fit=ft.BoxFit.CONTAIN,
                                gapless_playback=True,
                            ),
                            after := ft.Image(
                                src=b"",
                                height=170,
                                expand=True,
                                fit=ft.BoxFit.CONTAIN,
                                gapless_playback=True,
                            ),
                        ]
                    ),
                ],
            ),
        )
    )

    refresh()


if __name__ == "__main__":
    ft.run(main)
