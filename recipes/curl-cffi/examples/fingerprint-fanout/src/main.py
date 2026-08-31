import flet as ft
from impersonation import (
    CURL_VERSION,
    FIELDS,
    PROBE_URL,
    TARGETS,
    VERSION,
    cacert,
    fanout,
    known_targets,
)

# "monospace" is a generic family name that Android maps and iOS does not, and a
# hash only reads as a hash in a fixed-width face; Courier backs it up there.
MONO = {"font_family": "monospace", "font_family_fallback": ["Courier"]}


def result_row(target):
    """Build one target's row, and return it with a callback that refills it.

    The five rows are laid out up front in a fixed order rather than appended as probes
    land, which a fan-out would order at random and make uncomparable. The callback
    closes over the previous run's values so a hash that moved can be tinted — which is
    how a second run shows that it is the Chrome targets' raw ja3 that changes from one
    handshake to the next.
    """
    status = ft.Text("…", size=11, color=ft.Colors.OUTLINE)
    failed = ft.Text(size=11, color=ft.Colors.ERROR, max_lines=2)
    # expand sits on a Text inside a Row, never on a direct child of the
    # scrolling Column: there it collapses the whole viewport on iOS.
    values = {
        name: ft.Text(size=10, expand=True, selectable=True, **MONO) for name in FIELDS
    }
    fields = ft.Column(
        spacing=1,
        controls=[
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Text(name, size=10, width=36, color=ft.Colors.OUTLINE),
                    values[name],
                ],
            )
            for name in FIELDS
        ],
    )
    control = ft.Column(
        spacing=1,
        controls=[
            ft.Row(
                controls=[
                    ft.Text(target, size=13, weight=ft.FontWeight.BOLD, expand=True),
                    status,
                ]
            ),
            failed,
            fields,
            ft.Divider(height=8),
        ],
    )
    previous = {}

    def refill(reading=None, error=None):
        """Show this row's outcome, tinting whatever moved since the last run.

        Called with neither argument to blank the row while a probe is in flight.
        """
        failed.value = error or ""
        fields.visible = error is None
        if error:
            status.value = "failed"
            status.color = ft.Colors.ERROR
            return
        status.color = ft.Colors.OUTLINE
        if reading is None:
            status.value = "…"
            for text in values.values():
                text.value = ""
            return
        status.value = (
            f"{reading['status']} · {reading['http']} · {reading['ms']:.0f} ms"
        )
        for name in FIELDS:
            moved = name in previous and previous[name] != reading[name]
            values[name].value = reading[name]
            values[name].color = ft.Colors.PRIMARY if moved else None
            previous[name] = reading[name]

    return control, refill


async def main(page: ft.Page):
    async def run():
        """Refill every row from one concurrent fan-out, then total the timings.

        Ends in an explicit page.update() because a task gets none of the
        auto-update an event handler does, and the `finally` releases the button
        even when every probe failed.
        """
        for refill in rows.values():
            refill()
        footer.value = f"probing {len(TARGETS)} targets…"
        spinner.visible = True
        page.update()

        summed = 0.0
        landed = 0

        def show(target, reading, error):
            """Fill one row the moment its probe lands, from the same loop."""
            nonlocal summed, landed
            if reading:
                landed += 1
                summed += reading["ms"]
            rows[target](reading, error)
            page.update()

        try:
            wall = await fanout(show)
            footer.value = f"{landed}/{len(TARGETS)} probes · {wall:.0f} ms wall"
            if landed:
                footer.value += (
                    f" · {summed:.0f} ms summed ({summed / wall:.1f}x overlap)"
                )
        finally:
            button.disabled = False
            spinner.visible = False
            page.update()

    def rerun():
        """Start a fan-out. The guard is set here, not inside `run`.

        `page.run_task` only schedules, so a `disabled` set inside the coroutine
        has not happened when this handler returns and Flet pushes the button's
        state — a second tap in that window queues a second fan-out into the same
        rows. `run_thread` is not an alternative: AsyncSession drives libcurl
        through the running loop's readers and writers, and a worker thread has
        no loop.
        """
        if button.disabled:
            return
        button.disabled = True
        page.run_task(run)

    source, path, contents = cacert()
    verdicts = known_targets()
    rows = {}
    row_controls = []
    for target in TARGETS:
        control, refill = result_row(target)
        rows[target] = refill
        row_controls.append(control)

    page.appbar = ft.AppBar(title="Fingerprint fan-out", center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(f"{VERSION} on {page.platform.value}", size=12),
                    ft.Text(CURL_VERSION, size=10, **MONO),
                    ft.Text(
                        f"fingerprint tables {sum(verdicts.values())}/{len(verdicts)} · "
                        f"{', '.join(t for t, ok in verdicts.items() if ok)}",
                        size=11,
                    ),
                    ft.Text(f"CA bundle via {source} — {contents}", size=11),
                    ft.Text(path, size=10, selectable=True, **MONO),
                    ft.Divider(),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Probe all targets",
                                icon=ft.Icons.FINGERPRINT,
                                on_click=rerun,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    ft.Text(
                        f"as seen by {PROBE_URL}", size=11, color=ft.Colors.OUTLINE
                    ),
                    *row_controls,
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    # Scheduled, not awaited: Flet awaits `main` before its first update, so
    # awaiting a fan-out here would hold the first frame for up to the timeout on
    # a phone with no network. Everything above the button is already on screen.
    rerun()


if __name__ == "__main__":
    ft.run(main)
