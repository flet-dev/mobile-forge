import flet as ft
from sandbox import (
    FAILED,
    IMPORT_ERROR,
    OK,
    SIZES,
    SOFT,
    environment,
    measure,
    summary,
    survey,
)

DOT = {OK: ft.Colors.GREEN, SOFT: ft.Colors.AMBER, FAILED: ft.Colors.RED}


def result(index, label, state, answer, cross):
    """One result row: an outcome dot, the call, its answer, and its cross-check.

    Amber is not a paler green. A call that returned `None`, or that degraded to a
    warning and an invented number, is a different outcome from one that answered,
    and a two-colour dot would let it pass for success.
    """
    return ft.Column(
        spacing=1,
        controls=[
            ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CIRCLE, size=9, color=DOT[state]),
                    ft.Text(f"{index}. {label}", size=11, expand=True),
                ]
            ),
            ft.Text(answer, size=10),
            *([ft.Text(cross, size=10, italic=True)] if cross else []),
        ],
    )


def main(page: ft.Page):
    """Probe the sandbox once at startup, then let a slider move one number.

    Both passes run synchronously — the probe costs about the 0.3 s `cpu_percent`
    spends sampling, the allocation rather less — so none of `page.run_thread`'s
    exception-swallowing applies and two runs of either cannot overlap.
    """

    def show_size():
        """Report the allocation the next release of the slider will make."""
        caption.value = f"allocate {SIZES[int(size.value)]} MB and watch RSS"

    def allocate():
        """Allocate, measure, release, and print the three RSS readings.

        Driven by the slider's `on_change_end`, which fires once when the finger
        lifts, so one gesture is one allocation.
        """
        megabytes = SIZES[int(size.value)]
        try:
            wanted, before, held, freed = measure(megabytes)
        except Exception as error:
            memory.controls = [ft.Text(f"{type(error).__name__}: {error}", size=11)]
            return
        memory.controls = [
            ft.Text(f"requested {wanted:,} B ({megabytes} MB)", size=11),
            ft.Text(f"RSS before      {before:,} B", size=11),
            ft.Text(f"RSS holding it  {held:,} B  ({held - before:+,} B)", size=11),
            ft.Text(f"RSS after `del` {freed:,} B  ({freed - held:+,} B)", size=11),
            ft.Text(
                f"kept {held - before:,} B of the {wanted:,} B asked for, "
                f"returned {held - freed:,} B",
                size=11,
            ),
        ]

    def probe():
        """Fill the table from one pass of the probe list, or explain the absence.

        With psutil missing the screen still starts: it states the import error,
        says why psutil is not there and disables the slider, because that guarded
        path is the one every iOS build and every desktop `flet run` takes.
        """
        if IMPORT_ERROR:
            note.value = (
                f"{IMPORT_ERROR}\npsutil is declared under [tool.flet.android] "
                "dependencies, so it reaches an Android build only — no iOS wheel "
                "is published, and a desktop run does not install it either."
            )
            note.visible = True
            header.value = f"{environment()} · {page.platform.value}"
            caption.value = "the allocation probe needs psutil"
            size.disabled = True
            return
        answers = survey()
        rows.controls = [
            result(index, *row) for index, row in enumerate(answers, start=1)
        ]
        header.value = f"{environment()} · {page.platform.value} · {summary(answers)}"

    page.appbar = ft.AppBar(title=ft.Text("psutil sandbox probe"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    header := ft.Text(size=11),
                    note := ft.Text(size=11, visible=False),
                    rows := ft.Column(spacing=6),
                    ft.Divider(),
                    caption := ft.Text(size=11),
                    size := ft.Slider(
                        min=0,
                        max=len(SIZES) - 1,
                        value=2,
                        divisions=len(SIZES) - 1,
                        on_change=show_size,
                        on_change_end=allocate,
                    ),
                    memory := ft.Column(spacing=2),
                ],
            ),
        )
    )

    show_size()
    probe()


if __name__ == "__main__":
    ft.run(main)
