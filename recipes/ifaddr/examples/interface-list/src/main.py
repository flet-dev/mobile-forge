import time

import flet as ft
from interfaces import (
    VERSION,
    addresses_in,
    changes,
    fingerprint,
    lan_address,
    scan,
    summarise,
)

FAMILIES = ("all", "IPv4", "IPv6")
LOG_LINES = 30


def address_row(address):
    """One address line: the address, its prefix length and its scope."""
    return ft.Row(
        controls=[
            ft.Text(address.text, size=12, font_family="monospace", expand=5),
            ft.Text(f"/{address.prefix}", size=12, expand=1),
            ft.Text(address.kind, size=11, color=ft.Colors.PRIMARY, expand=2),
        ]
    )


def interface_card(interface, family):
    """One interface: its name, its kernel index, and its matching addresses."""
    title = f"{interface.name}  ·  index {interface.index}"
    return ft.Column(
        spacing=2,
        controls=[
            ft.Text(title, size=13, weight=ft.FontWeight.BOLD),
            *(address_row(a) for a in addresses_in(interface, family)),
            ft.Divider(height=1),
        ],
    )


def main(page: ft.Page):
    """Show what the kernel currently reports, and keep the screen in step with it."""
    state = {"family": "all", "unconfigured": False, "seen": None, "poll": 0}

    def refresh():
        """Re-enumerate, rebuild the list, and log every address that changed."""
        found, elapsed = scan(state["unconfigured"])
        now = fingerprint(found)
        if state["seen"] is not None:
            for line in reversed(changes(state["seen"], now)):
                log.controls.insert(0, ft.Text(line, size=11, font_family="monospace"))
            del log.controls[LOG_LINES:]
        state["seen"] = now
        cards.controls = [
            interface_card(i, state["family"])
            for i in found
            if state["unconfigured"] or addresses_in(i, state["family"])
        ]
        # Nothing at all is not the same answer as loopback-only: an empty scan is
        # what a wrong sockaddr layout looks like, not what a quiet network does.
        headline.value = (
            "no interfaces at all"
            if not found
            else lan_address(found) or "loopback and link-local only"
        )
        summary.value = summarise(found, elapsed)
        page.update()

    def on_family(e):
        """Filter by address family. In Flet 0.86 `selected` is a list, not a set."""
        state["family"] = e.control.selected[0]
        refresh()

    def on_unconfigured(e):
        """Also list interfaces that currently carry no address at all."""
        state["unconfigured"] = e.control.value
        refresh()

    def on_watch(e):
        """Start a poller, or retire the running one by bumping the generation."""
        state["poll"] += 1
        spinner.visible = e.control.value
        page.update()
        if e.control.value:
            page.run_thread(watch, state["poll"])

    def watch(generation):
        """Re-scan once a second until this poller is switched off or superseded.

        ifaddr has no change notification, so polling is the only way to see Wi-Fi
        come up or a VPN drop. `run_thread` hands this to a pool thread and holds
        that thread for as long as the loop runs — so flicking the switch off and
        straight back on inside one interval would leave the previous poller alive
        alongside the new one, which is what the generation check prevents. Flet
        discards whatever a background thread raises and never auto-updates from
        one, hence the try/except and the explicit `page.update()` at the end.
        """
        try:
            while True:
                time.sleep(1)
                if generation != state["poll"]:
                    break
                refresh()
        except Exception as exc:
            state["poll"] += 1
            watching.value = False
            spinner.visible = False
            summary.value = f"watch stopped: {exc}"
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Interface list"), center_title=True)
    body = [
        ft.Text(VERSION, size=11),
        headline := ft.Text(size=22, weight=ft.FontWeight.BOLD, selectable=True),
        summary := ft.Text(size=11),
        ft.Row(
            controls=[
                ft.SegmentedButton(
                    selected=["all"],
                    show_selected_icon=False,
                    segments=[ft.Segment(value=f, label=ft.Text(f)) for f in FAMILIES],
                    on_change=on_family,
                ),
                ft.Button("Rescan", icon=ft.Icons.REFRESH, on_click=refresh),
            ]
        ),
        ft.Switch(label="Include unconfigured interfaces", on_change=on_unconfigured),
        ft.Row(
            controls=[
                watching := ft.Switch(label="Watch for changes", on_change=on_watch),
                spinner := ft.ProgressRing(width=16, height=16, visible=False),
            ]
        ),
        cards := ft.Column(spacing=6),
        log := ft.Column(spacing=0),
    ]
    # Nothing in `body` may carry expand=True: on a scrolling Column's direct child
    # that collapses the whole viewport on iOS while Android renders it fine.
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(controls=body, scroll=ft.ScrollMode.AUTO),
        )
    )

    refresh()


if __name__ == "__main__":
    ft.run(main)
