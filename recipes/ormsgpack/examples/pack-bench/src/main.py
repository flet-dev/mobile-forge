import flet as ft
from packing import SIZES, VERSIONS, compare, round_trips


def line(label, *cells):
    """One line of the timing table: a label, then a column per value."""
    return ft.Row(
        controls=[
            ft.Text(label, size=12, expand=3),
            *(ft.Text(cell, size=12, expand=2) for cell in cells),
        ]
    )


def trip(label, sent, got, size, note):
    """One round-trip card: what went in, what came back, and the byte count."""
    return ft.Column(
        spacing=1,
        controls=[
            ft.Row(
                controls=[
                    ft.Text(label, size=12, weight=ft.FontWeight.BOLD, expand=True),
                    ft.Text(f"{size} B", size=11),
                ]
            ),
            ft.Text(f"in   {sent}", size=11, font_family="monospace"),
            ft.Text(f"out  {got!r}", size=11, font_family="monospace"),
            ft.Text(note, size=11, color=ft.Colors.PRIMARY),
        ],
    )


def main(page: ft.Page):
    state = {"records": SIZES[1]}

    def run():
        """Lock the controls and hand the benchmark to a background thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Time both libraries on the same payload, then show what a trip costs.

        The two byte counts are the point of the table: on this payload they
        match exactly, so nothing here is an argument about wire size. The clock
        is where the two differ, and the ratios below say by how much on this
        device — pack decisively, unpack barely.
        """
        result = compare(state["records"])
        table.controls = [
            line("", "ormsgpack", "msgpack"),
            ft.Divider(height=1),
            line(
                "pack",
                f"{result['orm_pack']:.2f} ms",
                f"{result['msgpack_pack']:.2f} ms",
            ),
            line(
                "unpack",
                f"{result['orm_unpack']:.2f} ms",
                f"{result['msgpack_unpack']:.2f} ms",
            ),
            line("bytes", f"{result['orm_bytes']:,}", f"{result['msgpack_bytes']:,}"),
            line("identical", "yes" if result["identical"] else "no"),
        ]
        summary.value = (
            f"ormsgpack packs at {result['msgpack_pack'] / result['orm_pack']:.2f}× "
            f"and unpacks at {result['msgpack_unpack'] / result['orm_unpack']:.2f}× "
            "msgpack's speed here"
        )
        trips.controls = [trip(*row) for row in round_trips()]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def on_size(e):
        """Switch payload size and re-run; SegmentedButton.selected is a list."""
        state["records"] = int(e.control.selected[0])
        run()

    page.appbar = ft.AppBar(title=ft.Text("pack-bench"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSIONS, size=11),
                    ft.Text("Records packed on each run", size=12),
                    ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=str(size), label=ft.Text(f"{size:,}"))
                            for size in SIZES
                        ],
                        selected=[str(SIZES[1])],
                        on_change=on_size,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Run again", icon=ft.Icons.SPEED, on_click=run
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    table := ft.Column(spacing=4),
                    summary := ft.Text(size=11, color=ft.Colors.PRIMARY),
                    ft.Divider(),
                    ft.Text("What comes back", size=13, weight=ft.FontWeight.BOLD),
                    trips := ft.Column(spacing=12),
                ],
            ),
        )
    )

    run()


if __name__ == "__main__":
    ft.run(main)
