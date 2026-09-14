import flet as ft
import soundfile as sf
from audio_codecs import RATE, SECONDS, envelope, run_all, signal

BARS = 64
WAVE_HEIGHT = 70


def bars(levels, color):
    """A waveform strip: one centred bar per bucket, height scaled to its peak."""
    return ft.Row(
        controls=[
            ft.Container(
                width=3,
                height=max(2, level * WAVE_HEIGHT),
                bgcolor=color,
                border_radius=1,
            )
            for level in levels
        ],
        spacing=1,
        alignment=ft.MainAxisAlignment.CENTER,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        height=WAVE_HEIGHT,
    )


def cell(text, width, color=None, mono=True):
    """One fixed-width table cell."""
    return ft.Container(
        width=width,
        content=ft.Text(
            text,
            size=11,
            color=color,
            font_family="monospace" if mono else None,
        ),
    )


def row_for(result):
    """One result line: size, compression against raw float64, time, RMS error."""
    if "error" in result:
        return ft.Row(
            controls=[
                cell(result["label"], 110, mono=False),
                cell(result["error"][:40], 200, color=ft.Colors.RED),
            ]
        )
    return ft.Row(
        controls=[
            cell(result["label"], 110, mono=False),
            cell(f"{result['bytes'] / 1000:.1f} kB", 62),
            cell(f"{result['ratio']:.0f}x", 40, color=ft.Colors.BLUE),
            cell(f"{result['seconds'] * 1e3:.0f} ms", 55),
            cell(f"{result['rms_error']:.0e}", 55, color=ft.Colors.GREY),
        ]
    )


def main(page: ft.Page):
    def encode_all():
        """The whole sweep. Runs on a worker thread; soundfile releases the GIL."""
        button.disabled = True
        spinner.visible = True
        page.update()

        results = run_all()
        table.controls = [
            ft.Row(
                controls=[
                    cell("", 110),
                    cell("size", 62),
                    cell("vs raw", 40),
                    cell("time", 55),
                    cell("rms err", 55),
                ]
            ),
            ft.Divider(height=1),
            *(row_for(r) for r in results),
        ]

        lossy = next(r for r in results if r["label"] == "MP3" and "waveform" in r)
        decoded.controls = [
            ft.Text("decoded MP3", size=11),
            bars(envelope(lossy["waveform"], BARS), ft.Colors.ORANGE),
        ]

        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("soundfile round-trip"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"{SECONDS:g} s chord, {RATE // 1000} kHz, generated in numpy",
                        size=11,
                    ),
                    bars(envelope(signal(), BARS), ft.Colors.BLUE),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Re-encode",
                                on_click=lambda: page.run_thread(encode_all),
                            ),
                            spinner := ft.ProgressRing(
                                visible=False, width=18, height=18
                            ),
                        ]
                    ),
                    table := ft.Column(spacing=2),
                    ft.Divider(),
                    decoded := ft.Column(spacing=2),
                    ft.Divider(),
                    ft.Text(f"libsndfile {sf.__libsndfile_version__}", size=11),
                ],
            ),
        )
    )
    page.run_thread(encode_all)


ft.run(main)
