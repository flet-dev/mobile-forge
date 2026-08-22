import flet as ft
from loopback import CHECKS, ROWS, VERSION, accelerators, run_checks, start


def check_row(label, ok, detail, elapsed):
    """One check on screen: verdict and timing on one line, the detail wrapping below.

    Two lines rather than a wide Row on purpose — the details are long enough that a
    single non-scrolling Row would overflow a phone's width.
    """
    return ft.Column(
        spacing=2,
        controls=[
            ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.CHECK_CIRCLE if ok else ft.Icons.ERROR,
                        color=ft.Colors.GREEN if ok else ft.Colors.RED,
                        size=16,
                    ),
                    ft.Text(label, expand=True, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{elapsed:.1f} ms"),
                ]
            ),
            ft.Text(detail, size=11),
        ],
    )


async def main(page: ft.Page):
    """Serve four endpoints on loopback, then run six checks against them.

    The server is started here and `main` then *returns*. Flet awaits `main` to
    completion before its first post-main update, so parking the coroutine to keep the
    server alive — `await asyncio.Event().wait()`, say — would strand the first render;
    the runner goes on serving from the same loop once `main` has returned.
    """
    base_url = await start()

    async def run_suite():
        """Lay out one result row per check as it lands, then total what is on screen.

        The body ends with `page.update()` because `page.run_task` does not trigger the
        auto-update an event handler gets, and the `finally` releases the slider even
        when the session itself failed to open.
        """
        n = int(slider.value)
        slider.disabled = True
        results.controls = []
        footer.value = f"running {n:,} rows…"
        page.update()

        passed = 0
        total = 0.0
        try:
            async for label, ok, detail, elapsed in run_checks(base_url, n):
                passed += ok
                total += elapsed
                results.controls.append(check_row(label, ok, detail, elapsed))
                page.update()
            footer.value = (
                f"{passed}/{len(CHECKS)} checks passed · {total:.1f} ms in total"
            )
        finally:
            slider.disabled = False
            page.update()

    def describe():
        """Keep the caption in step with the slider, which moves as it is dragged."""
        caption.value = f"{int(slider.value):,} rows per response"

    def rerun():
        """Re-run the suite on the slider's release, on the loop the server is on.

        `page.run_task` and not `page.run_thread`: a thread gets no event loop, and
        `run_thread` discards whatever its worker raises, so an aiohttp failure there
        would surface nowhere at all.

        The disable has to happen *here*, and be read back as the guard, because
        `run_task` only schedules `run_suite`: a `disabled` set inside it has not
        happened yet when this handler returns and Flet pushes the slider's new state, so
        a second release arriving in that window queues a second run. Two runs sharing
        one `results` column interleave into twelve rows under a footer that counts six.
        """
        if slider.disabled:
            return
        slider.disabled = True
        page.run_task(run_suite)

    page.appbar = ft.AppBar(title=ft.Text("aiohttp loopback"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"{VERSION} on {page.platform.value} — {accelerators()}",
                        size=12,
                    ),
                    ft.Text(f"serving {base_url}", size=12),
                    caption := ft.Text(f"{ROWS:,} rows per response"),
                    slider := ft.Slider(
                        min=100,
                        max=5000,
                        value=ROWS,
                        divisions=49,
                        label="{value} rows",
                        on_change=describe,
                        on_change_end=rerun,
                    ),
                    results := ft.Column(spacing=8),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    await run_suite()


if __name__ == "__main__":
    ft.run(main)
