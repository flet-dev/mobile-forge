import flet as ft
from charts import SPECS, VERSIONS, render


def main(page: ft.Page):
    def show(name):
        """Start converting `name` on a background thread, spinner up."""
        spinner.visible = True
        page.update()
        page.run_thread(work, name)

    def work(name):
        """Convert the spec to PNG off the UI thread, then show it with its timing."""
        try:
            png, (width, height), elapsed = render(name, 280)
        except Exception as exc:
            caption.value = f"{type(exc).__name__}: {exc}"
        else:
            chart.src = png
            caption.value = f"{width}×{height} px PNG in {elapsed:.2f} s"
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title="Vega-Lite charts", center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.SegmentedButton(
                        selected=["Bars"],
                        segments=[ft.Segment(value=n, label=n) for n in SPECS],
                        on_change=lambda e: show(e.control.selected[0]),
                    ),
                    ft.Container(
                        expand=True,
                        alignment=ft.Alignment.CENTER,
                        # gapless_playback keeps the old chart up until the new one decodes.
                        content=(
                            chart := ft.Image(
                                src=b"", fit=ft.BoxFit.CONTAIN, gapless_playback=True
                            )
                        ),
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            caption := ft.Text(
                                "First chart boots the JavaScript runtime…", size=12
                            ),
                            spinner := ft.ProgressRing(width=14, height=14),
                        ],
                    ),
                    ft.Text(VERSIONS, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
            ),
        )
    )
    show("Bars")


if __name__ == "__main__":
    ft.run(main)
