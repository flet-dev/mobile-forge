import threading

import flet as ft
from logs import LEVELS, archive, library_version, sample_log


def main(page: ft.Page):
    busy = threading.Lock()

    def run(name):
        """Lock the levels, raise the spinner, and hand one archive run to a thread."""
        # Every level writes the same file. Disabling the buttons is not enough on
        # its own: a second tap already in flight lands before the patch does.
        if not busy.acquire(blocking=False):
            return
        levels.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(lambda: work(name))

    def work(name):
        """Write, read back and verify at one level, then refill the report.

        run_thread swallows exceptions and does not carry an automatic update
        with it, so this catches its own failures and ends with page.update().
        """
        try:
            a = archive(sample_log(), LEVELS[name])
            headline.value = (
                f"{name}: {a.raw / 1e6:.1f} MB → {a.packed / 1e6:.2f} MB "
                f"({a.raw / a.packed:.1f}x)"
            )
            detail.value = (
                f"write {a.write_s * 1e3:.0f} ms ({a.raw / a.write_s / 1e6:.0f} MB/s)\n"
                f"read {a.read_s * 1e3:.0f} ms ({a.raw / a.read_s / 1e6:.0f} MB/s)\n"
                f"round trip {'intact' if a.intact else 'CORRUPTED'}"
            )
            where.value = a.path
        except Exception as exc:
            headline.value = f"{name} failed"
            detail.value = repr(exc)
            where.value = ""
        levels.disabled = False
        spinner.visible = False
        page.update()
        busy.release()

    page.appbar = ft.AppBar(title=ft.Text("Archive a log"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    levels := ft.Row(
                        wrap=True,
                        controls=[
                            ft.Button(name, on_click=lambda _, n=name: run(n))
                            for name in LEVELS
                        ],
                    ),
                    ft.Row(
                        controls=[
                            headline := ft.Text(
                                "Pick a level", size=18, weight=ft.FontWeight.BOLD
                            ),
                            spinner := ft.ProgressRing(
                                visible=False, width=18, height=18
                            ),
                        ]
                    ),
                    detail := ft.Text(""),
                    where := ft.Text("", size=11, selectable=True),
                    ft.Divider(),
                    ft.Text(f"liblz4 {library_version()}", size=11),
                ],
            ),
        )
    )


ft.run(main)
