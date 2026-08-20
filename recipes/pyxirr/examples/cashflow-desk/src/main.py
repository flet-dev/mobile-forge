import random

import flet as ft
from cashflow import RATE_MAX, RATE_MIN, SCHEDULES, VERSION, analyse

FIRST = next(iter(SCHEDULES))


def percent(rate):
    """Format a rate, folding anything that rounds to nothing onto a clean zero.

    A root at exactly zero comes back from the solver as a tiny signed residue
    such as -1.7e-11, which "%" would otherwise render as "-0.00%".
    """
    return f"{rate:+.2%}" if abs(rate) >= 5e-5 else "0.00%"


def row(label, value, color=None):
    """One line of a table: label on the left, value right-aligned opposite."""
    return ft.Row(
        controls=[
            ft.Text(label, size=12, expand=2),
            ft.Text(value, size=12, expand=3, color=color, text_align=ft.TextAlign.END),
        ]
    )


def main(page: ft.Page):
    """Wire the schedule picker, the guess slider and the report together."""

    def solve():
        """Lock the controls, raise the spinner, hand the solve to a thread."""
        for control in (picker, guess, shuffle):
            control.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Solve the selected schedule and refill the table, report and strip.

        The solve is microseconds, and the reported figure says so. The thread
        is here because it is the shape that still works once the schedule
        arrives from a file, a database or the network instead of a literal --
        not because pyxirr is slow.
        """
        result = analyse(picker.value, guess.value)
        rate, error = result["rate"], result["error"]
        curve, near = result["profile"][1], result["near"]

        answer = error or ("no root in reach" if rate is None else percent(rate))
        check = (
            "—"
            if rate is None
            else f"{result['residual']:+.2e} on {result['gross']:,.0f} moved"
        )
        schedule.controls = [
            row(when, f"{amount:+,.0f}") for when, amount in SCHEDULES[picker.value]
        ]
        report.controls = [
            row("XIRR", answer, None if rate is not None else ft.Colors.ERROR),
            row("XNPV there", check),
            row("sign changes", str(len(result["crossings"]))),
            row("conventional", "yes" if result["conventional"] else "no"),
            row("roots found", " · ".join(percent(r) for r in result["roots"]) or "—"),
            row("solved in", f"{result['micros']:.1f} µs"),
        ]
        strip.controls = [
            ft.Container(
                expand=1,
                height=26,
                bgcolor=ft.Colors.GREEN_400 if npv > 0 else ft.Colors.RED_400,
                border=ft.Border.all(2, ft.Colors.PRIMARY) if index == near else None,
            )
            for index, npv in enumerate(curve)
        ]

        for control in (picker, guess, shuffle):
            control.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def randomise():
        """Throw the guess somewhere else in the window and solve again.

        On a schedule with one root this changes nothing, which is the point;
        on the mine site the answer jumps between three equally correct rates.
        """
        guess.value = round(random.uniform(RATE_MIN, RATE_MAX), 1)
        solve()

    page.appbar = ft.AppBar(title=ft.Text("Cash flow desk"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    picker := ft.Dropdown(
                        label="Schedule",
                        value=FIRST,
                        dense=True,
                        options=[ft.DropdownOption(key=k) for k in SCHEDULES],
                        on_select=solve,
                    ),
                    schedule := ft.Column(spacing=2),
                    ft.Divider(height=1),
                    report := ft.Column(spacing=2),
                    ft.Divider(height=1),
                    ft.Text(
                        f"Sign of XNPV from {RATE_MIN:+.0%} to {RATE_MAX:+.0%}. Every "
                        "colour boundary breaks even; the outlined cell is the guess.",
                        size=12,
                    ),
                    strip := ft.Row(spacing=1),
                    guess := ft.Slider(
                        min=RATE_MIN,
                        max=RATE_MAX,
                        value=0.1,
                        divisions=39,
                        round=2,
                        label="guess {value}",
                        # on_change would re-solve for every step the thumb
                        # passes through; on_change_end solves once, on release.
                        on_change_end=solve,
                    ),
                    ft.Row(
                        controls=[
                            shuffle := ft.Button(
                                "Random guess",
                                icon=ft.Icons.CASINO,
                                on_click=randomise,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                ],
            ),
        )
    )

    solve()


if __name__ == "__main__":
    ft.run(main)
