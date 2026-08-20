import flet as ft
from server import HOST, ROUTES, VERSION, log, request, start, stop


def main(page: ft.Page):
    """An HTTP API served from inside the app, and called from inside the app."""

    def listen():
        """Bind the server if it is not up yet, and show the address it got.

        Both callers are worker threads -- the Send handler and the lifecycle
        rebind -- and page.run_thread drops whatever escapes one. A bind can
        genuinely fail on a device, so it is caught here: letting it propagate
        would leave the button disabled and the spinner turning with nothing
        on screen to say why.
        """
        try:
            address.value = f"http://{HOST}:{start()}"
        except Exception as exc:
            address.value = f"not listening — {type(exc).__name__}"
        page.update()

    def send(e=None):
        """Lock the controls, raise the spinner, hand the call to a worker thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(call)

    def call():
        """Make one request off the UI thread and show both sides of the exchange.

        The server log underneath is filled from the deque the handlers append to,
        so a reply on screen that is not matched by a new log line would mean the
        response came from somewhere other than this server.
        """
        listen()
        route = ROUTES[selector.selected[0]]
        try:
            result = request(route, note.value)
            sent.value = f"{route}\n{result['sent']}".strip()
            status.value = f"{result['status']}  ·  {result['elapsed']:.1f} ms"
            body.value = result["body"]
        except Exception as exc:  # run_thread drops anything that escapes here
            status.value = type(exc).__name__
            body.value = str(exc)
        history.controls = [ft.Text(entry, size=11) for entry in log()]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def on_lifecycle(e):
        """Drop the socket while the OS holds the app suspended, rebind on return.

        PAUSE and RESTART are delivered on Android and iOS only, so a desktop run
        keeps one server for its whole life. The address changes across the cycle:
        the port is whichever free one the kernel hands out on the next bind.
        """
        if e.state == ft.AppLifecycleState.PAUSE:
            stop()
        elif e.state == ft.AppLifecycleState.RESTART:
            page.run_thread(listen)

    page.appbar = ft.AppBar(title=ft.Text("Local server"), center_title=True)
    page.on_app_lifecycle_state_change = on_lifecycle
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(VERSION, size=12, expand=True),
                            address := ft.Text(size=12, color=ft.Colors.PRIMARY),
                        ]
                    ),
                    selector := ft.SegmentedButton(
                        selected=["status"],
                        show_selected_icon=False,
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name))
                            for name in ROUTES
                        ],
                        on_change=send,
                    ),
                    note := ft.TextField(
                        label="note — the body of the POST",
                        dense=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_submit=send,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Send", icon=ft.Icons.SEND, on_click=send
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                            status := ft.Text(size=12, expand=True),
                        ]
                    ),
                    ft.Container(
                        padding=12,
                        border_radius=8,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        content=ft.Column(
                            spacing=6,
                            controls=[
                                sent := ft.Text(size=11, color=ft.Colors.SECONDARY),
                                body := ft.Text(size=11, selectable=True),
                            ],
                        ),
                    ),
                    ft.Text("Server log, newest first", size=12),
                    history := ft.Column(spacing=2),
                ],
            ),
        )
    )

    send()


if __name__ == "__main__":
    ft.run(main)
