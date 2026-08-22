import flet as ft
from envelope import (
    BAD,
    DEFAULT_NOTE,
    DEFAULT_PASSPHRASE,
    GOOD,
    IMPORT_ERROR,
    LEVELS,
    PLAIN,
    environment,
    run_pass,
)

TONE = {GOOD: ft.Colors.PRIMARY, BAD: ft.Colors.ERROR, PLAIN: None}


def line(label, value, tone=PLAIN):
    """One result row, sized so neither half overflows a phone-width screen."""
    return ft.Row(
        controls=[
            ft.Text(label, size=11, expand=2, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(value, size=11, expand=5, color=TONE[tone], selectable=True),
        ]
    )


def main(page: ft.Page):
    """Seal the note in a worker thread and report every number the pass produced.

    The pass never runs on the event loop thread: Argon2id is hundreds of
    milliseconds at `interactive` and seconds at `moderate`, and a Flet handler
    that takes that long is a frozen screen. PyNaCl's bindings release the GIL,
    so the worker genuinely steps aside for the UI while it runs.
    """

    def refresh():
        """Run one pass on the current inputs and fill the rows it produced."""
        found = run_pass(note.value, passphrase.value or " ", level.selected[0])
        results.controls = [
            *(line(*row) for row in found["rows"]),
            ft.Divider(height=8),
            *(line(name, f"{micros:,.1f} µs") for name, micros in found["costs"]),
        ]
        status.value = found["status"]

    def worker():
        """The whole of a pass, off the event loop thread.

        Two Flet rules meet here. `page.run_thread` never retrieves the worker's
        future, so an exception here would vanish with no log, no dialog and no
        crash — hence the bare `except`. And auto-update does not reach a
        background thread, so the explicit `page.update()` is what redraws.
        """
        try:
            refresh()
        except Exception as error:  # noqa: BLE001 - surfaced, since Flet will not
            results.controls = [line("failed", f"{type(error).__name__}: {error}", BAD)]
            status.value = "the pass did not finish"
        finally:
            seal_button.disabled = False
            page.update()

    def start(event=None):
        """Start a pass, unless one is already running.

        The guard is the lock, not the greyed-out button: the passphrase field's
        `on_submit` reaches here whatever the button looks like, and `run_thread`
        submits to a shared pool, so a second call would run alongside the first
        — two Argon2id allocations live at once, both writing these controls.
        """
        if seal_button.disabled:
            return
        seal_button.disabled = True
        status.value = "sealing…"
        results.controls = []
        page.run_thread(worker)

    page.appbar = ft.AppBar(title=ft.Text("pynacl sealed note"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    header := ft.Text(size=11),
                    hint := ft.Text(size=11, visible=False),
                    note := ft.TextField(
                        label="note",
                        value=DEFAULT_NOTE,
                        multiline=True,
                        min_lines=2,
                        max_lines=4,
                        text_size=13,
                        dense=True,
                    ),
                    # A phone keyboard that "helps" produces a different
                    # passphrase, and the only symptom is a CryptoError that
                    # looks as though the note itself is damaged.
                    passphrase := ft.TextField(
                        label="passphrase",
                        value=DEFAULT_PASSPHRASE,
                        password=True,
                        can_reveal_password=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        text_size=13,
                        dense=True,
                        on_submit=start,
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=8,
                        run_spacing=8,
                        controls=[
                            # 0.86 declares `selected` as list[str]; the set the
                            # docstring still describes fails to serialize.
                            level := ft.SegmentedButton(
                                selected=[LEVELS[0][0]],
                                show_selected_icon=False,
                                segments=[
                                    ft.Segment(value=value, label=label)
                                    for value, label in LEVELS
                                ],
                            ),
                            seal_button := ft.Button(
                                "Seal, open, attack",
                                icon=ft.Icons.LOCK,
                                on_click=start,
                            ),
                        ],
                    ),
                    status := ft.Text(size=11, italic=True),
                    results := ft.Column(spacing=2),
                ],
            ),
        )
    )

    header.value = f"{environment()} · {page.platform.value}"
    if IMPORT_ERROR:
        hint.value = (
            f'{IMPORT_ERROR}\nAdd "pynacl" to [project] dependencies — the package '
            "publishes desktop wheels as well as the mobile ones, so one entry "
            "covers `flet run` and `flet build` alike."
        )
        hint.visible = True
        status.value = "nothing to seal without the package"
        seal_button.disabled = True
        level.disabled = True
        return

    start()


if __name__ == "__main__":
    ft.run(main)
