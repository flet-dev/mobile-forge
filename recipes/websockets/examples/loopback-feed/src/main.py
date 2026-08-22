import time

import flet as ft
from loopback import MESSAGES, VERSION, checks_from, collect, masking, serve_feed


def check_row(label, ok, detail):
    """One check on screen: verdict and label on top, the detail wrapping below.

    Two lines rather than one wide Row on purpose — the details are long enough that a
    single non-scrolling Row would overflow a phone's width into Flutter's striped
    marker.
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
                ]
            ),
            ft.Text(detail, size=11),
        ],
    )


async def main(page: ft.Page):
    """Serve a feed on loopback, then run one client conversation against it.

    `serve_feed()` returns as soon as the socket is bound and `main` then *returns* —
    Flet awaits main to completion before its first post-main update, so parking here to
    keep the server alive would strand the first render. The server goes on serving from
    the same loop afterwards.

    Whether the OS lets an app listen at all is the one thing here that only a device can
    settle, so the bind is the one call that has to fail *on screen*: an exception out of
    `main` reaches Flet as a crash screen, which would replace the answer with nothing.
    """
    try:
        uri = await serve_feed()
    except OSError as error:
        uri, refused = None, f"{type(error).__name__}: {error}"
    else:
        refused = None

    def arrived(message):
        """Put one streamed message in the feed, refreshing every twentieth.

        A page.update() per message would be hundreds of round trips to the client for
        one run; a batch of twenty still reads as live at a twentieth of the traffic.
        """
        feed_view.controls.append(ft.Text(message, size=10))
        if len(feed_view.controls) % 20 == 0:
            page.update()

    async def run_feed():
        """Run one conversation and lay the result out; the caller disables the slider.

        Re-enabling it is this function's job, in a `finally`, so a failed run does not
        leave the screen permanently stuck. The body ends with an explicit page.update()
        because `page.run_task` does not get the auto-update an event handler does.
        """
        count = int(slider.value)
        feed_view.controls = []
        results.controls = []
        footer.value = f"streaming {count:,} messages…"
        page.update()

        started = time.perf_counter()
        try:
            result = await collect(uri, count, arrived)
            checks = checks_from(result, count)
        except Exception as error:
            results.controls = [
                check_row("run failed", False, f"{type(error).__name__}: {error}")
            ]
            footer.value = ""
        else:
            elapsed = (time.perf_counter() - started) * 1000.0
            results.controls = [check_row(*check) for check in checks]
            streamed, payload = result["received_bytes"], result["payload_bytes"]
            footer.value = (
                f"{sum(ok for _, ok, _ in checks)}/{len(checks)} checks passed · "
                f"{result['received']:,} messages · {streamed:,} B streamed + "
                f"{payload:,} B payload = {streamed + payload:,} B in {elapsed:.1f} ms"
            )
        finally:
            slider.disabled = False
            page.update()

    def describe():
        """Keep the caption in step with the slider, which moves as it is dragged."""
        caption.value = f"{int(slider.value):,} messages per run"

    def rerun():
        """Start a run on the slider's release, guarding against a second one.

        The disable happens here rather than inside `run_feed`: `page.run_task` only
        schedules, so a `disabled` set in the coroutine has not happened yet when this
        handler returns and Flet pushes the slider's new state. Two runs sharing one feed
        interleave their messages and the totals stop adding up.
        """
        if slider.disabled:
            return
        slider.disabled = True
        page.run_task(run_feed)

    page.appbar = ft.AppBar(title=ft.Text("websockets loopback feed"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(f"{VERSION} on {page.platform.value} — {masking()}", size=12),
                    ft.Text(f"serving {uri}" if uri else "not serving", size=12),
                    caption := ft.Text(f"{MESSAGES:,} messages per run"),
                    slider := ft.Slider(
                        min=10,
                        max=500,
                        value=MESSAGES,
                        divisions=49,
                        label="{value} messages",
                        on_change=describe,
                        on_change_end=rerun,
                    ),
                    feed_view := ft.ListView(height=180, spacing=1, auto_scroll=True),
                    results := ft.Column(spacing=8),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    slider.disabled = True
    if uri is None:
        results.controls = [check_row("listening socket", False, refused)]
        page.update()
        return
    await run_feed()


if __name__ == "__main__":
    ft.run(main)
