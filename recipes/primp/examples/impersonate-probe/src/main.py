import flet as ft
from fingerprint import PROFILES, SYSTEMS, VERSION, echo, probe

# "monospace" is a generic family name that Android maps and iOS does not, and a
# request head only reads as a request head in a fixed-width face.
MONO = {"font_family": "monospace", "font_family_fallback": ["Courier"]}


def picker(label, values, on_select):
    """A dropdown over one of the two impersonation axes."""
    return ft.Dropdown(
        label=label,
        value=values[0],
        dense=True,
        expand=True,
        options=[ft.DropdownOption(key=value, text=value) for value in values],
        on_select=on_select,
    )


def heading(text):
    """The title of one of the two panels."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def observed_row(label, value):
    """One line of the fingerprint table the remote endpoint reported.

    The two `expand` weights sit on Texts inside a Row deliberately: an
    `expand` on a direct child of a scrolling Column collapses the whole
    viewport on iOS while looking perfectly fine on Android.
    """
    return ft.Row(
        vertical_alignment=ft.CrossAxisAlignment.START,
        controls=[
            ft.Text(label, size=11, expand=3),
            ft.Text(value, size=11, expand=8, selectable=True, **MONO),
        ],
    )


def main(page: ft.Page):
    """Two panels over one client: what it writes, and what a server sees.

    The wire panel runs on startup and on every change of profile or OS,
    because it costs a loopback round trip and needs no network. The
    fingerprint panel stays behind a button: it is the only thing here that
    leaves the device.
    """

    def rerun():
        """A new profile or OS invalidates the remote reading, so clear it."""
        observed.controls = []
        probe_note.value = ""
        start(show_wire)

    def start(worker):
        """Put the spinner up, lock the button, and hand `worker` to a thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(worker)

    def show_wire():
        """Print the request head the loopback socket received."""
        try:
            head, status, elapsed = echo(profile.value, system.value)
            wire.value = head
            wire_note.value = (
                f"{status} · {len(head.splitlines()) - 1} headers · {elapsed:.0f} ms"
            )
        except Exception as error:
            wire.value = ""
            wire_note.value = f"{type(error).__name__}: {error}"
        finish()

    def show_fingerprint():
        """Report the hashes the remote endpoint computed from the handshake."""
        try:
            rows, elapsed = probe(profile.value, system.value)
            observed.controls = [observed_row(*row) for row in rows]
            probe_note.value = f"{elapsed:.0f} ms"
        except Exception as error:
            observed.controls = []
            probe_note.value = f"{type(error).__name__}: {error}"
        finish()

    def finish():
        """Release the controls and push the result.

        Every worker body is wrapped and ends here, so an unreachable endpoint
        reports itself instead of leaving the button disabled for good.
        """
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Impersonate probe"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=12),
                    ft.Row(
                        controls=[
                            profile := picker("Impersonate", PROFILES, rerun),
                            system := picker("As OS", SYSTEMS, rerun),
                        ]
                    ),
                    heading("Sent to a loopback socket"),
                    ft.Container(
                        padding=10,
                        border_radius=8,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        content=(wire := ft.Text(size=10, selectable=True, **MONO)),
                    ),
                    wire_note := ft.Text(size=11, color=ft.Colors.OUTLINE),
                    ft.Divider(),
                    heading("Seen by tls.browserleaks.com"),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Probe TLS fingerprint",
                                icon=ft.Icons.FINGERPRINT,
                                on_click=show_fingerprint,
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    probe_note := ft.Text(size=11, color=ft.Colors.OUTLINE),
                    observed := ft.Column(spacing=4),
                ],
            ),
        )
    )

    rerun()


if __name__ == "__main__":
    ft.run(main)
