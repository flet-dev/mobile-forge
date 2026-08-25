import flet as ft
from identify import HEADS, IMPORT_ERROR, library_line, magic, scan

LABEL_WEIGHTS = (4, 7)


def field(label, value, verdict=None):
    """One labelled line inside a card, with an optional MATCH/MISMATCH verdict."""
    controls = [
        ft.Text(label, size=11, expand=LABEL_WEIGHTS[0]),
        ft.Text(value, size=11, expand=LABEL_WEIGHTS[1], selectable=True),
    ]
    if verdict is not None:
        controls.append(
            ft.Text(
                "MATCH" if verdict else "MISMATCH",
                size=11,
                weight=ft.FontWeight.BOLD,
                color=ft.Colors.GREEN if verdict else ft.Colors.RED,
            )
        )
    return ft.Row(controls=controls, spacing=6)


def card(answer):
    """One file's card: its name, what the name suggests, and two libmagic answers."""
    return ft.Card(
        content=ft.Container(
            padding=10,
            content=ft.Column(
                spacing=3,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                answer.name,
                                weight=ft.FontWeight.BOLD,
                                size=13,
                                expand=True,
                            ),
                            ft.Text(
                                f"{answer.size:,} B · really {answer.kind}", size=11
                            ),
                        ]
                    ),
                    field("name suggests", answer.guess),
                    field("from_file", answer.mime, answer.mime_ok),
                    ft.Text(
                        answer.description,
                        size=11,
                        italic=True,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        selectable=True,
                    ),
                    field(
                        f"from_buffer {answer.head:,} B",
                        answer.head_mime,
                        answer.head_ok,
                    ),
                ],
            ),
        )
    )


def main(page: ft.Page):
    """Identify ten files by content, and show where a head sample stops being enough.

    Every row is asked twice about the same bytes. `from_file` lets libmagic read the
    file itself and is right about all ten; `from_buffer` sees only the leading bytes
    the slider allows, and needs a format-specific number of them before it agrees —
    4 for a GIF, 512 for a tar, and, for the ZIP, never, not even at full length.
    """

    def show_head():
        """Report the head size the next run will use, as the slider moves."""
        caption.value = f"from_buffer gets the first {HEADS[int(head.value)]:,} bytes"

    def refresh():
        """Rewrite every card against the current head size, once per slider release."""
        cards.controls = [card(answer) for answer in scan(HEADS[int(head.value)])]
        header.value = library_line(page.platform.value)
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("What is this file?"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    header := ft.Text(IMPORT_ERROR or "", size=11),
                    caption := ft.Text(size=11),
                    head := ft.Slider(
                        min=0,
                        max=len(HEADS) - 1,
                        value=len(HEADS) - 1,
                        divisions=len(HEADS) - 1,
                        # on_change only updates the caption: a full redraw per pixel
                        # travelled would rewrite ten files on every frame.
                        on_change=show_head,
                        on_change_end=refresh,
                    ),
                    cards := ft.ListView(expand=True, spacing=6),
                ],
            ),
        )
    )

    head.disabled = magic is None  # nothing to recompute without a library behind it
    show_head()
    if magic is not None:
        refresh()


if __name__ == "__main__":
    ft.run(main)
