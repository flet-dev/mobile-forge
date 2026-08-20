import flet as ft
from history import (
    BURST,
    CAPTION,
    EDIT_KEY,
    SIZEOF_NOTE,
    TITLE_KEY,
    burst,
    compare,
    new_document,
    retitle,
    summarise,
)


def row(label, *cells):
    """One line of the comparison table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=4), *(ft.Text(c, expand=3) for c in cells)]
    )


def main(page: ft.Page):
    """Edit one document, keep every version, and jump back to any of them."""
    versions = [new_document()]
    current = 0

    def goto(index):
        """Park the timeline on a version, clamped, and refill the controls from it.

        Jumping is a list index and two key reads: every version is a live map
        that was never copied, so there is nothing to restore and no edit log to
        replay.
        """
        nonlocal current
        current = max(0, min(len(versions) - 1, index))
        doc = versions[current]
        title.value = doc[TITLE_KEY]
        note.value = f"version {current + 1} of {len(versions)} — {doc[EDIT_KEY]}"
        # A Slider needs max > min even when there is only one version to show.
        timeline.max = max(len(versions) - 1, 1)
        timeline.value = current
        timeline.disabled = len(versions) < 2
        page.update()

    def commit(fresh):
        """Append new versions, dropping any redo tail, and park on the last one."""
        del versions[current + 1 :]
        versions.extend(fresh)
        goto(len(versions) - 1)

    def on_title(e):
        """Turn a typed title into a new version, ignoring a re-submit of the same one.

        The guard is not an optimisation: insert always allocates, so without it
        every focus change would push an identical version onto the stack.
        """
        typed = e.control.value.strip() or "Untitled note"
        if typed != versions[current][TITLE_KEY]:
            commit([retitle(versions[current], typed)])

    def scramble(e):
        """Apply a burst of random field edits, keeping every version in between."""
        commit(burst(versions[current], len(versions)))

    def nav(icon, delta):
        """Build an undo or redo button: one step along the timeline."""
        return ft.IconButton(icon, on_click=lambda: goto(current + delta))

    def on_timeline(e):
        """Scrub to any version while the thumb moves, not just when released.

        This slider recomputes nothing, so there is no reason to defer to
        on_change_end.
        """
        goto(int(e.control.value))

    def measure(e):
        """Lock the button and hand the comparison to a background thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Time both snapshot strategies and fill in the results table.

        Safe to run while the timeline is scrubbed, with no lock: the versions
        this thread reads cannot be mutated by the UI thread.
        """
        head, *rest = summarise(compare(versions[current], len(versions)))
        results.controls = [
            row(*head),
            ft.Divider(height=1),
            *(row(*cells) for cells in rest),
            ft.Text(SIZEOF_NOTE, size=11),
        ]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Undo stack"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(CAPTION, size=12),
                    title := ft.TextField(
                        label="Title",
                        dense=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        on_submit=on_title,
                        on_blur=on_title,
                    ),
                    timeline := ft.Slider(min=0, max=1, on_change=on_timeline),
                    note := ft.Text(size=11, color=ft.Colors.PRIMARY),
                    ft.Row(
                        wrap=True,
                        run_spacing=4,
                        controls=[
                            nav(ft.Icons.UNDO, -1),
                            nav(ft.Icons.REDO, 1),
                            ft.Button(
                                f"{BURST} random edits",
                                icon=ft.Icons.SHUFFLE,
                                on_click=scramble,
                            ),
                            button := ft.Button(
                                "Compare with dict copies",
                                icon=ft.Icons.SPEED,
                                on_click=measure,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ],
                    ),
                    results := ft.Column(spacing=4),
                ],
            ),
        )
    )

    goto(0)


if __name__ == "__main__":
    ft.run(main)
