import flet as ft
from resampling import (
    QUALITIES,
    SECONDS,
    SOURCE_RATE,
    TARGET_RATES,
    convert,
    engine_for,
    tone,
)


def main(page: ft.Page):
    """Wire the rate buttons to a background resample and report the result."""
    source = tone()

    def resample_to(rate):
        """Run one conversion off the UI thread, with the spinner up."""

        def work():
            """Resample, then refill the caption from the worker thread."""
            spinner.visible = True
            page.update()

            frames, elapsed = convert(source, rate)
            headline.value = f"{SOURCE_RATE:,} Hz → {rate:,} Hz"
            detail.value = (
                f"{len(source):,} frames in, {frames:,} out\n"
                f"{elapsed * 1e3:.1f} ms for {SECONDS} s of audio "
                f"({SECONDS / elapsed:,.0f}x realtime)"
            )
            spinner.visible = False
            page.update()  # auto-update does not reach background threads

        # soxr releases the GIL while resampling, so this genuinely runs in parallel.
        page.run_thread(work)

    spinner = ft.ProgressRing(visible=False, width=18, height=18)
    headline = ft.Text("Pick a target rate", size=18, weight=ft.FontWeight.BOLD)
    detail = ft.Text("")

    page.appbar = ft.AppBar(title=ft.Text("Resample a tone"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Button(
                                f"{rate // 1000}k",
                                on_click=lambda _, r=rate: resample_to(r),
                            )
                            for rate in TARGET_RATES
                        ],
                        wrap=True,
                    ),
                    ft.Row(controls=[headline, spinner]),
                    detail,
                    ft.Divider(),
                    ft.Text("libsoxr core per quality setting", size=11),
                    ft.Text(
                        "  ".join(f"{q}={engine_for(q)}" for q in QUALITIES),
                        size=11,
                        font_family="monospace",
                    ),
                ],
            ),
        )
    )


ft.run(main)
