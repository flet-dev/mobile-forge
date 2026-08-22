"""Pick a zstd compression level by measuring it on this device, not by guessing."""

import flet as ft
from levels import HEAVY_LEVEL, LEVELS, RECORDS, build_info, dictionary_sweep, sweep

CODEC_WEIGHTS = (5, 4, 3, 4, 4)

DICT_WEIGHTS = (7, 4, 3, 4)


def table_row(values, weights, size=10):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Sweep the zstd level range on this device and show what each level costs."""

    def show_level():
        """Report the level the next run will use, as the slider moves."""
        level = LEVELS[int(dial.value)]
        caption.value = f"zstd level {level}"
        warning.visible = level >= HEAVY_LEVEL

    def start():
        """Hand one run to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end, which fires once on release, so one
        gesture means one run. The guard is set here rather than in the worker
        because this body is synchronous where `run_thread` only schedules: a
        `disabled` set inside the worker would not have taken effect when Flet
        pushes control states, and a second release would start an overlapping run
        that writes the same cache file.
        """
        if dial.disabled:
            return
        dial.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Measure every codec at the chosen level, then the dictionary comparison.

        Wrapped in try/except because `page.run_thread` discards whatever a worker
        raises — without this, a failure would look like a screen that quietly
        stopped updating. Both tables are cleared on the error path, since numbers
        left over from the previous run read as though they described the error.
        """
        try:
            level = LEVELS[int(dial.value)]
            rows, checks_text, memory_text, stream_text = sweep(level)
            table.controls = [
                table_row(
                    ("codec", "bytes", "ratio", "comp ms", "read ms"), CODEC_WEIGHTS
                ),
                ft.Divider(height=1),
                *(table_row(row, CODEC_WEIGHTS) for row in rows),
            ]
            checks.value = checks_text
            memory.value = memory_text
            stream.value = stream_text

            dict_rows, note_text = dictionary_sweep(level)
            dictionary.controls = [
                table_row(
                    (f"{RECORDS:,} records", "bytes", "ratio", "ms"), DICT_WEIGHTS
                ),
                ft.Divider(height=1),
                *(table_row(row, DICT_WEIGHTS) for row in dict_rows),
            ]
            note.value = note_text
        except Exception as error:
            table.controls = []
            dictionary.controls = []
            checks.value = ""
            stream.value = ""
            note.value = ""
            memory.value = f"{type(error).__name__}: {error}"

        dial.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    build, runtime = build_info(page.platform.value)
    page.appbar = ft.AppBar(title=ft.Text("zstd level lab"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(build, size=11),
                    ft.Text(runtime, size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    dial := ft.Slider(
                        min=0,
                        max=len(LEVELS) - 1,
                        value=4,
                        divisions=len(LEVELS) - 1,
                        on_change=show_level,
                        on_change_end=start,
                    ),
                    warning := ft.Text(
                        "levels 15 and up are background work, not a tap: much more "
                        "memory reserved and much longer to run",
                        size=11,
                        visible=False,
                        color=ft.Colors.ERROR,
                    ),
                    table := ft.Column(spacing=4),
                    checks := ft.Text(size=11),
                    memory := ft.Text(size=11),
                    stream := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("many small records, three ways", size=11),
                    dictionary := ft.Column(spacing=4),
                    note := ft.Text(size=11),
                ],
            ),
        )
    )

    show_level()
    start()


if __name__ == "__main__":
    ft.run(main)
