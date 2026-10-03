import platform
import sys

import flet as ft
from station import SENSORS, batch, codec_rows, native_codec, start_server, submit
from telemetry.ttypes import InvalidReading
from thrift.Thrift import TException


def cell(text, width, color=None):
    """One fixed-width monospace table cell."""
    return ft.Container(
        width=width,
        content=ft.Text(text, size=11, color=color, font_family="monospace"),
    )


def rate(per_second):
    """Round trips per second, abbreviated: 41200 -> '41.2k', 180 -> '180'."""
    if per_second is None:
        return "—"
    return f"{per_second / 1000:.1f}k" if per_second >= 1000 else f"{per_second:.0f}"


def row_for(name, size, fast, pure):
    """One protocol: wire bytes, native and pure-Python round trips/s, and the gain."""
    gain = f"{fast / pure:.1f}x" if fast else ""
    return ft.Row(
        controls=[
            cell(name, 64),
            cell(f"{size:,} B", 70),
            cell(rate(fast), 56, ft.Colors.GREEN),
            cell(rate(pure), 56),
            cell(gain, 48, ft.Colors.BLUE),
        ]
    )


def main(page: ft.Page):
    """Start the in-app Thrift server, then call it and benchmark the protocols."""
    port = start_server()
    native = native_codec()

    def calls():
        """A good call and a rejected one. Network failures raise TException."""
        summary, ms = submit(port, batch())
        call.value = (
            f"submit({summary.count} readings) in {ms:.1f} ms\n"
            f"mean {summary.mean_celsius:.1f} °C, warmest {summary.warmest_sensor} "
            f"at {summary.max_celsius:.1f} °C"
        )
        try:
            submit(port, batch(bad_sensor="s07"))
            rejected.value = "bad reading was accepted"
        except InvalidReading as err:
            rejected.value = f"InvalidReading({err.sensor}): {err.reason}"

    def run():
        """The calls and the codec table, off the UI thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        try:
            calls()
        except TException as err:  # refused, timed out, wrong framing, bad certificate
            call.value = f"{type(err).__name__}: {err}"
            rejected.value = ""

        table.controls = [
            ft.Row(
                controls=[
                    cell("", 64),
                    cell("size", 70),
                    cell("native", 56),
                    cell("pure", 56),
                    cell("gain", 48),
                ]
            ),
            ft.Divider(height=1),
            *(row_for(*row) for row in codec_rows(batch())),
        ]

        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("thrift telemetry"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"Python {platform.python_version()} on {sys.platform} · "
                        + ("native fastbinary codec" if native else "pure Python only"),
                        size=11,
                        color=ft.Colors.GREEN if native else ft.Colors.ORANGE,
                    ),
                    ft.Text(f"RPC to 127.0.0.1:{port}", weight=ft.FontWeight.BOLD),
                    call := ft.Text("calling…"),
                    rejected := ft.Text(color=ft.Colors.ORANGE),
                    ft.Divider(),
                    ft.Text(
                        f"submit() payload, {SENSORS} readings, round trips/s",
                        weight=ft.FontWeight.BOLD,
                    ),
                    table := ft.Column(spacing=2),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Run again", on_click=lambda: page.run_thread(run)
                            ),
                            spinner := ft.ProgressRing(
                                visible=False, width=18, height=18
                            ),
                        ]
                    ),
                ],
            ),
        )
    )
    page.run_thread(run)


ft.run(main)
