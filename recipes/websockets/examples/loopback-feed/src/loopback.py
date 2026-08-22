"""The websockets half of the example: a loopback server, and one client conversation."""

import hashlib
import json
import platform
import timeit
from importlib.machinery import ExtensionFileLoader

import websockets
import websockets.frames
import websockets.utils
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosedOK

# Loopback, and only loopback: nothing leaves the device and it works in airplane mode.
# Port 0 asks the kernel for a free one — a fixed port is what actually fails on a phone.
HOST = "127.0.0.1"
PORT = 0
MESSAGES = 200
PAYLOAD = bytes(range(256)) * 128
BENCH_BUFFER = bytes(range(256)) * 256
MASK = b"\x12\x34\x56\x78"

VERSION = f"websockets {websockets.__version__} — Python {platform.python_version()}"


def detect_speedups():
    """Report whether the C frame-mask accelerator is the one websockets will use.

    The obvious test does not work. Upstream's `speedups.c` declares its module name as
    "websocket.speedups" — singular — so comparing `apply_mask.__module__` against
    "websockets.speedups" is False whether or not the extension loaded. What does
    discriminate: asking for the module at all, which is honest here because the package
    ships no same-named `.py` for the import to fall back on; confirming the import
    system loaded it as an extension, which holds on both platforms since iOS's
    AppleFrameworkLoader subclasses ExtensionFileLoader; and confirming that the name
    `frames.apply_mask` is bound to is therefore not the pure-Python one.
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


def masking():
    """Summarise the accelerator verdict and its measured ratio, for the header line.

    Both halves on one line on purpose: a large ratio next to "pure Python" would mean
    the check and the stopwatch disagree, which is the only reading of this screen that
    should be treated as a bug in the app rather than in the build.
    """
    kind = "C extension" if detect_speedups() else "pure Python"
    return f"masking {kind} ({mask_speedup():.0f}x)"


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


async def serve_feed():
    """Bind the feed on an ephemeral loopback port and return the URI to dial.

    `await serve(...)` returns as soon as the socket is bound and the server goes on
    serving from the same loop, so the caller can render straight away. Not
    `async with serve(...)`: its `__aexit__` closes the server the instant the block
    ends. Raises OSError if the platform refuses the listening socket, which is the one
    failure here that only a device can produce.
    """
    server = await serve(feed, HOST, PORT)
    return f"ws://{HOST}:{server.sockets[0].getsockname()[1]}/"


async def collect(uri, count, arrived):
    """Hold one client conversation and return everything the screen reports.

    The order is deliberate. The ping goes first, on an otherwise idle connection,
    because the server closes as soon as the payload is out and a later ping would race
    that close. The final `recv` is *expected* to raise: a graceful close reaches the
    client as ConnectionClosedOK, and only after it has arrived are `close_code` and
    `close_reason` readable.

    `proxy=None` skips the system proxy lookup a client connect does by default; on
    loopback there is nothing for it to find and the call is unambiguous without it.
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
