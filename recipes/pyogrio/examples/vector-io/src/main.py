import flet as ft
from vectors import FIELDS, FORMATS, VERSION, registered_drivers, roundtrip


def row(label, *cells):
    """One line of a table: a label, then a column per value."""
    return ft.Row(
        controls=[
            ft.Text(label, size=12, expand=4),
            *(ft.Text(str(cell), size=12, expand=5) for cell in cells),
        ]
    )


def main(page: ft.Page):
    """Round-trip a point layer through the chosen driver and report on it."""
    state = {"driver": next(iter(FORMATS)), "count": 500}

    def run():
        """Lock the controls and hand the round trip to a background thread."""
        button.disabled = True
        spinner.visible = True
        status.value = ""
        page.update()
        page.run_thread(work)

    def work():
        """Write, read back and fill the table, off the handler that started it.

        The whole body is wrapped. pyogrio raises `DataSourceError` when the
        driver it needs is missing from the table of the extension doing the
        I/O, and an exception escaping here would leave the button disabled
        for good, because `run_thread` never surfaces one.
        """
        try:
            result = roundtrip(state["driver"], state["count"])
            results.controls = [
                row("", "written", "read back"),
                ft.Divider(height=1),
                *(
                    row(f"field {n + 1}", sent, f"{back} · {dtype}")
                    for n, (sent, back, dtype) in enumerate(
                        zip(FIELDS, result["fields"], result["dtypes"])
                    )
                ),
                ft.Divider(height=1),
                row("features", state["count"], result["features"]),
                row("crs", "+proj=longlat", result["crs"][:28]),
                row("worst coordinate error", f"{result['worst_coordinate']:.3g}"),
                row("attribute values wrong", result["wrong_values"]),
                ft.Divider(height=1),
                row("wrote in", f"{result['write_ms']:.0f} ms"),
                row("read in", f"{result['read_ms']:.0f} ms"),
                row("on disk", f"{result['bytes'] / 1000:,.0f} KB"),
                row("files", ", ".join(result["files"])),
            ]
        except Exception as exc:
            results.controls = []
            status.value = f"{type(exc).__name__}: {exc}"
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def on_driver(e):
        """Switch format and re-run; SegmentedButton.selected is a list."""
        state["driver"] = e.control.selected[0]
        run()

    def on_count(e):
        """Re-run at the released slider value, once per drag rather than once
        per pixel travelled."""
        state["count"] = int(e.control.value)
        run()

    page.appbar = ft.AppBar(title=ft.Text("Vector I/O"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=11),
                    ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name))
                            for name in FORMATS
                        ],
                        selected=[state["driver"]],
                        on_change=on_driver,
                    ),
                    ft.Text("Stations written and read back", size=12),
                    ft.Slider(
                        min=100,
                        max=2000,
                        value=state["count"],
                        divisions=19,
                        round=0,
                        label="{value}",
                        on_change_end=on_count,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Round trip", icon=ft.Icons.SYNC_ALT, on_click=run
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    status := ft.Text(size=12, color=ft.Colors.ERROR, selectable=True),
                    results := ft.Column(spacing=4),
                    ft.Divider(),
                    ft.Text("Drivers this GDAL registered", size=12),
                    ft.Column(
                        spacing=2,
                        controls=[row(*pair) for pair in registered_drivers()],
                    ),
                ],
            ),
        )
    )

    run()


if __name__ == "__main__":
    ft.run(main)
