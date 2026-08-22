import platform

import flet as ft
from urls import (
    HAVE_YARL,
    SAMPLES,
    fixed_panels,
    implementation,
    parse_rows,
    query_rows,
    requote,
    timing_lines,
)

SMALL = 11
TINY = 10


def field_block(label, mine, theirs):
    """One field of the parse table: its name, then each library's answer."""
    return ft.Column(
        spacing=0,
        controls=[
            ft.Text(label, size=TINY, weight=ft.FontWeight.BOLD),
            ft.Text(f"yarl    {mine}", size=SMALL, color=ft.Colors.PRIMARY),
            ft.Text(f"stdlib  {theirs}", size=SMALL),
        ],
    )


def labelled(label, value):
    """A dimmer label above a value, for the panels that are not two-sided."""
    return ft.Column(
        spacing=0,
        controls=[
            ft.Text(label, size=TINY, weight=ft.FontWeight.BOLD),
            ft.Text(value, size=SMALL),
        ],
    )


def panel(heading, rows):
    """A divider, a heading, and one labelled block per row of a fixed comparison."""
    return ft.Column(
        controls=[
            ft.Divider(),
            ft.Text(heading, size=TINY),
            *(labelled(label, value) for label, value in rows),
        ]
    )


def main(page: ft.Page):
    """Parse whatever is in the field with both libraries and show the difference.

    Everything on screen is computed on the device. Without the yarl wheel the app
    still runs: the header turns red and names what the import raised, every stdlib
    answer is still computed, and the yarl side of each comparison reads `-`.
    """

    def analyse():
        """Re-run the three input-driven panels against the current field value.

        Wrapped in try/except because an exception escaping a Flet event handler
        ends the session with a crash screen, and a malformed URL typed into the
        field is an ordinary thing for a workbench to be handed.
        """
        try:
            text = query.value or ""
            table.controls = [field_block(*row) for row in parse_rows(text)]
            requoted.value, same = requote(text)
            requoted.color = ft.Colors.PRIMARY if same else ft.Colors.ERROR
            queries.controls = [labelled(*row) for row in query_rows(text)]
        except Exception as error:
            table.controls = []
            queries.controls = []
            requoted.value = f"{type(error).__name__}: {error}"
            requoted.color = ft.Colors.ERROR

    def pick():
        """Copy the chosen sample into the field, then re-parse.

        Empty selection is allowed - tapping the highlighted segment clears it - so
        the list is checked rather than indexed, and clearing leaves the field alone.
        """
        if picker.selected:
            query.value = SAMPLES[picker.selected[0]]
        analyse()

    def submitted():
        """Re-parse after the keyboard's return key, dropping the sample highlight."""
        picker.selected = []
        analyse()

    def start():
        """Send the timing run to the thread pool and lock the button meanwhile.

        The guard is set here rather than in the worker because `run_thread` only
        schedules: a `disabled` set inside the worker would not have reached the
        client before a second tap could start an overlapping run.
        """
        if timer.disabled:
            return
        timer.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(measure)

    def measure():
        """Time both quoters off the UI thread and put the result on screen.

        Wrapped in try/except because `page.run_thread` discards whatever a worker
        raised - no log, no dialog, no crash - so an unguarded failure would look
        like a panel that quietly stopped updating.
        """
        try:
            numbers.value = "\n".join(timing_lines())
        except Exception as error:
            numbers.value = f"{type(error).__name__}: {error}"
        timer.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("yarl URL workbench"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        implementation(),
                        size=TINY,
                        color=None if HAVE_YARL else ft.Colors.ERROR,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} - {page.platform.value}",
                        size=TINY,
                    ),
                    query := ft.TextField(
                        label="URL",
                        value=SAMPLES["unicode"],
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        text_size=12,
                        multiline=True,
                        min_lines=1,
                        max_lines=3,
                        on_submit=submitted,
                    ),
                    # expand=True on a direct child of a scrolling Column collapses
                    # the whole viewport on iOS; the Row gives it bounded width.
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                allow_empty_selection=True,  # a typed URL is no sample
                                segments=[
                                    ft.Segment(value=name, label=ft.Text(name))
                                    for name in SAMPLES
                                ],
                                selected=["unicode"],  # a list, never a set
                                on_change=pick,
                            ),
                        ],
                    ),
                    table := ft.Column(spacing=6),
                    ft.Divider(),
                    ft.Text("re-encoding the same URL", size=TINY),
                    requoted := ft.Text(size=SMALL),
                    ft.Divider(),
                    ft.Text("the query string, four readings", size=TINY),
                    queries := ft.Column(spacing=6),
                    *(panel(heading, rows) for heading, rows in fixed_panels()),
                    ft.Divider(),
                    ft.Row(
                        controls=[
                            timer := ft.Button(
                                "time the two quoters",
                                icon=ft.Icons.TIMER,
                                on_click=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    numbers := ft.Text(size=SMALL),
                ],
            ),
        )
    )

    analyse()


if __name__ == "__main__":
    ft.run(main)
