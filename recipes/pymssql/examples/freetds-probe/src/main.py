import os

import flet as ft
from tds import connect_error, driver_facts, parse_server, run_probes


def row(label, value, indent=0):
    """One label/value line of a report block."""
    return ft.Row(
        spacing=8,
        controls=[
            ft.Text(label, size=12, width=96 - indent, color=ft.Colors.OUTLINE),
            ft.Text(value, size=12, expand=True, selectable=True),
        ],
    )


def main(page: ft.Page):
    """Report the FreeTDS build, then log in to a socket this app owns.

    The driver facts are on screen before the first frame; the four handshake
    probes and the connection attempt both run off the UI thread, because
    FreeTDS blocks the thread it is called on for the whole login.
    """
    scratch = os.getenv("FLET_APP_STORAGE_TEMP", ".")

    def show_parse(event=None):
        """Report what pymssql will actually hand to FreeTDS, as the user types.

        The parse can also fail outright — two backslashes make pymssql's own
        split raise before FreeTDS ever sees the string — so it is caught here
        and shown, which is what a connection attempt would do with it too.
        """
        try:
            target, notes = parse_server(host.value or "", port.value or "1433")
            parsed.controls = [row("FreeTDS gets", target)]
            parsed.controls += [row("", note) for note in notes]
        except ValueError as exc:
            parsed.controls = [row("raises", f"ValueError: {exc}")]
        page.update()

    def handshakes():
        """Run the in-process login probes and put each result on screen."""
        try:
            for heading, rows in run_probes(scratch):
                probes.controls.append(
                    ft.Text(heading, size=13, weight=ft.FontWeight.BOLD)
                )
                probes.controls += [row(label, value, 8) for label, value in rows]
        except Exception as exc:
            probes.controls.append(row("probe failed", str(exc)))
        finally:
            probing.visible = False
            page.update()  # auto-update does not reach background threads

    def connect(event):
        """Lock the button and hand the real connection attempt to a thread."""
        button.disabled = True
        connecting.visible = True
        outcome.controls.clear()
        page.update()
        page.run_thread(attempt)

    def attempt():
        """Try the address in the fields and report the exception it raises.

        Nothing is listening on 1433 on a phone, so the default address reliably
        shows the failure shape an app has to handle, doubled because the driver's
        compiled-in protocol default tries TDS 7.4 and then TDS 5.0. An address
        that accepts and then stalls is the one that misbehaves: retrying the
        version list outlasts ``login_timeout``, and this worker never finishes.
        """
        try:
            rows = connect_error(host.value or "", port.value or "1433")
            outcome.controls = [row(label, value) for label, value in rows]
        except Exception as exc:
            outcome.controls = [row("attempt failed", str(exc))]
        finally:
            button.disabled = False
            connecting.visible = False
            page.update()

    page.appbar = ft.AppBar(title=ft.Text("FreeTDS probe"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    *(row(label, value) for label, value in driver_facts()),
                    ft.Divider(),
                    ft.Row(
                        controls=[
                            ft.Text("Login handshakes, no server involved", size=13),
                            probing := ft.ProgressRing(width=14, height=14),
                        ]
                    ),
                    probes := ft.Column(spacing=2),
                    ft.Divider(),
                    ft.Row(
                        controls=[
                            host := ft.TextField(
                                label="server",
                                value="127.0.0.1",
                                expand=3,
                                on_change=show_parse,
                            ),
                            port := ft.TextField(
                                label="port",
                                value="1433",
                                expand=2,
                                on_change=show_parse,
                            ),
                        ]
                    ),
                    parsed := ft.Column(spacing=2),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Connect", icon=ft.Icons.BOLT, on_click=connect
                            ),
                            connecting := ft.ProgressRing(
                                width=14, height=14, visible=False
                            ),
                        ]
                    ),
                    outcome := ft.Column(spacing=2),
                ],
            ),
        )
    )

    show_parse()
    page.run_thread(handshakes)


if __name__ == "__main__":
    ft.run(main)
