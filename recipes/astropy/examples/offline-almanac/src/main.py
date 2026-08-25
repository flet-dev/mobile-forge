import flet as ft
from almanac import HEADER, NOT_ATTEMPTED, almanac, coverage, self_checks

STATUS_COLOURS = {
    "measured": ft.Colors.GREEN,
    "predicted": ft.Colors.AMBER,
    "frozen": ft.Colors.RED,
    "error": ft.Colors.RED,
}


def main(page: ft.Page):
    """An almanac for one date, with the offline caveats printed next to the answers.

    The slider moves the date past the end of the bundled Earth-orientation table on
    purpose: that is the moment UT1-UTC silently freezes, and the banner is the only thing
    that says so.
    """

    def recompute():
        """Recompute every value that depends on the chosen date, and put it on screen.

        Guarded broadly because run_thread drops the worker's future: an unguarded raise
        here would vanish, leaving the last date's numbers on screen as if they were new.
        """
        try:
            status, message, report = almanac(months.value)
        except Exception as exc:
            status, message, report = "error", f"{type(exc).__name__}: {exc}", ""
        banner.value = message
        banner.color = STATUS_COLOURS[status]
        sky.value = report
        page.update()  # auto-update does not reach background threads

    def startup():
        """First-launch work — coverage line, almanac, self-checks — all off the UI thread.

        The coverage line and the self-checks get their own guards for the same reason
        recompute has one: either panel should say what went wrong rather than sit at
        "running…" for the rest of the session with nothing logged anywhere.
        """
        try:
            span.value = coverage()
        except Exception as exc:
            span.value = f"coverage unknown — {type(exc).__name__}: {exc}"
        recompute()
        try:
            checks.value = "\n".join(self_checks())
        except Exception as exc:
            checks.value = f"self-checks did not finish — {type(exc).__name__}: {exc}"
        page.update()

    def on_epoch_change():
        """Recompute on on_change_end, so a drag does not queue one run per pixel."""
        page.run_thread(recompute)

    page.appbar = ft.AppBar(title=ft.Text("Offline almanac"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(HEADER, size=11),
                    span := ft.Text(size=11),
                    months := ft.Slider(
                        min=-12,
                        max=36,
                        divisions=48,
                        value=0,
                        label="{value} months from now",
                        on_change_end=on_epoch_change,
                    ),
                    banner := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    sky := ft.Text(font_family="monospace", size=12, selectable=True),
                    ft.Divider(),
                    ft.Text("Self-checks", weight=ft.FontWeight.BOLD),
                    checks := ft.Text("running…", size=11, selectable=True),
                    ft.Divider(),
                    ft.Text(NOT_ATTEMPTED, size=11),
                ],
            ),
        )
    )

    # After page.add, so the walrus-bound controls above it exist.
    page.run_thread(startup)


if __name__ == "__main__":
    ft.run(main)
