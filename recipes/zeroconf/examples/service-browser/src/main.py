import flet as ft
from discovery import BROWSE_TYPES, RUNTIME, lan_address, snapshot, start, stop

ICONS = {
    "Flet app": ft.Icons.PHONE_IPHONE,
    "Printer": ft.Icons.PRINT,
    "Printer (LPD)": ft.Icons.PRINT,
    "AirPlay": ft.Icons.CAST,
    "AirPlay speaker": ft.Icons.SPEAKER,
    "Chromecast": ft.Icons.CAST_CONNECTED,
    "Web interface": ft.Icons.LANGUAGE,
}


def service_card(service):
    """One discovered service: what it is, where it is, and what it says."""
    txt = "  ".join(f"{k}={v}" for k, v in list(service.properties.items())[:3])
    label = "this device" if service.is_self else service.kind
    return ft.Column(
        spacing=1,
        controls=[
            ft.Row(
                spacing=6,
                controls=[
                    ft.Icon(ICONS.get(service.kind, ft.Icons.DEVICES), size=16),
                    ft.Text(service.name, size=13, weight=ft.FontWeight.BOLD),
                    ft.Text(label, size=11, color=ft.Colors.PRIMARY),
                ],
            ),
            ft.Text(
                f"{service.server}:{service.port}  ·  {', '.join(service.addresses)}",
                size=11,
                font_family="monospace",
            ),
            ft.Text(txt, size=11, color=ft.Colors.OUTLINE),
            ft.Divider(height=1),
        ],
    )


def main(page: ft.Page):
    """Advertise this device on the local network and list what answers back."""

    def rebuild():
        """Refill the list from the current snapshot, on a Flet-owned thread."""
        found = snapshot()
        results.controls = [service_card(service) for service in found]
        headline.value = f"{len(found)} found" if found else "searching…"
        # Seeing our own advertisement means the sockets work; it does not mean
        # another device's announcements reach us, since a host loops its own
        # multicast back internally.
        summary.value = (
            f"browsing {len(BROWSE_TYPES)} types · own advertisement "
            f"{'seen' if any(s.is_self for s in found) else 'not seen yet'}"
        )
        page.update()  # auto-update does not reach background threads

    def on_found():
        """Called by zeroconf on its browser thread whenever a service changes.

        Nothing here may touch a control: that thread carries no Flet context.
        `page.run_thread` is safe to call from any thread and hands the UI work
        back to Flet, so `rebuild` runs where it is allowed to.
        """
        page.run_thread(rebuild)

    def begin():
        """Advertise and start browsing, which takes a second or two."""
        try:
            name, note = start(on_found)
            advertised.value = f"advertising as {name}"
            status.value = note
        except Exception as exc:
            advertised.value = "not advertising"
            status.value = f"could not start: {exc}"
        spinner.visible = False
        rebuild()

    def finish():
        """Withdraw the advertisement and close the sockets."""
        stop()
        advertised.value = "not advertising"
        results.controls = []
        headline.value = "stopped"
        summary.value = ""
        spinner.visible = False
        page.update()

    def on_browse(e):
        """Switch discovery on or off; both directions block, so both go to a thread."""
        spinner.visible = True
        page.update()
        page.run_thread(begin if e.control.value else finish)

    page.appbar = ft.AppBar(title=ft.Text("Service browser"), center_title=True)
    # ifaddr answers from the C library in about a millisecond, so the first
    # frame carries a real result instead of waiting on the 1.7 s registration.
    address = lan_address()
    body = [
        ft.Text(RUNTIME, size=11),
        headline := ft.Text("searching…", size=22, weight=ft.FontWeight.BOLD),
        summary := ft.Text(f"browsing {len(BROWSE_TYPES)} types", size=11),
        status := ft.Text("starting…", color=ft.Colors.PRIMARY, selectable=True),
        advertised := ft.Text(f"local address {address}", size=11, selectable=True),
        ft.Row(
            controls=[
                ft.Switch(label="Browse", value=True, on_change=on_browse),
                spinner := ft.ProgressRing(width=16, height=16, visible=True),
            ]
        ),
        results := ft.Column(spacing=6),
    ]
    # Nothing in `body` may carry expand=True: on a scrolling Column's direct
    # child that collapses the whole viewport on iOS while Android renders fine.
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(controls=body, scroll=ft.ScrollMode.AUTO),
        )
    )

    page.run_thread(begin)


if __name__ == "__main__":
    ft.run(main)
