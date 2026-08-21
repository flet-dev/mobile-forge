import flet as ft
from tiles import CAPACITIES, GRID, HEADLINE, TILE, TileCache, compare, frame, step


def row(label, *cells):
    """One line of a results table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    """Wire the tile grid, the pan pad and the two result tables to one LRU."""
    cache = TileCache(CAPACITIES[1])
    at = [0, 1, 1]  # zoom, origin x, origin y
    tiles = [
        [
            ft.Image(src=b"", width=TILE, height=TILE, gapless_playback=True)
            for _ in range(GRID)
        ]
        for _ in range(GRID)
    ]

    def draw():
        """Lock the controls and hand the frame to a background thread."""
        for control in (pad, capacity, timer):
            control.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(render)

    def render():
        """Draw the nine visible tiles and report what the cache did for them.

        Every miss here is a Mandelbrot tile rendered in pure Python, so the hit
        count and the elapsed time tell the same story twice.
        """
        pngs, hits, elapsed = frame(cache, *at)
        for controls, images in zip(tiles, pngs):
            for control, png in zip(controls, images):
                control.src = png
        stats.controls = [row(*cells) for cells in cache.report(hits, elapsed)]
        for control in (pad, capacity, timer):
            control.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def move(dx, dy, dz=0):
        """Build a pan or zoom handler for one direction."""

        def handler(e):
            """Apply the step to the shared position and redraw."""
            at[:] = step(*at, dx, dy, dz)
            draw()

        return handler

    def on_capacity(e):
        """Resize the live cache, evicting from the cold end down to the new bound."""
        cache.resize(int(e.control.selected[0]))
        draw()

    def on_timer(e):
        """Time the three ready-made LRU caches on this device, not on a laptop."""
        timer.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(measure)

    def measure():
        """Fill the comparison table from a run on the hardware the app is on."""
        bench.controls = [
            row("", "hit", "insert"),
            ft.Divider(height=1),
            *(row(n, f"{h:.0f} ns", f"{m:.0f} ns") for n, h, m in compare()),
        ]
        timer.disabled = False
        spinner.visible = False
        page.update()

    def icon(name, handler):
        """A pad button; the whole pad is disabled together while a frame renders."""
        return ft.IconButton(icon=name, on_click=handler)

    page.appbar = ft.AppBar(title=ft.Text("LRU tile cache"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(HEADLINE, size=12),
                    ft.Column(
                        spacing=0,
                        controls=[ft.Row(controls=r, spacing=0) for r in tiles],
                    ),
                    pad := ft.Row(
                        controls=[
                            icon(ft.Icons.CHEVRON_LEFT, move(-1, 0)),
                            icon(ft.Icons.EXPAND_LESS, move(0, -1)),
                            icon(ft.Icons.EXPAND_MORE, move(0, 1)),
                            icon(ft.Icons.CHEVRON_RIGHT, move(1, 0)),
                            icon(ft.Icons.ZOOM_IN, move(0, 0, 1)),
                            icon(ft.Icons.ZOOM_OUT, move(0, 0, -1)),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    ft.Text("Tiles the cache may hold", size=12),
                    capacity := ft.SegmentedButton(
                        # Flet 0.86 takes a list of the string values, not a set.
                        selected=[str(CAPACITIES[1])],
                        segments=[
                            ft.Segment(value=str(c), label=ft.Text(str(c)))
                            for c in CAPACITIES
                        ],
                        on_change=on_capacity,
                    ),
                    stats := ft.Column(spacing=4),
                    ft.Divider(),
                    timer := ft.Button(
                        "Time three caches", icon=ft.Icons.TIMER, on_click=on_timer
                    ),
                    bench := ft.Column(spacing=4),
                ],
            ),
        )
    )

    draw()


if __name__ == "__main__":
    ft.run(main)
