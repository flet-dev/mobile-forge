"""Screen for the hand-built GGUF: pick a width, run the pipeline, show what came back."""

import flet as ft
import model

STAGE_WEIGHTS = (5, 3, 8)

QUANT_WEIGHTS = (3, 5, 4)


def row(values, weights):
    """One table row, laid out by column weight so it fits a phone."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def table(header, rows, weights):
    """A header row, a rule, then one row per result tuple."""
    return [
        row(header, weights),
        ft.Divider(height=1),
        *(row(values, weights) for values in rows),
    ]


def main(page: ft.Page):
    """Build a model at the chosen width, run it, and report what came back.

    Everything on screen is computed on this device: the model file, the tokens
    llama.cpp generated from it, whether its logits agree with an independent numpy
    forward pass, and what the same weights cost once quantised. The weights are random,
    so the tokens are meaningless by construction — the pipeline is the point.
    """

    def show_width():
        """Report the model the next run will build, as the slider moves."""
        caption.value = model.describe(model.WIDTHS[int(size.value)])

    def start():
        """Hand one run to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end so one gesture means one run. The guard is
        set here rather than in the worker because this body is synchronous where
        `run_thread` only schedules: a `disabled` set inside the worker would not have
        reached the client before the next gesture arrived.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(worker)

    def worker():
        """Run the pipeline off the UI thread and rebuild the panels from its result.

        Worth a thread: the llama.cpp calls release the GIL, but the Python around them
        holds it in bursts long enough to stall every later handler. The `try/except` is
        not optional — `page.run_thread` discards whatever a worker raises, so a failure
        would look like a screen that simply stopped updating — and the panels are
        cleared on the way out so a previous run's numbers cannot sit under this run's
        error.
        """
        try:
            result = model.run(model.WIDTHS[int(size.value)])
            verdict.value = result.verdict
            verdict.color = ft.Colors.GREEN if result.passed else ft.Colors.RED
            stages.controls = table(
                ("stage", "ms", "result"), result.stages, STAGE_WEIGHTS
            )
            quantisation.controls = table(
                ("type", "file bytes", "bits/weight (file)"),
                result.quantised,
                QUANT_WEIGHTS,
            )
            footer.value = result.footer
        except Exception as error:
            stages.controls = []
            quantisation.controls = []
            footer.value = ""
            verdict.color = ft.Colors.RED
            verdict.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(
        title=ft.Text("llama.cpp hand-built GGUF"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    *(
                        ft.Text(line, size=11)
                        for line in model.banner(page.platform.value)
                    ),
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
                        max=len(model.WIDTHS) - 1,
                        value=2,
                        divisions=len(model.WIDTHS) - 1,
                        on_change=show_width,
                        on_change_end=start,
                    ),
                    verdict := ft.Text(size=12),
                    ft.Divider(),
                    stages := ft.Column(spacing=2),
                    ft.Divider(),
                    quantisation := ft.Column(spacing=2),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_width()
    start()


if __name__ == "__main__":
    ft.run(main)
