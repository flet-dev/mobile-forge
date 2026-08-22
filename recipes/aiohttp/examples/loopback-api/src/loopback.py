"""The aiohttp half of the example: a loopback server, and the client checks against it."""

import json
import platform
import sys
import time
from importlib.machinery import ExtensionFileLoader

import aiohttp
from aiohttp import http_parser, http_writer, web
from aiohttp._websocket import helpers as ws_helpers
from aiohttp._websocket import reader as ws_reader

# Loopback, and only loopback: nothing leaves the device, and it works in airplane mode.
# Port 0 asks the kernel for a free one — a fixed port is what actually fails on a phone.
HOST = "127.0.0.1"
PORT = 0
ROWS = 2000
GREETING = "aiohttp on a phone"
BLOB = bytes(range(256)) * 48

# Not inherited: aiohttp's default is five minutes with no read timeout at all, which on
# a phone means a request still counting down long after the user gave up on it.
TIMEOUT = aiohttp.ClientTimeout(total=30)

VERSION = f"aiohttp {aiohttp.__version__} — Python {platform.python_version()}"

# aiohttp exposes no public flag for whether its four compiled accelerators are in use.
# Three are identified by the private name their pure-Python twin would be bound to. The
# WebSocket reader cannot be: the wheel ships a pure-Python `_websocket/reader_c.py`
# alongside the compiled `reader_c` extension, so a fallback binds the same class out of
# the *same* module name and `WebSocketReader.__module__` reads "…reader_c" either way.
# Asking the import system what loaded that module does separate them — the loader is an
# ExtensionFileLoader (iOS's AppleFrameworkLoader subclasses it) only when the native
# module won, and a SourceFileLoader or zipimporter when the .py did.
# Worth printing on screen: a fallback returns identical results, and both pure-Python
# twins are fast enough that none of the timings below would move either.
ACCELERATORS = {
    "parser": http_parser.HttpRequestParser is not http_parser.HttpRequestParserPy,
    "writer": http_writer._serialize_headers is not http_writer._py_serialize_headers,
    "ws-mask": ws_helpers.websocket_mask is not ws_helpers._websocket_mask_python,
    "ws-reader": isinstance(
        sys.modules[ws_reader.WebSocketReader.__module__].__loader__,
        ExtensionFileLoader,
    ),
}


def accelerators():
    """Summarise which of the four compiled extensions are live, for the header line."""
    live = ", ".join(name for name, ok in ACCELERATORS.items() if ok) or "none"
    return f"C speedups {sum(ACCELERATORS.values())}/{len(ACCELERATORS)} ({live})"


def rows(n):
    """Build `n` deterministic rows, so every install produces the same numbers."""
    return [{"i": i, "v": (i * 37) % 1000 + i} for i in range(n)]


async def serve_rows(request):
    """Answer with a JSON array of rows, gzipped when the query string asks for it."""
    response = web.json_response(rows(int(request.query["n"])))
    if "gzip" in request.query:
        # force= pins the codec. A bare enable_compression() negotiates against the
        # request's Accept-Encoding and picks deflate, because aiohttp's *server* side
        # implements only deflate, gzip and identity — the zstd the client advertises on
        # Python 3.14 is a decoder, not something this server can produce.
        response.enable_compression(force=web.ContentCoding.gzip)
    return response


async def serve_sum(request):
    """Add up the `v` field of a posted row list, for the client to check."""
    posted = await request.json()
    return web.json_response({"n": len(posted), "sum": sum(r["v"] for r in posted)})


async def serve_stream(request):
    """Write the rows out as one JSON object per line, with no Content-Length.

    A StreamResponse whose length is unknown when the headers go out is sent chunked,
    which is the case the client's `iter_chunked` reader is for.
    """
    response = web.StreamResponse()
    response.content_type = "application/x-ndjson"
    await response.prepare(request)
    for row in rows(int(request.query["n"])):
        await response.write(json.dumps(row).encode() + b"\n")
    await response.write_eof()
    return response


async def serve_websocket(request):
    """Echo every frame back — text reversed, binary unchanged.

    The loop ends when the client closes the socket, at which point returning the
    prepared response completes the handler.
    """
    socket = web.WebSocketResponse()
    await socket.prepare(request)
    async for message in socket:
        if message.type is aiohttp.WSMsgType.TEXT:
            await socket.send_str(message.data[::-1])
        elif message.type is aiohttp.WSMsgType.BINARY:
            await socket.send_bytes(message.data)
    return socket


