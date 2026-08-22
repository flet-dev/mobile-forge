import flet as ft
from telemetry import IMPLEMENTATION, SIZES, header, measure, plural, probes

TIMING_WEIGHTS = (7, 5, 5, 4)

PANEL_WEIGHTS = (7, 8)


def table_row(values, weights, size=11, weight=None):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=column, weight=weight)
            for value, column in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Time a runtime-built protobuf schema against json, then show where protobuf bites.

    The header line is the point of the whole exercise. protobuf substitutes a pure-Python
    implementation whenever its C extension is missing, without a warning of any kind, and
    every message still round-trips correctly — roughly a hundred times slower. So if that
    line says anything but `upb`, the milliseconds below it are the fallback's, and the app
    says so in red rather than letting you read them as protobuf's.
    """

    def show_count():
        """Report the batch size the next run will use, as the slider moves."""
        caption.value = f"{plural(SIZES[int(size.value)])} per batch"

    def start():
        """Hand one run to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end, which fires once on release, so one gesture is
        one run. The guard is set here rather than in the worker because this body is
        synchronous where `run_thread` only schedules: a `disabled` set inside the worker
        would not have happened yet when Flet pushes the control states, and a second
        release would start a run that rewrites the same table.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Measure one batch off the UI thread and rewrite the table with the result.

        The try/except is load-bearing: `page.run_thread` discards whatever a worker raises,
        so a mistake in here would look like a screen that quietly stopped updating. It
        clears the table on the way out, because timings left over from the previous run
        read as though they described the error.
        """
        try:
            rows, checks.value, storage.value = measure(SIZES[int(size.value)])
            timings.controls = [
                table_row(
                    ("", "protobuf", "json", "ratio"),
                    TIMING_WEIGHTS,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Divider(height=1),
                *(table_row(row, TIMING_WEIGHTS) for row in rows),
            ]
        except Exception as error:
            timings.controls = []
            checks.value = ""
            storage.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def fill_panels():
        """Make every non-timing call on this device and put the answers on screen."""
        cases, drift.value, digests.value, presence.value = probes()
        panel.controls = [table_row(case, PANEL_WEIGHTS, 10) for case in cases]

    page.appbar = ft.AppBar(title=ft.Text("protobuf runtime schema"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"implementation: {IMPLEMENTATION}",
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=None if IMPLEMENTATION == "upb" else ft.Colors.RED,
                    ),
                    ft.Text(header(page.platform.value), size=11),
                    ft.Text(
                        "schema compiled from a FileDescriptorProto at import: "
                        "no .proto file, no _pb2.py, no protoc",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=0,
                        max=len(SIZES) - 1,
                        value=1,
                        divisions=len(SIZES) - 1,
                        on_change=show_count,
                        on_change_end=start,
                    ),
                    timings := ft.Column(spacing=4),
                    checks := ft.Text(size=11),
                    storage := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("bytes that are not your message", size=11),
                    panel := ft.Column(spacing=2),
                    drift := ft.Text(size=11),
                    digests := ft.Text(size=11),
                    presence := ft.Text(size=11),
                ],
            ),
        )
    )

    show_count()
    fill_panels()
    start()


if __name__ == "__main__":
    ft.run(main)
