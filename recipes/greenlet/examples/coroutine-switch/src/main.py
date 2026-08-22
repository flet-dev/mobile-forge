"""Exercise greenlet's per-architecture assembly switch on the device that runs it.

Four panels: what a switch costs against a generator and a thread; how that cost
grows with the depth of the parked greenlet; a conformance run covering the paths
that machine code can get wrong; and the two greenlets that prove the GIL is still
there. Everything runs inside `page.run_thread`, so a green result is also a
statement that greenlets work on a Flet worker thread and not only on the main one.

The switching itself is in `switching.py`; this file is the screen and its wiring.
"""

import flet as ft
from switching import (
    BUDGETS,
    IMPORT_ERROR,
    RUNTIME,
    VERSION,
    conformance,
    costs,
    depth_rows,
    gil_note,
    thread_note,
)

ROW_WEIGHTS = (5, 4, 4)  # a wide label column, then two number columns


def line(cells):
    """One line of a numeric table: a `Text` per cell, laid out by weight."""
    widths = zip(cells, ROW_WEIGHTS)
    return ft.Row(controls=[ft.Text(c, size=11, expand=w) for c, w in widths])


def table(header, rows, absent=""):
    """A header, a rule and a line per row — or `absent`, for a panel with no rows.

    That arm is what a missing wheel looks like: the panel says what was skipped
    rather than going blank.
    """
    if not rows:
        return [ft.Text(absent, size=11)]
    return [line(header), ft.Divider(height=1), *(line(row) for row in rows)]


def check(label, ok, detail):
    """One conformance result: a tick or a cross, the label, and what it saw."""
    mark = ft.Icons.CHECK_CIRCLE if ok else ft.Icons.CANCEL
    colour = ft.Colors.GREEN if ok else ft.Colors.ERROR
    said = ft.Text(f"{label} - {detail}", size=11, expand=True)
    return ft.Row(spacing=6, controls=[ft.Icon(mark, size=14, color=colour), said])


def main(page: ft.Page):
    """Measure and validate greenlet's switch on this device, on a worker thread.

    Without the wheel the app still runs: the header turns red and names what the
    import raised, the generator and thread rows are still measured so the device's
    baseline is visible, and every greenlet cell reads a dash.
    """
    shown = next(iter(BUDGETS))
    header_colour = ft.Colors.ERROR if IMPORT_ERROR else None

    def start():
        """Send one measurement to the thread pool and lock the picker while it runs.

        The guard is set in this synchronous handler rather than in the worker:
        `run_thread` only schedules, so a `disabled` set inside the worker would not
        have reached the client before a second tap could start an overlapping run.
        A tap that beats it is dropped and the picker is put back to the size being
        measured, because the client moves its own highlight the instant it is
        tapped.
        """
        nonlocal shown
        if picker.disabled:
            picker.selected = [shown]
            page.update()
            return
        shown = picker.selected[0]
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run, BUDGETS[shown])

    def run(trips):
        """Fill the four panels from one measuring pass, then release the picker.

        Wrapped in try/except because `page.run_thread` discards whatever a worker
        raises — without this a failure would look like a screen that quietly
        stopped updating. The panels are cleared on the error path so numbers from
        the previous run cannot be read as describing the error.
        """
        try:
            where.color = None  # an earlier failure may have left it red
            where.value = thread_note()
            speeds.controls = table(("handoff", "ns each", "per second"), costs(trips))
            depths.controls = table(
                ("frames parked", "stack saved", "ns / pair"),
                depth_rows(trips),
                "greenlet absent - no depth sweep",
            )
            results = conformance()
            passed = sum(1 for _, ok, _ in results if ok)
            checks.controls = [check(*result) for result in results] or [
                ft.Text("greenlet absent - nothing to check", size=11)
            ]
            score.value = f"{passed}/{len(results)} checks pass" if results else ""
            score.color = ft.Colors.GREEN if passed == len(results) else ft.Colors.ERROR
            gil.value = gil_note()
        except Exception as error:  # the worker must never let one escape
            speeds.controls, depths.controls, checks.controls = [], [], []
            score.value = gil.value = ""
            where.value = f"{type(error).__name__}: {error}"
            where.color = ft.Colors.ERROR

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("greenlet switch report"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=11, color=header_colour),
                    ft.Text(f"{RUNTIME} - {page.platform.value}", size=11),
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                segments=[
                                    ft.Segment(value=label, label=ft.Text(label))
                                    for label in BUDGETS
                                ],
                                selected=[shown],  # a set dies in msgpack
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    where := ft.Text(size=11),
                    speeds := ft.Column(spacing=4),
                    ft.Divider(),
                    ft.Text("cost against the depth of the parked greenlet", size=11),
                    depths := ft.Column(spacing=4),
                    ft.Divider(),
                    ft.Text("what the assembly has to get right", size=11),
                    checks := ft.Column(spacing=2),
                    score := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("greenlets are not a second core", size=11),
                    gil := ft.Text(size=11),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
