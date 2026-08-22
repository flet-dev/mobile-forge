"""Freeze this device's clock and see which readings follow and which do not."""

import asyncio
import platform

import clocks
import flet as ft

REFRESH_S = 0.25
ROW_WEIGHTS = (7, 8, 4)


def table_row(values, weight=None):
    """One table row: a `Text` per value, laid out by the shared column weights."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, weight=weight, expand=column)
            for value, column in zip(values, ROW_WEIGHTS)
        ]
    )


def face(label, reading):
    """One clock face: a small caption above a large reading."""
    caption = ft.Text(label, size=11)
    return ft.Column(expand=True, spacing=0, controls=[caption, reading])


def main(page: ft.Page):
    """Drive a trip from the UI and show what the device's clocks say during it.

    When `time_machine` is missing the app still works - the probe table reads the
    real clock and the header says what the import raised - because a crash screen
    would teach nothing.
    """

    def refresh():
        """Re-run the probe sweep and repaint the table, the verdict and the buttons."""
        rows, totals = clocks.sweep()
        table.controls = [
            table_row(("reading", "value (UTC)", "verdict"), weight=ft.FontWeight.BOLD),
            ft.Divider(height=1),
            *(table_row(row) for row in rows),
        ]
        live = clocks.travelling()
        verdict.value = clocks.summarise(totals, live)
        verdict.color = ft.Colors.TERTIARY if live else None
        travel_button.content = "Return" if live else "Travel"
        travel_button.icon = ft.Icons.HISTORY if live else ft.Icons.PLAY_ARROW
        travel_button.disabled = not clocks.AVAILABLE
        shift_button.disabled = not live
        why.value = clocks.WHY[picker.selected[0]]

    def guard(work):
        """Run a handler body, turning any failure into a status line.

        An exception escaping a Flet event handler ends the session with a crash
        screen, which would hide exactly the platform differences this app is for.
        The repaint is guarded separately so it still runs after a failed tap.
        """
        try:
            work()
            status.value = ""
        except Exception as error:
            status.value = f"{type(error).__name__}: {error}"
        try:
            refresh()
        except Exception as error:
            status.value = f"{type(error).__name__}: {error}"
        page.update()

    def travel_now():
        """Start a trip at the destination and tick setting currently selected."""
        clocks.start_trip(picker.selected[0], ticking.value)

    def repaint_only():
        """Do no work, leaving `guard`'s repaint as the whole effect of the tap."""

    def on_travel():
        """Toggle: end a running trip, or start one at the current settings."""
        guard(clocks.stop_trip if clocks.travelling() else travel_now)

    def on_settings():
        """Restart a live trip so a new destination or tick setting takes effect."""
        guard(travel_now if clocks.travelling() else repaint_only)

    def on_shift():
        """Push the trip an hour further on without leaving it."""
        guard(clocks.shift_hour)

    def on_thread():
        """Read the clock from a pool thread to show the patch is process-wide."""

        def worker():
            """Take the reading off the UI thread and paint it.

            `page.run_thread` never retrieves the worker's future, so the body
            carries its own try/except and ends with an explicit `page.update()` -
            auto-update does not reach background threads.
            """
            try:
                thread_line.value = clocks.thread_reading()
            except Exception as error:
                thread_line.value = f"{type(error).__name__}: {error}"
            page.update()

        page.run_thread(worker)

    async def tick_faces():
        """Repaint the two clock faces four times a second for the session's life.

        Only the faces are on this loop - the probe sweep opens a database and
        writes a file, which is far too much to do at this rate.
        """
        while True:
            app_face.value, real_face.value, uptime.value = clocks.faces()
            try:
                page.update()
            except Exception:  # the session is gone; nothing left to paint
                return
            await asyncio.sleep(REFRESH_S)

    page.appbar = ft.AppBar(title=ft.Text("frozen clock"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        clocks.library_line(),
                        size=11,
                        color=None if clocks.AVAILABLE else ft.Colors.ERROR,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} - {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            face(
                                "app clock",
                                app_face := ft.Text(size=28, weight=ft.FontWeight.BOLD),
                            ),
                            face("device clock", real_face := ft.Text(size=28)),
                        ]
                    ),
                    uptime := ft.Text(size=11),
                    ft.Divider(),
                    picker := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name))
                            for name in clocks.DESTINATIONS
                        ],
                        selected=["1969"],  # a set dies in msgpack
                        on_change=on_settings,
                    ),
                    why := ft.Text(size=11),
                    ft.Row(
                        wrap=True,
                        controls=[
                            travel_button := ft.Button("Travel", on_click=on_travel),
                            shift_button := ft.Button(
                                "+1 hour",
                                icon=ft.Icons.FAST_FORWARD,
                                on_click=on_shift,
                            ),
                            ft.Button(
                                "Re-read", icon=ft.Icons.REFRESH, on_click=on_settings
                            ),
                            ft.Button(
                                "From a thread",
                                icon=ft.Icons.CALL_SPLIT,
                                on_click=on_thread,
                            ),
                            ticking := ft.Switch(
                                label="tick", value=True, on_change=on_settings
                            ),
                        ],
                    ),
                    status := ft.Text(size=11, color=ft.Colors.ERROR),
                    ft.Divider(),
                    table := ft.Column(spacing=4),
                    verdict := ft.Text(size=11),
                    thread_line := ft.Text(size=11),
                    ft.Text(
                        clocks.UUID_NOTE, size=10, color=ft.Colors.ON_SURFACE_VARIANT
                    ),
                ],
            ),
        )
    )

    guard(repaint_only)  # first paint, behind the same guard as a tap
    page.run_task(tick_faces)


if __name__ == "__main__":
    ft.run(main)
