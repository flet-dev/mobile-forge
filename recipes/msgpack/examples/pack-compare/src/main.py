import platform

import flet as ft
from formats import (
    HAVE_MSGPACK,
    PAYLOADS,
    conversion_rows,
    fidelity_rows,
    implementation,
    integrity,
    measure,
    payload,
    size_note,
)

SIZE_WEIGHTS = (4, 4, 3, 4, 4)
FIDELITY_WEIGHTS = (6, 5, 5)
CONVERSION_WEIGHTS = (7, 5)


def table_row(values, weights, size=10):
    """One row of a table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def size_cells(measured):
    """Turn one `measure()` result into the display cells of the size table."""
    reference = next(size for label, size, _, _, _ in measured if label == "json")
    return [
        (
            label,
            f"{size:,}",
            f"{size / reference:.2f}",
            f"{write_ms:,.2f}",
            f"{read_ms:,.2f}",
        )
        for label, size, write_ms, read_ms, _ in measured
    ]


def main(page: ft.Page):
    """Measure both formats on this device and show where they disagree.

    Three things are on screen: what each format costs in bytes and
    milliseconds, what survives a round trip unchanged, and what a damaged
    frame does. Everything is computed here rather than bundled, and the
    import is guarded so a missing wheel degrades to a json-only screen
    instead of a crash.
    """
    shown = PAYLOADS[0]  # the payload the size table currently describes

    def start():
        """Send one comparison to the thread pool and lock the picker meanwhile.

        The guard is set in this synchronous handler rather than in the worker:
        `run_thread` only schedules, so a `disabled` set inside the worker
        would not have reached the client before a second tap could start an
        overlapping run. A tap that beats it is dropped and the picker is put
        back to the payload being measured, because the client moves its own
        highlight the instant it is tapped.
        """
        nonlocal shown
        if picker.disabled:
            picker.selected = [shown]
            page.update()
            return
        shown = picker.selected[0]  # SegmentedButton.selected is a list
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run, shown)

    def run(name):
        """Measure one payload, then the fidelity cases and the bit flips.

        The payload name is passed in rather than read off the picker, because
        the worker starts after the handler returns and a tap landing in
        between would move `picker.selected` out from under it.

        Wrapped in try/except because `page.run_thread` discards whatever a
        worker raises — without this, a failure would look like a screen that
        quietly stopped updating. The tables are cleared on the error path so
        numbers from the previous run cannot be read as describing the error.
        """
        try:
            measured = measure(payload(name))
            sizes.controls = [
                table_row(
                    ("format", "bytes", "vs json", "pack ms", "unpack ms"),
                    SIZE_WEIGHTS,
                ),
                ft.Divider(height=1),
                *(table_row(row, SIZE_WEIGHTS) for row in size_cells(measured)),
            ]
            exact = sum(1 for row in measured if row[4])
            summary.value = (
                f"{name} · {exact}/{len(measured)} formats decoded back to an "
                f"equal object{size_note(measured)}"
            )
            fidelity.controls = [
                table_row(("value", "msgpack", "json"), FIDELITY_WEIGHTS),
                ft.Divider(height=1),
                *(table_row(row, FIDELITY_WEIGHTS) for row in fidelity_rows()),
            ]
            silent.controls = [
                table_row(row, CONVERSION_WEIGHTS) for row in conversion_rows()
            ]
            damage.value = integrity()
        except Exception as error:  # the worker must never let one escape
            sizes.controls = []
            fidelity.controls = []
            silent.controls = []
            damage.value = ""
            summary.value = f"{type(error).__name__}: {error}"

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("msgpack vs json"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        implementation(),
                        size=11,
                        color=None if HAVE_MSGPACK else ft.Colors.ERROR,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} · {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                segments=[
                                    ft.Segment(value=name, label=ft.Text(name))
                                    for name in PAYLOADS
                                ],
                                selected=[PAYLOADS[0]],  # a set dies in msgpack
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    sizes := ft.Column(spacing=4),
                    summary := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("what survives a round trip", size=11),
                    fidelity := ft.Column(spacing=4),
                    ft.Divider(),
                    ft.Text("same bytes, different type", size=11),
                    silent := ft.Column(spacing=4),
                    ft.Divider(),
                    damage := ft.Text(size=11),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
