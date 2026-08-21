import flet as ft
from summaries import (
    BENCHMARK_LOOKUPS,
    RECORDS,
    VERSION,
    accelerator,
    lookup_rate,
    summarise,
    use_event_adapter,
    verify_candidates,
)


def registry_row(result):
    """One record: its own claim, the adapter the registry chose, the output."""
    chose = f"{result['record']} declares {result['declares']}  →  {result['resolved']}"
    return ft.Column(
        spacing=1,
        controls=[
            ft.Text(result["headline"], size=13, weight=ft.FontWeight.W_600),
            ft.Text(chose, size=11, color=ft.Colors.PRIMARY),
            ft.Text(result["detail"], size=11, color=ft.Colors.OUTLINE),
        ],
    )


def verification_row(name, ok, message):
    """One candidate: a verdict, then whatever verifyObject had to say about it.

    The message is quoted rather than summarised, because naming the attribute
    or the signature at fault is the whole reason to run the check.
    """
    return ft.Column(
        spacing=1,
        controls=[
            ft.Text(
                f"{'✓' if ok else '✗'}  {name}",
                size=12,
                weight=ft.FontWeight.W_600,
                color=ft.Colors.GREEN if ok else ft.Colors.ERROR,
            ),
            ft.Text(message, size=10, color=ft.Colors.OUTLINE),
        ],
    )


def main(page: ft.Page):
    """Two panels: what the registry resolved, and what verification rejected.

    Both are filled before the first frame, so the screen already answers the
    question the app exists to ask instead of waiting for a tap.
    """

    def redraw():
        """Adapt every record again and rebuild the registry panel from scratch."""
        rows.controls = [registry_row(summarise(r)) for r in RECORDS]
        page.update()

    def on_toggle(e):
        """Register or withdraw the IEvent adapter, then repeat every lookup.

        Nothing about the records changes here, only the registry — and the Event
        row moves to a different adapter class because of it.
        """
        use_event_adapter(e.control.value)
        redraw()

    def on_measure(e):
        """Start the benchmark on a worker thread, with the button disabled."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(measure)

    def measure():
        """Time the lookups and report, re-enabling the button whatever happens.

        A worker that raises without this guard leaves the button disabled and
        the spinner turning for the rest of the session.
        """
        try:
            elapsed, rate = lookup_rate()
            bench.value = (
                f"{rate:,.0f} lookups/s · "
                f"{BENCHMARK_LOOKUPS:,} in {elapsed * 1e3:.0f} ms"
            )
        except Exception as exc:
            bench.value = str(exc)
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    live, module = accelerator()
    page.appbar = ft.AppBar(title=ft.Text("Interface registry"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"{VERSION} · {'compiled' if live else 'pure Python'} "
                        f"lookups, from {module}",
                        size=11,
                    ),
                    ft.Divider(),
                    ft.Text("Adapter registry", weight=ft.FontWeight.BOLD),
                    ft.Switch(label="Register an IEvent adapter", on_change=on_toggle),
                    rows := ft.Column(spacing=10),
                    ft.Divider(),
                    ft.Text("Runtime verification", weight=ft.FontWeight.BOLD),
                    ft.Column(
                        spacing=10,
                        controls=[verification_row(*c) for c in verify_candidates()],
                    ),
                    ft.Divider(),
                    ft.Row(
                        controls=[
                            button := ft.FilledTonalButton(
                                f"Time {BENCHMARK_LOOKUPS:,} lookups",
                                on_click=on_measure,
                            ),
                            spinner := ft.ProgressRing(
                                width=14, height=14, visible=False
                            ),
                        ]
                    ),
                    bench := ft.Text(size=11, color=ft.Colors.OUTLINE),
                ],
            ),
        )
    )
    redraw()


if __name__ == "__main__":
    ft.run(main)