async def start():
    """Bind the four endpoints on an ephemeral loopback port and return the base URL.

    The runner API rather than `web.run_app`, which drives the loop itself and cannot be
    used inside Flet's already-running one. This returns as soon as the socket is bound,
    so the caller can go on and render; the server keeps serving from the same loop.
    `access_log=None` drops the line aiohttp would otherwise log per request, which on a
    device is pure cost. There is no matching `runner.cleanup()` anywhere in this app:
    the server is meant to live as long as the process.
    """
    server = web.Application()
    server.add_routes(
        [
            web.get("/rows", serve_rows),
            web.post("/sum", serve_sum),
            web.get("/stream", serve_stream),
            web.get("/ws", serve_websocket),
        ]
    )
    runner = web.AppRunner(server, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    return site.name


async def check_json(client, n, carried):
    """GET the row array, and keep it for the POST check to send back."""
    async with client.get("/rows", params={"n": n}) as response:
        body = await response.read()
    carried["rows"] = json.loads(body)
    ok = response.status == 200 and len(carried["rows"]) == n
    return ok, f"{response.status} · {len(carried['rows']):,} rows · {len(body):,} B"


async def check_gzip(client, n, carried):
    """GET the same array gzipped, and confirm it decoded back to the same rows.

    Nothing in the client asks for this: aiohttp advertises its codecs in
    Accept-Encoding and inflates the body before `read()` returns, so the only
    evidence it happened is the header and the size gap this reports.
    """
    async with client.get("/rows", params={"n": n, "gzip": 1}) as response:
        body = await response.read()
    coding = response.headers.get("Content-Encoding")
    offered = response.request_info.headers.get("Accept-Encoding")
    wire = response.content_length
    ok = coding == "gzip" and json.loads(body) == carried["rows"]
    # A Response holding plain bytes is compressed whole, so Content-Length is the
    # compressed size. A chunked or Payload body is compressed as it streams instead and
    # declares no length at all, which is why the wire figure has to be optional.
    measured = (
        f"{wire:,} B on the wire → {len(body):,} B decoded "
        f"({len(body) / wire:.1f}x smaller)"
        if wire
        else f"{len(body):,} B decoded, wire size not declared"
    )
    return ok, f"{coding} · {measured} · offered {offered}"


async def check_post(client, n, carried):
    """POST the rows back, and check the server's total against one computed here."""
    expected = sum(row["v"] for row in carried["rows"])
    async with client.post("/sum", json=carried["rows"]) as response:
        answer = await response.json()
    ok = response.status == 200 and answer["n"] == n and answer["sum"] == expected
    return ok, f"{response.status} · server {answer['sum']:,} = client {expected:,}"


async def check_stream(client, n, carried):
    """Read a chunked response 8 KiB at a time and count the lines that arrived."""
    async with client.get("/stream", params={"n": n}) as response:
        chunks = [chunk async for chunk in response.content.iter_chunked(8192)]
    body = b"".join(chunks)
    lines = body.count(b"\n")
    ok = response.headers.get("Transfer-Encoding") == "chunked" and lines == n
    return ok, (
        f"{response.status} · chunked · {len(chunks)} chunks · {len(body):,} B · "
        f"{lines:,} lines"
    )


async def check_missing(client, n, carried):
    """Ask for a path with no route, and expect a 404 rather than an exception."""
    async with client.get("/nope") as response:
        await response.read()
    return response.status == 404, f"{response.status} {response.reason}"


async def check_websocket(client, n, carried):
    """Round-trip one text frame and one 12 KiB binary frame.

    The binary frame is deliberately big so that `ws-mask` and `ws-reader` run over a
    real payload rather than a few bytes — a client masks every frame it sends. Do not
    expect a fallback to show up in the timing, though: aiohttp's pure-Python masker is
    four `bytes.translate` calls and costs about 0.01 ms on 12 KiB, which is well under
    the tenth of a millisecond this row prints. The header's speedup line is what
    reports it.
    """
    async with client.ws_connect("/ws") as socket:
        await socket.send_str(GREETING)
        echoed = await socket.receive_str()
        await socket.send_bytes(BLOB)
        returned = await socket.receive_bytes()
    ok = echoed == GREETING[::-1] and returned == BLOB
    return ok, f"text reversed · binary {len(returned):,} B identical"


CHECKS = (
    ("GET JSON", check_json),
    ("gzip response", check_gzip),
    ("POST JSON", check_post),
    ("chunked stream", check_stream),
    ("missing route", check_missing),
    ("WebSocket echo", check_websocket),
)


async def run_checks(base_url, n):
    """Run the six checks in order over one session, yielding each result as it lands.

    Yields `(label, ok, detail, milliseconds)` so the caller can put a row on screen the
    moment it is ready rather than after all six. Each check is timed on its own and its
    own failure is contained, so one broken endpoint shows as one red row instead of
    hiding the other five. The milliseconds are rounded here, not on display, so a caller
    that adds them up reports the sum of the figures it actually showed.

    The session is built here rather than at module scope: its constructor needs a
    running event loop and would raise `RuntimeError: no running event loop` at import.
    """
    carried = {}
    async with aiohttp.ClientSession(base_url=base_url, timeout=TIMEOUT) as client:
        for label, check in CHECKS:
            started = time.perf_counter()
            try:
                ok, detail = await check(client, n, carried)
            except Exception as error:
                ok, detail = False, f"{type(error).__name__}: {error}"
            yield label, ok, detail, round((time.perf_counter() - started) * 1000.0, 1)
