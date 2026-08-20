from datetime import datetime, timezone

import flet as ft
from sky import SITES, VERSION, leap_seconds, positions, time_scales, utc_from


def row(label, *cells):
    """One line of a results table: a label, then a column per value."""
    return ft.Row(
        controls=[
            ft.Text(label, expand=4, size=12),
            *(ft.Text(c, expand=3, size=12) for c in cells),
        ]
    )


def main(page: ft.Page):
    """Build the screen and wire the three things that trigger a recompute.

    The site and the UT1 guess are the user's; the clock supplies the third and
    moves on its own, which is why there is a button.
    """
    state = {"site": SITES[0], "dut1": 0.0}
    leaps = leap_seconds()
    footer = (
        f"{leaps['entries']} leap seconds compiled into the wheel · "
        f"last {leaps['last']}, TAI-UTC {leaps['tai_utc']:.0f} s · "
        f"pyerfa calls the table expired since {leaps['expires']}"
    )

    def refresh(e=None):
        """Lock the controls and hand the whole transform to a background thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def on_site(e):
        """Move to another observing site, which changes every star's alt/az."""
        state["site"] = SITES[int(e.control.value)]
        refresh()

    def on_dut1(e):
        """Adopt a new guess for UT1 minus UTC and redo the sky from scratch."""
        state["dut1"] = e.control.value
        refresh()

    def compute():
        """Read the device clock, spread it across the time scales, place the stars.

        Everything on screen comes from the one instant `datetime.now` returns,
        and nothing else is consulted: no network, no ephemeris file, no IERS
        bulletin. The `moved` column is the price of that self-sufficiency — how
        far each star travels when the UT1 guess changes from zero to the slider,
        which is the same rotation about the celestial pole for all of them. The
        column therefore scales with cos(dec), not with the star: at the slider's
        limit Polaris moves 0.15" while the rest move 10" to 13.5".

        The time table above it, by contrast, barely depends on the site at all.
        """
        utc = utc_from(datetime.now(timezone.utc))
        scales.controls = [
            row("", "clock", "vs UTC"),
            ft.Divider(height=1),
            *(
                row(name, clock, f"{offset:+.3f} s")
                for name, clock, offset in time_scales(
                    utc, state["site"], state["dut1"]
                )
            ),
        ]
        stars.controls = [
            row("", "altitude", "azimuth", "moved"),
            ft.Divider(height=1),
            *(
                row(name, f"{alt:+.2f}°", f"{az:.2f}°", f'{shift:.1f}"')
                for name, alt, az, shift in positions(utc, state["site"], state["dut1"])
            ),
        ]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Sky clock"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=11),
                    ft.Dropdown(
                        label="Observing site",
                        dense=True,
                        value="0",
                        options=[
                            ft.DropdownOption(key=str(index), text=site[0])
                            for index, site in enumerate(SITES)
                        ],
                        on_select=on_site,
                    ),
                    ft.Text(
                        "UT1 - UTC, the number no offline library can know", size=12
                    ),
                    ft.Slider(
                        min=-0.9,
                        max=0.9,
                        value=0.0,
                        divisions=18,
                        round=1,
                        label="{value} s",
                        # on_change would rebuild the sky for every pixel the thumb
                        # travels; on_change_end rebuilds it once, on release.
                        on_change_end=on_dut1,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Read the clock",
                                icon=ft.Icons.SCHEDULE,
                                on_click=refresh,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    scales := ft.Column(spacing=4),
                    ft.Divider(),
                    stars := ft.Column(spacing=4),
                    ft.Text(footer, size=11, color=ft.Colors.OUTLINE),
                ],
            ),
        )
    )

    refresh()


if __name__ == "__main__":
    ft.run(main)
