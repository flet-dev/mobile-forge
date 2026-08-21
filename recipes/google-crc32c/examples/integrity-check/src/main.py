import flet as ft
from integrity import (
    BLOB_MB,
    CHUNK,
    CHUNKS,
    ENGINE,
    cloud_header,
    compare,
    damage,
    store,
    stored,
    verify,
)


def line(label, *cells):
    """One row of the results table: a label, then a column per value."""
    return ft.Row(
        controls=[
            ft.Text(label, expand=3, size=12),
            *(ft.Text(cell, expand=2, size=12) for cell in cells),
        ]
    )


def table(whole, elapsed):
    """The four-way digest comparison, plus two facts about the stored blob."""
    return [
        line("", "digest", "MB/s"),
        ft.Divider(height=1),
        *(line(name, value, f"{rate:,.0f}") for name, value, rate in compare()),
        ft.Divider(height=1),
        line("checksummed in", f"{elapsed * 1e3:.0f} ms", f"{CHUNKS} chunks"),
        line("x-goog-hash", cloud_header(whole)),
    ]


def main(page: ft.Page):
    """Store a blob under its CRC32C, damage it, and catch the damage."""

    def run(job):
        """Lock the buttons, raise the spinner, hand `job` to a worker thread.

        page.run_thread neither auto-updates the page nor surfaces exceptions,
        so the worker owns the try/except and every path out of it ends in
        finish(), which is the only place page.update() is called.
        """

        def worker():
            """Run `job` and land whatever it produces — result or error — on screen."""
            try:
                finish(*job())
            except Exception as error:
                finish(str(error), ft.Colors.ERROR)

        for button in buttons:
            button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(worker)

    def finish(message, colour=None):
        """Land a worker's result on screen and unlock the buttons."""
        status.value = message
        status.color = colour
        for button in buttons:
            button.disabled = False
        spinner.visible = False
        page.update()

    def write_blob():
        """Write a fresh blob, record its per-chunk checksums, fill the table."""
        whole, elapsed = store()
        report.controls = table(whole, elapsed)
        return f"Stored {BLOB_MB} MB in {CHUNKS} chunks.", None

    def flip_bit():
        """Corrupt the stored blob by one bit and say where it landed."""
        offset, chunk = damage()
        return f"Flipped one bit at byte {offset:,}, in chunk {chunk}.", None

    def check():
        """Re-checksum the blob and name the chunk that stopped matching."""
        bad, whole, elapsed = verify()
        report.controls = table(whole, elapsed)
        if not bad:
            return f"Intact: all {CHUNKS} chunks match.", ft.Colors.PRIMARY
        first = bad[0]
        span = f"{first * CHUNK:,} to {(first + 1) * CHUNK:,}"
        return f"Corrupt: chunk {first} failed, bytes {span}.", ft.Colors.ERROR

    status = ft.Text(expand=True, size=13)
    spinner = ft.ProgressRing(width=16, height=16, visible=False)
    report = ft.Column(spacing=4)
    buttons = [
        ft.Button("Store", icon=ft.Icons.SAVE, on_click=lambda: run(write_blob)),
        ft.Button("Damage", icon=ft.Icons.BOLT, on_click=lambda: run(flip_bit)),
        ft.Button("Verify", icon=ft.Icons.FACT_CHECK, on_click=lambda: run(check)),
    ]

    page.appbar = ft.AppBar(title=ft.Text("Integrity check"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(ENGINE, size=11),
                    ft.Row(controls=[status, spinner]),
                    ft.Row(wrap=True, controls=buttons),
                    report,
                ],
            ),
        )
    )

    if stored():
        run(check)
    else:
        finish(f"Tap Store to write a fresh {BLOB_MB} MB blob.")


if __name__ == "__main__":
    ft.run(main)
