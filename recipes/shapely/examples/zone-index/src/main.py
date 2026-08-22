import flet as ft

# `ft.canvas` is a submodule: importing flet does not bind it, so ask for it by name.
from flet import canvas
from zones import LEVELS, measure, projected, report, version_line, workload_label


def outline_path(rings):
    """One part of the merged footprint as a stroked path: its ring, then its holes."""
    elements = []
    for ring in rings:
        elements.append(canvas.Path.MoveTo(*ring[0]))
        elements += [canvas.Path.LineTo(x, y) for x, y in ring[1:]]
        elements.append(canvas.Path.Close())
    return canvas.Path(
        elements=elements,
        paint=ft.Paint(
            style=ft.PaintingStyle.STROKE, stroke_width=1.2, color=ft.Colors.TEAL_400
        ),
    )


def point_cloud(points, colour):
    """Half of the sample — the inside points or the outside ones — as coloured dots."""
    return canvas.Points(points=points, paint=ft.Paint(stroke_width=2.0, color=colour))


def main(page: ft.Page):
    """One slider picks the workload; every figure it produces is checked a second way.

    This file is the app only: `zones` owns the geometry and hands back plain
    numbers, lines of text and screen coordinates.
    """
    result = None
    size = (0.0, 0.0)

    def redraw():
        """Rebuild the canvas from the last result, at the canvas's current size."""
        # One read of `result`, because the worker rebinds it while this may be
        # running: reading it twice could pair one level's points with another's
        # mask, and the mismatched lengths would raise here.
        latest, (width, height) = result, size
        if latest is None or width <= 0 or height <= 0:
            return
        parts, inside, outside = projected(latest, width, height)
        plot.shapes = [outline_path(rings) for rings in parts] + [
            point_cloud(inside, ft.Colors.AMBER_600),
            point_cloud(outside, ft.Colors.BLUE_GREY_400),
        ]

    def on_resize(e):
        """Remember the canvas's pixel size and redraw at it."""
        nonlocal size
        size = (e.width, e.height)
        redraw()

    def run(n_zones, n_points):
        """Measure off the UI thread, fill the readout, redraw, free the slider.

        `page.run_thread` never retrieves the worker's future, so anything raised
        here would vanish without a trace — hence the blanket `except`, which puts
        the failure in the caption instead. The explicit `page.update()` is needed
        for the same reason: auto-update only fires at handler boundaries, and this
        is not one.
        """
        nonlocal result
        try:
            result = measure(n_zones, n_points)
            # Re-state the level from the result, not from the thumb: a release
            # dropped by the guard leaves the two disagreeing, and the numbers are
            # the half that is true.
            caption.value = workload_label(result["zones"], result["points"])
            readout.controls = [ft.Text(line, size=12) for line in report(result)]
            redraw()
        except Exception as error:
            # Six rows and a map from the previous level, left under a fresh
            # error message, read as that error's own output.
            result = None
            readout.controls = []
            plot.shapes = []
            caption.value = f"{type(error).__name__}: {error}"
        finally:
            workload.disabled = False
            page.update()

    def start():
        """Dispatch the run for the level the slider was released on.

        Bound to `on_change_end`, which fires once per gesture: `on_change` fires
        continuously while dragging, and the all-pairs half of this workload is far
        too expensive to run per pixel.

        The guard reads `disabled` back rather than trusting it to have taken
        effect. Disabling the slider only queues the new state for the client, and
        `page.run_thread` submits to a shared pool, so a release arriving in that
        window would put a second worker on the same rows — and the two then leave
        the slider, the caption and the numbers each describing a different level,
        with nothing on screen admitting it.
        """
        if workload.disabled:
            return
        workload.disabled = True
        n_zones, n_points = LEVELS[int(workload.value)]
        page.update()
        page.run_thread(run, n_zones, n_points)

    def preview():
        """Caption the level under the thumb while it is still moving — no computing.

        A preview only: the caption is rewritten from the result once the run lands.
        """
        caption.value = workload_label(*LEVELS[int(workload.value)])

    page.appbar = ft.AppBar(title=ft.Text("shapely zone index"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        version_line(page.platform.value), size=11, selectable=True
                    ),
                    caption := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    workload := ft.Slider(
                        value=len(LEVELS) - 1,
                        min=0,
                        max=len(LEVELS) - 1,
                        divisions=len(LEVELS) - 1,
                        on_change=preview,
                        on_change_end=start,
                    ),
                    readout := ft.Column(),
                    ft.Container(
                        height=300,
                        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                        border_radius=8,
                        content=(
                            plot := canvas.Canvas(expand=True, on_resize=on_resize)
                        ),
                    ),
                ],
            ),
        )
    )

    preview()
    start()


if __name__ == "__main__":
    ft.run(main)
