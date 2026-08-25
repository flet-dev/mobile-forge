import flet as ft
import thermo


def main(page: ft.Page):
    """One screen: a cross-check table, a saturation sweep, and three out-of-range requests.

    Nothing is computed before the first frame. `import CoolProp` parses the whole fluid
    database its extension carries, which is the app's single largest cost, so it stays
    inside thermo.load() and runs in the thread pool with a spinner on screen.
    """

    def problem(exc):
        """The one way this app reports a failure: the exception class and its message."""
        return ft.Text(f"{type(exc).__name__}: {exc}", color=ft.Colors.ERROR, size=11)

    def note(text, colour=None):
        """Small secondary text — the app's unit of detail under every heading."""
        return ft.Text(text, size=11, color=colour or ft.Colors.ON_SURFACE_VARIANT)

    def heading(text):
        """A section title."""
        return ft.Text(text, size=14, weight=ft.FontWeight.BOLD)

    def render(column, build):
        """Replace `column`'s children with `build()`'s, showing any exception in their place.

        An unhandled exception in a Flet handler ends the session with a crash screen,
        which would hide exactly the failure this app exists to show.
        """
        try:
            column.controls = build()
        except Exception as exc:
            column.controls = [problem(exc)]

    def verdict(label, ok, detail):
        """One result line: a pass/fail icon, the question asked, and the answer under it."""
        return ft.Column(
            spacing=0,
            controls=[
                ft.Row(
                    spacing=6,
                    controls=[
                        ft.Icon(
                            ft.Icons.CHECK_CIRCLE if ok else ft.Icons.CANCEL,
                            color=ft.Colors.GREEN if ok else ft.Colors.ERROR,
                            size=16,
                        ),
                        ft.Text(label, size=13, expand=True),
                    ],
                ),
                note(detail, None if ok else ft.Colors.ERROR),
            ],
        )

    def check_rows():
        """The reference table: every published value against what CoolProp computes."""
        return [verdict(*row) for row in thermo.checks()]

    def probe_rows():
        """The three impossible requests, under the limits CoolProp reports for water.

        A green tick here means CoolProp *refused*. The third row is why this app exists.
        """
        return [note(thermo.limits_line())] + [
            verdict(*row) for row in thermo.probes()
        ]

    def dome_rows():
        """The saturation point the slider picked, and what the sweep cost measured both ways."""
        headline, properties, timing = thermo.sweep(fluids.selected[0], position.value)
        return [ft.Text(headline, size=13), note(properties), note(timing)]

    def refresh():
        """Redraw the sweep. Runs in the thread pool: several hundred short CoolProp calls."""
        render(dome, dome_rows)
        page.update()  # auto-update does not reach background threads

    def on_input_change():
        """Send the sweep off the UI thread whenever the fluid or the temperature changes."""
        page.run_thread(refresh)

    def start():
        """Import CoolProp in the thread pool, then fill every section.

        run_thread retrieves no future, so an import that fails on device would otherwise
        leave the spinner turning with nothing on screen to say why.
        """
        try:
            cost = thermo.load()
        except Exception as exc:
            checks.controls = [problem(exc)]
            page.update()
            return

        render(checks, check_rows)
        render(dome, dome_rows)
        render(probes, probe_rows)
        footer.controls = [
            note(cost),
            note(f"{thermo.library_line()} on {page.platform.value}"),
        ]
        fluids.disabled = position.disabled = False
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("CoolProp property check"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                controls=[
                    heading("Against published values"),
                    checks := ft.Column(spacing=10, controls=[ft.ProgressRing()]),
                    ft.Divider(),
                    heading("Saturation line"),
                    fluids := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name))
                            for name in thermo.FLUIDS
                        ],
                        selected=[thermo.FLUIDS[0]],
                        disabled=True,
                        on_change=on_input_change,
                    ),
                    position := ft.Slider(
                        min=2,
                        max=98,
                        value=50,
                        divisions=48,
                        label="{value}% up the dome",
                        disabled=True,
                        # on_change_end, so one drag runs one sweep instead of one per
                        # pixel the thumb travels.
                        on_change_end=on_input_change,
                    ),
                    dome := ft.Column(spacing=2),
                    ft.Divider(),
                    heading("Requests CoolProp should refuse"),
                    probes := ft.Column(spacing=10),
                    ft.Divider(),
                    footer := ft.Column(spacing=2),
                ],
            ),
        )
    )

    page.run_thread(start)


if __name__ == "__main__":
    ft.run(main)
