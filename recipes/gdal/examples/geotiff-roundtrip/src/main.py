import flet as ft
from terrain import (
    IMPORT_ERROR,
    SIZE,
    exception_modes,
    footprint,
    numpy_rows,
    registry,
    roundtrip,
    spatial_rows,
    vector_rows,
    versions,
    window_read,
)


def line(text):
    """One monospaced result row; much past ~55 characters wraps on a phone."""
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def unavailable(reason):
    """The whole screen when osgeo did not import, which is every run off a device.

    gdal is declared under [tool.flet.android]/[tool.flet.ios] because it has no desktop
    wheel, so a `flet run` or a web build never sees it.
    """
    return ft.SafeArea(
        expand=True,
        content=ft.Card(
            content=ft.Container(
                padding=16,
                content=ft.Text(
                    f"osgeo is not importable here — {reason}.\n\n"
                    "That is expected off-device: the gdal wheel exists only for Android "
                    "and iOS on pypi.flet.dev, and upstream publishes no desktop wheel, "
                    "so this app declares it under [tool.flet.android] and "
                    "[tool.flet.ios] rather than in [project] dependencies."
                ),
            )
        ),
    )


def main(page: ft.Page):
    """Write one GeoTIFF, read it back, and print how far each read disagrees with its source.

    Nothing on screen asserts that GDAL is right. Every row is either a difference against
    the reference surface or the exception the call raised, rendered with its class and
    message — an unhandled exception in a Flet handler ends the session with a crash screen.
    """
    page.appbar = ft.AppBar(title=ft.Text("GeoTIFF round trip"), center_title=True)

    if IMPORT_ERROR is not None:
        page.add(unavailable(IMPORT_ERROR))
        return

    def fill(column, work):
        """Run one panel and put either its rows or its exception into the column."""
        try:
            column.controls = [line(text) for text in work()]
        except Exception as err:
            column.controls = [line(f"{type(err).__name__}: {err}"[:220])]

    def sample():
        """Re-read at the slider's window size and put the result in the readout."""
        try:
            readout.value = window_read(int(window.value))
        except Exception as err:
            readout.value = f"{type(err).__name__}: {err}"[:180]
        page.update()  # auto-update does not reach background threads

    def resize():
        """Hand the re-read to a pool thread so the slider handler returns at once."""
        page.run_thread(sample)

    def build():
        """Fill every panel off the UI thread, in the one order that works.

        exception_modes() has to run first: it owns the only gdal.Open made before
        gdal.UseExceptions(), and the FutureWarning it captures fires once per process.
        Everything after it therefore raises on failure instead of returning None.
        """
        fill(modes, exception_modes)
        fill(drivers, registry)
        fill(raster, roundtrip)
        fill(arrays, numpy_rows)
        fill(spatial, spatial_rows)
        fill(vectors, vector_rows)
        count, total = footprint()
        loaded.value = f"after UseExceptions {count}/6, {total:,} B"
        window.disabled = False
        sample()  # carries the page.update() this worker owes

    def version_row():
        """The version strings, guarded: this one runs while page.add() is still building."""
        try:
            text = versions()
        except Exception as err:
            text = f"{type(err).__name__}: {err}"[:160]
        return line(f"{text} - {page.platform.value}")

    imported, bytes_in = footprint()
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=6,
                controls=[
                    version_row(),
                    line(f"import mapped {imported}/6, {bytes_in:,} B"),
                    loaded := line("after UseExceptions ..."),
                    ft.Divider(),
                    heading(f"{SIZE}x{SIZE} float32 GeoTIFF, all of it inside _gdal"),
                    raster := ft.Column(spacing=6, controls=[line("writing...")]),
                    ft.Divider(),
                    heading("Windowed read"),
                    window := ft.Slider(
                        min=64,
                        max=512,
                        divisions=7,
                        value=256,
                        label="{value} px",
                        disabled=True,
                        on_change_end=resize,
                    ),
                    readout := line("waiting for the file..."),
                    ft.Divider(),
                    heading("Into _gdal_array"),
                    arrays := ft.Column(spacing=6),
                    heading("Into _osr"),
                    spatial := ft.Column(spacing=6),
                    heading("Into _ogr"),
                    vectors := ft.Column(spacing=6),
                    ft.Divider(),
                    heading("Driver registries"),
                    drivers := ft.Column(spacing=6),
                    heading("Exception mode"),
                    modes := ft.Column(spacing=6),
                ],
            ),
        )
    )

    page.run_thread(build)


if __name__ == "__main__":
    ft.run(main)
