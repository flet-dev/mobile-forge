import flet as ft
from probe import (
    DEFAULT_DSN,
    IMPORT_ERROR,
    attempt,
    driver,
    features,
    literals,
    normalise,
)


def pair(label, value):
    """One label/value line. Both cells wrap, so a long libpq message stays whole."""
    return ft.Row(
        vertical_alignment=ft.CrossAxisAlignment.START,
        controls=[
            ft.Text(label, size=11, expand=2),
            ft.Text(value, size=11, expand=3, selectable=True),
        ],
    )


def marked(icon, colour, *controls):
    """A row led by a coloured icon — the feature dots and the transport padlock."""
    return ft.Row(
        vertical_alignment=ft.CrossAxisAlignment.START,
        controls=[ft.Icon(icon, size=12, color=colour), *controls],
    )


def flag(label, present, said):
    """A compiled-in feature: a dot, the verdict, and the sentence libpq answered."""
    return marked(
        ft.Icons.CIRCLE,
        ft.Colors.GREEN if present else ft.Colors.RED,
        ft.Text(f"{label}: {'yes' if present else 'no'}", size=11, expand=2),
        ft.Text(said, size=10, italic=True, expand=3),
    )


def heading(text):
    """A section title inside the scrolling column."""
    return ft.Text(text, size=12, weight=ft.FontWeight.BOLD)


def main(page: ft.Page):
    """Read what this wheel contains, then probe one connection string against it.

    Everything on screen is computed on the device and none of it needs a server.
    The driver facts and the feature flags are read out of the binary at startup;
    the probe below parses a connection string and then shows what a connection
    that cannot be made actually raises.
    """

    def start(event=None):
        """Lock the controls, show the spinner, hand the probe to a worker thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Parse the connection string and try it, off the UI thread.

        libpq blocks the thread it is called on for as long as `connect_timeout`
        allows — drop that keyword, point the string at an address that swallows
        packets, and this worker is gone until the operating system gives up on
        the socket. The body is wrapped whole because `page.run_thread` swallows
        exceptions: an unhandled one leaves the button disabled and the spinner
        turning for good. A keyword libpq does not know reaches this handler.
        """
        try:
            results.controls = report(dsn.value)
        except Exception as error:
            message = " ".join(str(error).split())
            results.controls = [pair("raised", f"{type(error).__name__}: {message}")]
        finally:
            button.disabled = False
            spinner.visible = False
            page.update()

    def report(text):
        """Rows for one connection string: keywords, libpq's defaults, the failure."""
        keywords, filled, (verdict, safe) = normalise(text)
        return [
            heading("keywords libpq read out of it"),
            *(pair(key, value) for key, value in keywords.items()),
            heading("left unset, so libpq supplies"),
            *(pair(key, value) for key, value in filled),
            marked(
                ft.Icons.LOCK if safe else ft.Icons.LOCK_OPEN,
                ft.Colors.GREEN if safe else ft.Colors.ORANGE,
                ft.Text(verdict, size=11, expand=True),
            ),
            heading("what connecting to it raises"),
            *(pair(key, value) for key, value in attempt(text)),
        ]

    page.appbar = ft.AppBar(title=ft.Text("psycopg2 libpq probe"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    facts := ft.Column(spacing=2),
                    ft.Divider(),
                    flags := ft.Column(spacing=8),
                    ft.Divider(),
                    dsn := ft.TextField(
                        label="connection string",
                        value=DEFAULT_DSN,
                        multiline=True,
                        text_size=11,
                        on_submit=start,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Probe", icon=ft.Icons.PLAY_ARROW, on_click=start
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=2),
                    ft.Divider(),
                    types := ft.Column(spacing=2),
                ],
            ),
        )
    )

    if IMPORT_ERROR:
        facts.controls = [
            heading("psycopg2 did not import"),
            pair("error", IMPORT_ERROR),
            pair("why", "it is declared under [tool.flet.android] and [tool.flet.ios]"),
        ]
        button.disabled = dsn.disabled = True
        page.update()
        return

    facts.controls = [heading("driver"), *(pair(*fact) for fact in driver())]
    flags.controls = [
        heading("compiled into this wheel"),
        *(flag(*found) for found in features()),
    ]
    types.controls = [
        heading("Python value → SQL literal, with no connection"),
        *(pair(*row) for row in literals()),
    ]
    start()


if __name__ == "__main__":
    ft.run(main)
