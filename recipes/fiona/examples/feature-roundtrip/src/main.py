import flet as ft
from vectors import (
    IMPORT_ERROR,
    START_COUNT,
    build_lines,
    crs_lines,
    registry_lines,
    roundtrip_lines,
    transform_lines,
)


def line(text):
    """One monospaced result line; anything past ~55 characters wraps on a phone."""
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def main(page: ft.Page):
    """Print what this build of fiona can do, then write, read and difference layers."""

    def render(count):
        """Refill the results column from a fresh set of probes.

        The registry comes immediately before the round trip on purpose: on iOS the
        first is a green light from a driver table the second never consults.
        """
        sections = (
            ("Build", build_lines(page.platform.value)),
            ("Registry (fiona.Env)", registry_lines()),
            (
                f"Round trip (fiona.open), {count} features/layer",
                roundtrip_lines(count),
            ),
            ("CRS", crs_lines()),
            ("fiona.transform", transform_lines()),
        )
        results.controls = [
            control
            for title, lines in sections
            for control in (heading(title), *(line(text) for text in lines))
        ]

    def worker():
        """Recompute and repaint; run_thread swallows errors and never auto-updates."""
        try:
            render(int(features.value))
        except Exception as err:
            results.controls = [line(f"  FAILED  {type(err).__name__}: {err}")]
        finally:
            features.disabled = False
            page.update()

    def rerun():
        """Run the probes off the thread pool, since 2000 features is not instant.

        Also the first run, called once below: `import fiona` has already mapped every
        extension by then, and on iOS `transform_lines` maps another one, so doing the
        opening pass on the UI thread would hold the first paint behind it.

        The guard reads `disabled` back rather than trusting it to have taken effect.
        Disabling the slider only queues the new state for the client, and
        `page.run_thread` submits to a shared pool, so a release arriving in that window
        would put a second worker on the same four layer directories — which each clear
        themselves before writing. Overlapping runs then report `FileExistsError`,
        `FileNotFoundError` and `DriverError: Failed to create GeoJSON datasource`,
        putting fiona's name on a fault that belongs to this app.
        """
        if features.disabled:
            return
        features.disabled = True
        results.controls = [line("working...")]
        page.update()
        page.run_thread(worker)

    page.appbar = ft.AppBar(title=ft.Text("fiona round trip"), center_title=True)

    if IMPORT_ERROR is not None:
        page.add(
            ft.SafeArea(
                expand=True,
                content=ft.Column(
                    [
                        heading("fiona is not installed here"),
                        line(IMPORT_ERROR),
                        line("It is declared under [tool.flet.android] and"),
                        line("[tool.flet.ios], so only an apk/ipa build carries it."),
                    ]
                ),
            )
        )
        return

    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                [
                    features := ft.Slider(
                        min=10,
                        max=2000,
                        divisions=199,
                        value=START_COUNT,
                        label="{value} features",
                        # on_change would re-run every layer for each pixel the thumb
                        # travels; on_change_end runs them once, on release.
                        on_change_end=rerun,
                    ),
                    results := ft.Column(
                        spacing=2, expand=True, scroll=ft.ScrollMode.AUTO
                    ),
                ],
                expand=True,
            ),
        )
    )
    rerun()


if __name__ == "__main__":
    ft.run(main)
