import flet as ft
from store import (
    NAME,
    VERSION,
    append,
    documents,
    fidelity,
    reading,
    seed,
    size,
    summary,
    throughput,
)

WEIGHTS = (3, 3, 3, 2, 2)


def line(*values):
    """One table line: a Text per value, sized by the shared column weights."""
    return ft.Row(
        controls=[ft.Text(str(v), size=11, expand=w) for v, w in zip(values, WEIGHTS)]
    )


def main(page: ft.Page):
    """Three panels over one store file: its contents, its types, its speed.

    Nothing is computed on the UI thread, and the first screen is a real one:
    the store seeds itself on the first run.
    """

    def start(target):
        """Lock the button, raise the spinner, and run `target` off the UI thread.

        The guard matters because run_thread swallows what the worker raises,
        and a store torn by a kill mid-write stays torn: one escaping error
        would leave the button disabled and the spinner turning for good.
        """

        def guarded():
            try:
                target()
            except Exception as error:
                note.value = f"{type(error).__name__}: {error}"
            finally:
                button.disabled = False
                spinner.visible = False
                page.update()  # auto-update does not reach background threads

        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(guarded)

    def rebuild():
        """Re-read the store from disk and refill every panel."""
        seed()
        docs, whole = documents()
        stats.value = f"{len(docs)} documents · {size()} bytes · {NAME}"
        note.value = "" if whole else "torn tail: the walk kept everything before it"
        entries.controls = [line(*row) for row in summary(docs)]
        table.controls = [
            line("field", "python", "back", "same", "json"),
            ft.Divider(height=1),
            *(line(*row) for row in fidelity()),
        ]
        count, encoding, decoding, average = throughput()
        speed.value = (
            f"{count} documents of {average:.0f} bytes: "
            f"encode {encoding:.1f} µs each, decode {decoding:.1f} µs each"
        )

    def add():
        """Append one more reading on the worker thread, then rebuild."""
        append(reading())
        rebuild()

    page.appbar = ft.AppBar(title=ft.Text("BSON store"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    ft.Text("Stored on this device", weight=ft.FontWeight.BOLD),
                    stats := ft.Text(size=12),
                    note := ft.Text(size=11, color=ft.Colors.ERROR),
                    entries := ft.Column(spacing=2),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Add reading",
                                icon=ft.Icons.ADD,
                                on_click=lambda: start(add),
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    ft.Divider(),
                    ft.Text("What survives the round trip", weight=ft.FontWeight.BOLD),
                    table := ft.Column(spacing=2),
                    ft.Text(
                        "json refuses four of these outright, and takes Int64 only "
                        "because it subclasses int.",
                        size=11,
                        color=ft.Colors.OUTLINE,
                    ),
                    ft.Divider(),
                    ft.Text("Throughput", weight=ft.FontWeight.BOLD),
                    speed := ft.Text(size=12),
                ],
            ),
        )
    )

    start(rebuild)


if __name__ == "__main__":
    ft.run(main)
