import flet as ft
from speech import ensure_model, load_recognizer, transcribe


def main(page: ft.Page):
    recognizers = {}

    def report(message: str):
        status.value = message
        page.update()

    def work():
        """Fetch the model if needed, then transcribe its sample recording.

        run_thread does not update the page for us, so this ends with
        page.update(), and catches its own failures to show them.
        """
        try:
            model = ensure_model(report)
            if "asr" not in recognizers:
                report("Loading model…")
                recognizers["asr"] = load_recognizer(model)
            report("Transcribing…")
            result = transcribe(recognizers["asr"], model / "test_wavs" / "0.wav")
            transcript.value = f"“{result.text}”"
            timing.value = (
                f"{result.audio_s:.1f} s of audio in {result.decode_s:.2f} s "
                f"({result.audio_s / result.decode_s:.0f}x real time), offline"
            )
            status.value = "Done"
        except Exception as exc:
            status.value = f"Failed: {exc!r}"
        button.disabled = False
        spinner.visible = False
        page.update()

    def start(_: ft.Event[ft.Button]):
        button.disabled = True
        spinner.visible = True
        transcript.value = ""
        timing.value = ""
        page.update()
        page.run_thread(work)

    page.appbar = ft.AppBar(title=ft.Text("Offline speech-to-text"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    button := ft.Button("Transcribe the sample", on_click=start),
                    ft.Row(
                        controls=[
                            spinner := ft.ProgressRing(
                                visible=False, width=18, height=18
                            ),
                            status := ft.Text("Model: moonshine tiny (English)"),
                        ]
                    ),
                    transcript := ft.Text(size=20, weight=ft.FontWeight.BOLD),
                    timing := ft.Text(),
                ],
            ),
        )
    )


ft.run(main)
