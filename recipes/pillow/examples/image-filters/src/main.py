import flet as ft
from filters import EFFECTS, SIZE, VERSION, apply_effect


def main(page: ft.Page):
    """Show a Pillow-drawn picture, a filter picker, and the strength slider."""

    def render():
        """Raise the spinner and hand the filtering to a background thread."""
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Filter at the current settings and swap the new PNG bytes into the preview."""
        name, amount = effect.value, strength.value
        try:
            data, elapsed = apply_effect(name, amount)
        except Exception as exc:
            # run_thread swallows whatever the worker raises, so show it here or
            # a failed render is indistinguishable from a slow one.
            caption.value = f"{type(exc).__name__}: {exc}"
        else:
            preview.src = data
            caption.value = (
                f"{name} at {amount:.0f} — PNG, {len(data) / 1000:.1f} KB, "
                f"{elapsed:.0f} ms"
            )
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Pillow image filters"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(VERSION, size=12),
                    # src is required; the first background render fills it in.
                    # gapless_playback keeps the control from blanking between
                    # renders, since every encode is a different byte string.
                    preview := ft.Image(
                        src=b"",
                        width=SIZE,
                        height=SIZE,
                        border_radius=8,
                        gapless_playback=True,
                    ),
                    ft.Row(
                        controls=[
                            effect := ft.Dropdown(
                                expand=True,
                                label="Effect",
                                value=next(iter(EFFECTS)),
                                options=[ft.DropdownOption(name) for name in EFFECTS],
                                on_select=render,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    # on_change_end, not on_change: one render per gesture, so two
                    # workers can never land out of order and swap the preview back.
                    strength := ft.Slider(
                        min=0,
                        max=7,
                        value=4,
                        divisions=7,
                        round=0,
                        label="{value}",
                        on_change_end=render,
                    ),
                    caption := ft.Text(size=12),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                scroll=ft.ScrollMode.AUTO,
            ),
        )
    )

    render()


if __name__ == "__main__":
    ft.run(main)
