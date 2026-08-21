import flet as ft
from driver import (
    DEFAULT_DSN,
    SAMPLES,
    api_type_groups,
    attempt,
    driver_facts,
    load_oracle_client,
    parse,
    prepare_config,
)


def table(pairs):
    """Turn (label, value) pairs into rows of a two-column table."""
    return [
        ft.Row(
            [
                ft.Text(label, size=12, expand=2),
                ft.Text(value, size=12, expand=5, selectable=True),
            ]
        )
        for label, value in pairs
    ]


def heading(text):
    """A section label above a block of rows."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def main(page: ft.Page):
    """Wire the driver panels together; every panel is filled before first paint."""
    config_dir = prepare_config()

    def show_parse(e=None):
        """Re-run the parser over whatever is in the field."""
        parsed.controls = table(parse(dsn.value.strip()))
        page.update()

    def pick_sample(e):
        """Copy the chosen sample connect string into the field and parse it."""
        dsn.value = e.control.value
        show_parse()

    def start_connect(e):
        """Lock the button and hand the connection attempt to a background thread."""
        connect.disabled = True
        spinner.visible = True
        outcome.controls = []
        page.update()
        page.run_thread(work)

    def work():
        """Attempt the connection off the UI thread, then report the outcome.

        The unroutable sample sits in a socket for the full timeout, which is
        exactly the wait that must not happen on the UI thread. The finally
        clause keeps a surprise exception from leaving the button disabled for
        the session: page.run_thread swallows whatever the worker raises.
        """
        try:
            outcome.controls = table(attempt(dsn.value.strip()))
        finally:
            connect.disabled = False
            spinner.visible = False
            page.update()  # auto-update does not reach background threads

    def load_client(e):
        """Try to switch to thick mode, then re-read the driver panel.

        Re-reading matters: on a desktop with an Oracle Client installed this
        succeeds and the mode flips for the rest of the process.
        """
        thick.controls = table(load_oracle_client())
        facts.controls = table(driver_facts())
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("Oracle thin client"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    heading("Driver"),
                    facts := ft.Column(table(driver_facts()), spacing=2),
                    ft.Divider(height=1),
                    heading("Connect string"),
                    ft.Dropdown(
                        label="Sample",
                        dense=True,
                        options=[
                            ft.DropdownOption(key=value, text=label)
                            for label, value in SAMPLES
                        ],
                        on_select=pick_sample,
                    ),
                    dsn := ft.TextField(
                        label="dsn",
                        value=DEFAULT_DSN,
                        dense=True,
                        multiline=True,
                        min_lines=1,
                        max_lines=4,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_submit=show_parse,
                        on_blur=show_parse,
                    ),
                    ft.Text(f"config_dir {config_dir}", size=11),
                    parsed := ft.Column(table(parse(DEFAULT_DSN)), spacing=2),
                    ft.Row(
                        [
                            connect := ft.Button(
                                "Connect", icon=ft.Icons.CABLE, on_click=start_connect
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    outcome := ft.Column(spacing=2),
                    ft.Divider(height=1),
                    heading("Thick mode"),
                    ft.Button(
                        "init_oracle_client()",
                        icon=ft.Icons.EXTENSION,
                        on_click=load_client,
                    ),
                    thick := ft.Column(spacing=2),
                    ft.Divider(height=1),
                    heading("cursor.description types"),
                    ft.Column(table(api_type_groups()), spacing=2),
                ],
            ),
        )
    )


if __name__ == "__main__":
    ft.run(main)
