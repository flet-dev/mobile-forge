import flet as ft

from document import TITLES, VERSIONS, render


def main(page: ft.Page):
    state = {"index": 0, "term": ""}

    def redraw():
        """Kick off a render for the current state, with the spinner up."""
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Render on a background thread, then refill the image and the caption."""
        png, hits, (width, height), elapsed = render(state["index"], state["term"])
        sheet.src = png
        position.value = (
            f"{state['index'] + 1} / {len(TITLES)}  ·  {TITLES[state['index']]}"
        )
        found.value = (
            "" if not state["term"] else f"{hits} hit{'' if hits == 1 else 's'}"
        )
        stats.value = (
            f"rasterised {width}x{height} px in {elapsed * 1e3:.0f} ms · "
            f"{len(png) / 1024:.0f} KB PNG"
        )
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def go(delta):
        """Move `delta` pages, clamped to the ends of the document."""
        state["index"] = max(0, min(len(TITLES) - 1, state["index"] + delta))
        redraw()

    def on_search(e):
        """Re-render with the new search term highlighted."""
        state["term"] = e.control.value.strip()
        redraw()

    page.appbar = ft.AppBar(title=ft.Text("Render and read"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(VERSIONS, size=11),
                    ft.TextField(
                        label="Search this page",
                        dense=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_submit=on_search,
                        on_blur=on_search,
                    ),
                    ft.Container(
                        expand=True,
                        alignment=ft.Alignment.CENTER,
                        content=(
                            # src is required, and the first render fills it in;
                            # gapless_playback stops the control blanking between
                            # renders, since each one is a different byte string.
                            sheet := ft.Image(
                                src=b"",
                                fit=ft.BoxFit.CONTAIN,
                                gapless_playback=True,
                            )
                        ),
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.IconButton(
                                ft.Icons.CHEVRON_LEFT, on_click=lambda: go(-1)
                            ),
                            ft.Column(
                                spacing=0,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    position := ft.Text(size=12),
                                    found := ft.Text(size=11, color=ft.Colors.PRIMARY),
                                ],
                            ),
                            ft.IconButton(
                                ft.Icons.CHEVRON_RIGHT, on_click=lambda: go(1)
                            ),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            stats := ft.Text(size=11, expand=True),
                            spinner := ft.ProgressRing(
                                width=14, height=14, visible=False
                            ),
                        ]
                    ),
                ]
            ),
        )
    )

    redraw()


if __name__ == "__main__":
    ft.run(main)
