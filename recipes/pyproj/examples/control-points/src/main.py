import coordinates
import flet as ft


def line(text):
    """One monospaced result line.

    `coordinates` formats its rows to 50 columns because at this size a phone wraps a
    little past that, and a wrapped column-aligned table is unreadable. `monospace` is a
    generic family name; `Courier` backs it up on platforms that do not map it.
    """
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def main(page: ft.Page):
    """Four panels of coordinate maths, each printing its own disagreement with a check.

    Nothing here asserts that pyproj is right: every projected coordinate is differenced
    against arithmetic done in `coordinates.py`. The numbers on screen are the residuals,
    in millimetres.
    """

    def measure(count):
        """Run the vectorised round trip and show its timings.

        Runs in the thread pool because 200k points is long enough to drop frames.
        `benchmark` returns its own errors as text, which matters here: `run_thread`
        never retrieves the worker's future, so a raised exception would vanish.
        """
        timing.value = coordinates.benchmark(count)
        page.update()  # auto-update does not reach background threads

    def resize():
        """Re-run the benchmark at the slider's new size, off the UI thread."""
        page.run_thread(measure, int(size.value))

    page.appbar = ft.AppBar(title=ft.Text("Control points"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=6,
                controls=[
                    line(coordinates.version_line()),
                    line(coordinates.data_dir_line()),
                    line(coordinates.network_line()),
                    ft.Divider(),
                    heading("Geodesics on the ellipsoid (no data needed)"),
                    *(line(row) for row in coordinates.geodesy_rows()),
                    ft.Divider(),
                    heading("Projections from proj-strings (empty proj.db)"),
                    *(line(row) for row in coordinates.projection_rows()),
                    ft.Divider(),
                    heading("Axis order"),
                    *(line(row) for row in coordinates.axis_rows()),
                    ft.Divider(),
                    heading("What needs the real database"),
                    line(coordinates.epsg_row()),
                    ft.Divider(),
                    heading("Vectorised round trip"),
                    size := ft.Slider(
                        min=10000,
                        max=200000,
                        divisions=19,
                        value=50000,
                        label="{value} points",
                        on_change_end=resize,
                    ),
                    timing := line("measuring..."),
                ],
            ),
        )
    )

    resize()


if __name__ == "__main__":
    ft.run(main)
