"""Run jq programs against a bundled JSON document, on this device."""

import platform

import flet as ft
from queries import (
    IMPORT_ERROR,
    PRESETS,
    compare,
    library_line,
    render,
    run_jq,
    twin_only,
)


def main(page: ft.Page):
    """A jq console: pick or type a program, run it, see what it answered.

    Each preset ships with a hand-written Python function that computes the same
    thing, so the status line can report both timings and whether the two agree
    — the claim the app exists to make checkable. Without the wheel it degrades
    to running only the Python twins and says what the import raised.
    """

    def choose(preset):
        """Load a preset into the editable field and run it."""
        name, program, _ = preset
        query.value = program
        run_now(name)

    def show(state, output, comparison_text="", failed=False):
        """Put one run's three lines on screen and push them to the client."""
        status.value = state
        result.value = output
        result.color = ft.Colors.ERROR if failed else None
        comparison.value = comparison_text
        page.update()

    def run_now(name=""):
        """Run whatever is in the field, next to the twin if this is a preset.

        Runs inline rather than in
        [`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread):
        jq holds the GIL for the whole call, so a worker thread would neither run
        in parallel nor let anything else make progress while it worked.

        Every failure path lands in the one `try` on purpose. A bad program is a
        `ValueError` from `jq.compile`, bad data is a `ValueError` from the
        iterator, and an unhandled exception in a Flet handler ends the session
        with a crash screen — so the message goes on screen instead.
        """
        program = (query.value or "").strip()
        if not program:
            show("type a jq program, or pick one above", "")
            return
        try:
            if IMPORT_ERROR:
                show(*twin_only(name))
                return
            values, compile_ms, run_ms = run_jq(program)
        except Exception as error:  # jq reports bad programs and bad data alike
            show(type(error).__name__, str(error), failed=True)
            return
        show(
            f"{len(values)} output value{'' if len(values) == 1 else 's'} — "
            f"compiled in {compile_ms:.2f} ms, ran in {run_ms:.1f} ms",
            render(values),
            compare(name, values),
        )

    page.appbar = ft.AppBar(title=ft.Text("jq query console"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        library_line(),
                        size=11,
                        color=ft.Colors.ERROR if IMPORT_ERROR else None,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} — {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        scroll=ft.ScrollMode.AUTO,  # a plain Row overflows on a phone
                        controls=[
                            ft.Button(
                                preset[0],
                                on_click=lambda _, p=preset: choose(p),
                            )
                            for preset in PRESETS
                        ],
                    ),
                    query := ft.TextField(
                        label="jq program",
                        multiline=True,
                        min_lines=4,
                        max_lines=8,
                        text_size=12,
                        autocorrect=False,  # a keyboard "fixing" .[] breaks the query
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        keyboard_type=ft.KeyboardType.MULTILINE,
                    ),
                    ft.Row(
                        controls=[
                            ft.FilledButton("Run", on_click=lambda _: run_now()),
                            status := ft.Text(size=11, expand=True),
                        ]
                    ),
                    result := ft.Text(size=11, selectable=True, font_family="monospace"),
                    ft.Divider(),
                    comparison := ft.Text(size=11),
                ],
            ),
        )
    )

    choose(PRESETS[0])


if __name__ == "__main__":
    ft.run(main)
