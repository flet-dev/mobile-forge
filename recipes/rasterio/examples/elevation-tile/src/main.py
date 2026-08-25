"""A GeoTIFF written into app storage, read back, and differenced against its source array."""

import flet as ft
from elevation import PROBE, SIZE, epsg_probe, round_trip, versions, window_read


def line(text):
    """One monospaced result line; anything past ~55 characters wraps on a phone."""
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def header_lines():
    """Versions and the driver registry, trimmed to what fits a phone screen."""
    info = versions()
    drivers = info["drivers"]
    extra = f" (+{len(drivers) - 12} more)" if len(drivers) > 12 else ""
    return [
        line(
            f"rasterio {info['rasterio']} - GDAL {info['gdal']} - PROJ {info['proj']}"
        ),
        line(f"{len(drivers)} drivers: {', '.join(drivers[:12])}{extra}"),
    ]


def report_lines(r):
    """Turn one round_trip() result into the labelled lines of the round-trip panel."""
    return [
        line(f"{'driver':<9}{r['driver']}, {r['compress']}"),
        line(f"{'blocks':<9}{r['blocks']} of {r['block_shape']}"),
        line(f"{'size':<9}{r['on_disk']:,} B on disk, {r['in_memory']:,} B as an array"),
        line(f"{'crs':<9}{r['crs']}"),
        line(f"{'':<9}to_epsg {r['epsg']}"),
        line(
            f"{'bounds':<9}{r['bounds'].left:.3f}..{r['bounds'].right:.3f}E, "
            f"{r['bounds'].bottom:.3f}..{r['bounds'].top:.3f}N"
        ),
        line(f"{'lookup':<9}{PROBE[0]}E {PROBE[1]}N -> row {r['row']}, col {r['col']}"),
        line(f"{'':<9}{r['sample']:.4f}, delta vs numpy {r['sample_delta']:.3e}"),
        line(f"{'write':<9}{r['write_ms']:.0f} ms"),
        line(
            f"{'read':<9}{r['read_ms']:.0f} ms - {r['differ']} differ, "
            f"worst {r['worst']:.3e}"
        ),
        line(
            f"{'stats':<9}min {r['stats'].min:.4f}, max {r['stats'].max:.4f}, "
            f"mean {r['stats'].mean:.4f}"
        ),
        line(f"{'':<9}worst delta vs numpy {r['stats_drift']:.3e}"),
    ]


def main(page: ft.Page):
    """Write one GeoTIFF, read it back several ways, and print how far each read disagrees.

    Nothing on screen asserts that rasterio is right: every panel differences what came off
    disk against the numpy array that was written, so the numbers are residuals rather than
    claims.
    """

    def build():
        """Write and read the raster off the UI thread, then fill the round-trip panel.

        Wrapped because `page.run_thread` retrieves no future: an exception here would
        otherwise vanish with no traceback anywhere.
        """
        try:
            report.controls = report_lines(round_trip())
            size.disabled = False
        except Exception as err:
            report.controls = [line(f"{type(err).__name__}: {err}")]
        sample()  # carries the page.update() this worker needs

    def sample():
        """Re-read the centred window at the slider's size and print the residual."""
        try:
            r = window_read(int(size.value))
            readout.value = (
                f"{r['side']}x{r['side']} in {r['ms']:.2f} ms, {r['bytes']:,} B - "
                f"{r['differ']} differ, worst {r['worst']:.3e}"
            )
        except Exception as err:
            readout.value = f"{type(err).__name__}: {err}"
        page.update()  # auto-update does not reach background threads

    def resize():
        """Slider release: re-read at the new window size, off the UI thread."""
        page.run_thread(sample)

    page.appbar = ft.AppBar(title=ft.Text("Elevation tile"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=6,
                controls=[
                    *header_lines(),
                    ft.Divider(),
                    heading(f"{SIZE}x{SIZE} float32 GeoTIFF, written then read back"),
                    report := ft.Column(spacing=6, controls=[line("writing...")]),
                    ft.Divider(),
                    heading("Windowed read"),
                    size := ft.Slider(
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
                    heading("What needs a PROJ database"),
                    line(f"CRS.from_epsg(4326) -> {epsg_probe()}"),
                ],
            ),
        )
    )

    page.run_thread(build)


if __name__ == "__main__":
    ft.run(main)
