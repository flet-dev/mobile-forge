import flet as ft
from vectors import (
    HEADER,
    check_all,
    describe,
    device_facts,
    hexed,
    open_sealed,
    seal,
    time_kdfs,
)


def line(text, color=None, expand=None):
    """One monospaced result line.

    Pass `expand` when the line sits in a `Row`: a `Text` there is given unbounded
    width, so a long label stops wrapping and paints Flutter's OVERFLOWED stripes down
    the edge of a phone instead. Inside a `Column` it wraps already, and `expand` there
    would make it swallow the column's spare height.
    """
    return ft.Text(
        text,
        size=11,
        color=color,
        expand=expand,
        font_family="monospace",
        font_family_fallback=["Courier"],
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def verdict(label, source, passed, got, expected):
    """One vector's rows: a tick or cross, then the value, or both when it fails."""
    head = ft.Row(
        spacing=6,
        controls=[
            ft.Icon(
                ft.Icons.CHECK_CIRCLE if passed else ft.Icons.CANCEL,
                color=ft.Colors.GREEN if passed else ft.Colors.RED,
                size=14,
            ),
            line(f"{label} - {source}", expand=True),
        ],
    )
    if passed:
        return [head, line(f"  {got[:28]}..." if len(got) > 28 else f"  {got}")]
    # Both values in full on a failing row: clipped to the same width, two hex strings
    # that diverge only in the tail look identical.
    return [
        head,
        line(f"  got  {got}", ft.Colors.RED),
        line(f"  want {expected}", ft.Colors.RED),
    ]


def main(page: ft.Page):
    """Three panels: a known-answer table, an AEAD round trip, and a KDF cost sweep."""
    sealed = {}

    def startup():
        """Fill both computed panels as one background job.

        One `run_thread` unit rather than two: pycryptodome releases the GIL for the
        duration of each bulk call, so the whole batch is what benefits from being off
        the UI thread, and splitting it would only add a second worker for the shared
        scrypt allocation to collide with.
        """
        table.controls = [c for row in check_all() for c in verdict(*row)]
        page.update()  # auto-update does not reach background threads
        resweep()

    def resweep():
        """Re-time the KDFs at the slider's N and redraw the timings."""
        try:
            timings.controls = [line(text) for text in time_kdfs(int(cost.value))]
        except Exception as err:
            timings.controls = [line(describe(err), ft.Colors.RED)]
        page.update()

    def on_cost():
        """Hand the sweep to a background thread, since a KDF is deliberately slow."""
        page.run_thread(resweep)

    def on_seal():
        """Seal the typed message and show the nonce, ciphertext and tag it produced."""
        try:
            sealed.update(seal(message.value or ""))
            box.controls = [
                line(f"{'nonce':<7}{hexed(sealed['nonce'], keep=64)}"),
                line(f"{'cipher':<7}{hexed(sealed['ciphertext'])}"),
                line(f"{'tag':<7}{hexed(sealed['tag'], keep=64)}"),
            ]
            opened.value = ""
        except Exception as err:
            box.controls = [line(describe(err), ft.Colors.RED)]
        page.update()

    def unseal(flip):
        """Open the sealed message, with `flip` deciding whether a tag bit is corrupted.

        Catching is not optional: an unhandled exception in a Flet event handler ends
        the session with a crash screen instead of showing which call broke — and
        `sealed` is empty if the seal above failed, so the lookup belongs in the `try`.
        """
        try:
            opened.value = "-> " + open_sealed(sealed, flip)
            opened.color = None
        except Exception as err:
            opened.value = "-> " + describe(err)
            opened.color = ft.Colors.RED
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("Known answers"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=6,
                controls=[
                    line(HEADER),
                    *(line(f"{label:<9}{value}") for label, value in device_facts()),
                    ft.Divider(),
                    heading("Published vectors, recomputed here"),
                    table := ft.Column(spacing=2, controls=[line("computing...")]),
                    ft.Divider(),
                    heading("Seal and open, AES-256-GCM"),
                    message := ft.TextField(
                        label="Message",
                        value="hello mobile-forge",
                        dense=True,
                        autocorrect=False,
                        capitalization=ft.TextCapitalization.NONE,
                        on_submit=on_seal,
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=6,
                        controls=[
                            ft.Button("Seal", on_click=on_seal),
                            ft.Button("Open", on_click=lambda: unseal(False)),
                            ft.Button("Flip a tag bit", on_click=lambda: unseal(True)),
                        ],
                    ),
                    box := ft.Column(spacing=2),
                    opened := line(""),
                    ft.Divider(),
                    heading("What a password KDF costs on this device"),
                    cost := ft.Slider(
                        min=12,
                        max=17,
                        divisions=5,
                        value=14,
                        label="scrypt N=2^{value}",
                        # on_change would re-derive for every step the thumb travels.
                        on_change_end=on_cost,
                    ),
                    timings := ft.Column(spacing=2, controls=[line("measuring...")]),
                ],
            ),
        )
    )

    on_seal()
    page.run_thread(startup)


if __name__ == "__main__":
    ft.run(main)
