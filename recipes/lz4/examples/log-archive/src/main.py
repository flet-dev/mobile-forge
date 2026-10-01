import flet as ft
import lz4
from logs import LEVELS, archive, sample_log


def main(page: ft.Page):
    """Wire the level buttons to a background archive-and-verify of a generated log."""

    def run(label):
        """Archive the log at one compression level off the UI thread."""

        def work():
            """Write, read back and verify, then refill the report from the worker."""
            spinner.visible = True
            page.update()
            try:
                a = archive(sample_log(), LEVELS[label])
                headline.value = (
                    f"{label}: {a.raw / 1e6:.1f} MB → {a.packed / 1e6:.2f} MB "
                    f"({a.raw / a.packed:.1f}x)"
                )
                detail.value = (
                    f"write {a.write_s * 1e3:.0f} ms ({a.raw / a.write_s / 1e6:.0f} MB/s)\n"
                    f"read {a.read_s * 1e3:.0f} ms ({a.raw / a.read_s / 1e6:.0f} MB/s)\n"
                    f"round trip {'intact' if a.intact else 'CORRUPTED'}"
                )
                where.value = a.path
            except Exception as e:
                headline.value = f"{label} failed"
                detail.value = repr(e)
            spinner.visible = False
            page.update()  # auto-update does not reach background threads

        # lz4 releases the GIL while it compresses, so this genuinely runs in parallel.
        page.run_thread(work)

    spinner = ft.ProgressRing(visible=False, width=18, height=18)
    headline = ft.Text("Pick a level", size=18, weight=ft.FontWeight.BOLD)
    detail = ft.Text("")
    where = ft.Text("", size=11, selectable=True)

    page.appbar = ft.AppBar(title=ft.Text("Archive a log"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Button(label, on_click=lambda _, l=label: run(l))
                            for label in LEVELS
                        ],
                        wrap=True,
                    ),
                    ft.Row(controls=[headline, spinner]),
                    detail,
                    where,
                    ft.Divider(),
                    ft.Text(f"liblz4 {lz4.library_version_string()}", size=11),
                ],
            ),
        )
    )


ft.run(main)
