"""A websockets server and websockets' own client, streaming on 127.0.0.1 in Flet's loop."""

import hashlib
import json
import platform
import time
import timeit
from importlib.machinery import ExtensionFileLoader

import flet as ft
import websockets
import websockets.frames
import websockets.utils
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosedOK

MESSAGES = 200
PAYLOAD = bytes(range(256)) * 128
BENCH_BUFFER = bytes(range(256)) * 256
MASK = b"\x12\x34\x56\x78"


def detect_speedups():
    """Report whether the C frame-mask accelerator is the one websockets will use.

    The obvious test does not work. Upstream's `speedups.c` declares its module name as
    "websocket.speedups" — singular — so comparing `apply_mask.__module__` against
    "websockets.speedups" is False whether or not the extension loaded. What does
    discriminate: asking for the module at all, which is honest here because the package
    ships no same-named `.py` for the import to fall back on; confirming the import
    system loaded it as an extension, which holds on both platforms since iOS's
    AppleFrameworkLoader subclasses ExtensionFileLoader; and confirming that the name
    `frames.apply_mask` is bound to therefore is not the pure-Python one.
    """
    try:
        import websockets.speedups
    except ModuleNotFoundError:
        return False
    return (
        isinstance(websockets.speedups.__spec__.loader, ExtensionFileLoader)
        and websockets.frames.apply_mask is not websockets.utils.apply_mask
    )


def mask_speedup():
    """Time the masking websockets will really use against the pure-Python one.

    A stopwatch that has to agree with the boolean above: with the extension live the
    two names are different functions and the ratio is large, and without it they are
    the same function and it comes out at 1.
    """
    live = min(
        timeit.repeat(
            lambda: websockets.frames.apply_mask(BENCH_BUFFER, MASK), number=5, repeat=5
        )
    )
    pure = min(
        timeit.repeat(
            lambda: websockets.utils.apply_mask(BENCH_BUFFER, MASK), number=5, repeat=5
        )
    )
    return pure / live


async def feed(websocket):
    """Stream as many messages as the client asks for, then a hashed binary payload.

    One parameter, not two. The asyncio server calls its handler with the connection
    alone, so the `(websocket, path)` signature every pre-14.0 tutorial shows raises a
    TypeError here — and the client sees only a 1011 close that names nothing about a
    handler. The path, when you want it, is on `websocket.request.path`.

    The close is explicit and carries a code so that the client can distinguish a
    finished conversation from a dropped socket.
    """
    count = int(await websocket.recv())
    streamed = 0
    for index in range(count):
        line = json.dumps({"i": index, "v": (index * 37) % 1000 + index})
        await websocket.send(line)
        streamed += len(line.encode())
    await websocket.send(
        json.dumps(
            {
                "messages": count,
                "bytes": streamed,
                "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
                "payload_bytes": len(PAYLOAD),
            }
        )
    )
    await websocket.send(PAYLOAD)
    await websocket.close(1001, "feed complete")


async def collect(uri, count, arrived):
    """Hold one client conversation and return everything the screen reports.

    The order is deliberate. The ping goes first, on an otherwise idle connection,
    because the server closes as soon as the payload is out and a later ping would race
    that close. The final `recv` is *expected* to raise: a graceful close reaches the
    client as ConnectionClosedOK, and only after it has arrived are `close_code` and
    `close_reason` readable.
    """
    async with connect(uri, proxy=None) as websocket:
        result = {
            "ping_ms": (await (await websocket.ping())) * 1000.0,
            "latency_ms": websocket.latency * 1000.0,
            "extensions": [
                f"{extension.name} ({extension.remote_max_window_bits}-bit windows)"
                for extension in websocket.protocol.extensions
            ],
        }

        await websocket.send(str(count))
        result["received"] = 0
        result["received_bytes"] = 0
        for _ in range(count):
            message = await websocket.recv()
            result["received"] += 1
            result["received_bytes"] += len(message.encode())
            arrived(message)

        summary = await websocket.recv()
        result["summary_type"] = type(summary).__name__
        result["summary"] = json.loads(summary)

        payload = await websocket.recv()
        result["payload_type"] = type(payload).__name__
        result["payload_bytes"] = len(payload)
        result["payload_sha256"] = hashlib.sha256(payload).hexdigest()

        try:
            await websocket.recv()
        except ConnectionClosedOK:
            pass
        result["close_code"] = websocket.close_code
        result["close_reason"] = websocket.close_reason
    return result


def checks_from(result, count):
    """Turn one conversation into the six (label, verdict, detail) rows on screen."""
    summary = result["summary"]
    return [
        (
            "ping / pong",
            result["ping_ms"] == result["latency_ms"],
            f"round trip {result['ping_ms']:.3f} ms · connection.latency "
            f"{result['latency_ms']:.3f} ms",
        ),
        (
            "streamed feed",
            summary["messages"] == result["received"] == count
            and summary["bytes"] == result["received_bytes"],
            f"server sent {summary['messages']:,} msg / {summary['bytes']:,} B · "
            f"client read {result['received']:,} msg / {result['received_bytes']:,} B",
        ),
        (
            "payload integrity",
            summary["sha256"] == result["payload_sha256"]
            and summary["payload_bytes"] == result["payload_bytes"],
            f"sha256 {result['payload_sha256'][:16]}… recomputed over "
            f"{result['payload_bytes']:,} B",
        ),
        (
            "frame types",
            (result["summary_type"], result["payload_type"]) == ("str", "bytes"),
            f"summary arrived as {result['summary_type']} · payload as "
            f"{result['payload_type']}",
        ),
        (
            "compression",
            bool(result["extensions"]),
            " · ".join(result["extensions"]) or "none negotiated",
        ),
        (
            "graceful close",
            result["close_code"] == 1001,
            f"{result['close_code']} · {result['close_reason']!r}",
        ),
    ]


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

    `await serve(...)` returns as soon as the socket is bound and `main` then *returns* —
    Flet awaits main to completion before its first post-main update, so parking here to
    keep the server alive would strand the first render. The server goes on serving from
    the same loop afterwards.

    Whether the OS lets an app listen at all is the one thing here that only a device can
    settle, so the bind is the one call that has to fail *on screen*: an exception out of
    `main` reaches Flet as a crash screen, which would replace the answer with nothing.
    """
    try:
        server = await serve(feed, "127.0.0.1", 0)
    except OSError as error:
        uri, refused = None, f"{type(error).__name__}: {error}"
    else:
        uri = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
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

    speedups = detect_speedups()
    ratio = mask_speedup()
    page.appbar = ft.AppBar(
        title=ft.Text("websockets loopback feed"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"websockets {websockets.__version__} — Python "
                        f"{platform.python_version()} on {page.platform.value} — masking "
                        f"{'C extension' if speedups else 'pure Python'} "
                        f"({ratio:.0f}x)",
                        size=12,
                    ),
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
