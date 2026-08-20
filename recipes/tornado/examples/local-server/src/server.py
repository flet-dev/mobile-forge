import asyncio
import json
import os
import threading
import time
from collections import deque

import tornado
import tornado.httpclient
import tornado.httpserver
import tornado.netutil
import tornado.web

# Loopback, and only loopback. 0.0.0.0 would publish the API on whatever network
# the phone is joined to; 127.0.0.1 never leaves the device and works in airplane
# mode. Give the literal address rather than "localhost", which also resolves to
# ::1 and binds a second socket.
HOST = "127.0.0.1"
# Port 0 asks the kernel for a free one. A fixed port is what actually fails on a
# phone: below 1024 needs root, and above it another app may already hold it.
PORT = 0
NOTES = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "notes.json")
ROUTES = {
    "status": "GET /api/status",
    "notes": "GET /api/notes",
    "add": "POST /api/notes",
}
TIMEOUT = 5.0

VERSION = f"tornado {tornado.version}"

_log = deque(maxlen=5)
_state = {"loop": None, "stop": None, "port": 0, "requests": 0, "since": 0.0}


def speedups_loaded():
    """Whether the compiled `tornado.speedups` extension is the one actually masking.

    It is tornado's only native code: one `websocket_mask()` that XORs a websocket
    frame against its 4-byte key. `setup.py` marks the extension optional, so a wheel
    built without it still imports and still serves, and `tornado.util` quietly
    selects a Python loop instead.

    `from tornado import speedups` would only prove the file shipped -- the fallback
    satisfies that check too, since the module can be present and still unused. The
    choice `tornado.util` made at import is the real answer, and `tornado.websocket`
    uses whatever it chose. Reading it back is reaching into a private name, so it
    belongs in a diagnostic like this one and nowhere else.
    """
    from tornado.util import _websocket_mask

    return _websocket_mask.__module__ == "tornado.speedups"


def read_notes():
    """Load the stored notes, tolerating a first run with no file yet."""
    try:
        with open(NOTES, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return []


def log():
    """The last few requests the server finished, newest first."""
    return list(_log)


class Handler(tornado.web.RequestHandler):
    """Base handler: JSON errors, and one log line per finished request."""

    def on_finish(self):
        """Record the request after the response has gone out.

        `request_time()` is measured by the server, so it excludes everything the
        client spends getting to the socket -- which is why it reads lower than the
        round trip the app times.
        """
        _state["requests"] += 1
        _log.appendleft(
            f"{self.request.method} {self.request.path} -> {self.get_status()}"
            f"  {self.request.request_time() * 1000:.1f} ms"
        )

    def write_error(self, status_code, **kwargs):
        """Send failures as JSON too, so the app never parses tornado's HTML page."""
        self.write({"error": self._reason, "status": status_code})


class StatusHandler(Handler):
    """`GET /api/status` -- what the server knows about itself."""

    def get(self):
        """Report the facts that are worth seeing from inside the app."""
        self.write(
            {
                "tornado": tornado.version,
                "speedups_extension": speedups_loaded(),
                "listening_on": f"http://{HOST}:{_state['port']}",
                "requests_served": _state["requests"],
                "uptime_seconds": round(time.monotonic() - _state["since"], 1),
                "server_thread": threading.current_thread().name,
                "storage": NOTES,
            }
        )


class NotesHandler(Handler):
    """`GET`/`POST /api/notes` -- a JSON API over a file in app storage."""

    def get(self):
        """Return the stored notes. A dict passed to write() is sent as JSON."""
        self.write({"notes": read_notes()})

    def post(self):
        """Append one note and persist it under FLET_APP_STORAGE_DATA."""
        note = json.loads(self.request.body or b"{}").get("note", "").strip()
        if not note:
            raise tornado.web.HTTPError(400, reason="note must not be empty")
        notes = read_notes() + [note]
        with open(NOTES, "w", encoding="utf-8") as handle:
            json.dump(notes, handle)
        self.set_status(201)
        self.write({"notes": notes})


def start():
    """Bring the server up on its own thread and return the port it got.

    Everything tornado owns -- the listening sockets, the IOLoop, the handlers and
    the HTTP client below -- belongs to one asyncio loop running on one thread.
    Flet owns the main thread, so the server gets a thread of its own and calls
    `asyncio.run` there, which creates that loop and makes it current *for that
    thread only*. The caller waits on an `Event` because the port does not exist
    until the socket is bound.
    """
    if _state["loop"] is not None:
        return _state["port"]
    ready = threading.Event()
    thread = threading.Thread(
        target=lambda: asyncio.run(_serve(ready)), name="tornado", daemon=True
    )
    thread.start()
    if not ready.wait(TIMEOUT):
        raise RuntimeError("server did not come up")
    return _state["port"]


async def _serve(ready):
    """The whole life of the server: bind, publish the port, wait, wind down."""
    sockets = tornado.netutil.bind_sockets(PORT, HOST)
    server = tornado.httpserver.HTTPServer(
        tornado.web.Application(
            [(r"/api/status", StatusHandler), (r"/api/notes", NotesHandler)]
        )
    )
    server.add_sockets(sockets)
    _state.update(
        loop=asyncio.get_running_loop(),
        stop=asyncio.Event(),
        port=sockets[0].getsockname()[1],
        since=time.monotonic(),
        requests=0,  # reported beside uptime_seconds, so reset with it
    )
    ready.set()
    await _state["stop"].wait()
    server.stop()
    await server.close_all_connections()


def stop():
    """Ask the server's own thread to wind down, from outside that thread.

    `call_soon_threadsafe` is the only supported way to touch a running loop from
    outside its thread; setting the Event directly from here would be a data race.
    It schedules and returns, so this call is over before the socket is actually
    closed -- which is what a PAUSE handler wants, since it must not block, and
    which costs nothing here because the next bind asks for a fresh port anyway.
    """
    loop, done = _state["loop"], _state["stop"]
    if loop is None:
        return
    _state.update(loop=None, stop=None, port=0)
    loop.call_soon_threadsafe(done.set)


def request(route, note):
    """Call the local server once, from a Flet worker thread, and flatten the reply.

    The coroutine is handed to the server's loop with `run_coroutine_threadsafe`
    instead of being run here. A `page.run_thread` worker has no event loop, so
    `IOLoop.current()` on this thread quietly builds a second one and hands it back
    -- and nothing ever runs it. A fetch started there returns a future that stays
    pending forever: not even its own `request_timeout` fires, because that timer is
    scheduled on the same dead loop. Passing the work to the loop that already exists
    is the whole trick, and it is also why the server and its client can share a
    single thread. The timeout that does protect this call is the one below, on the
    `concurrent.futures` future -- that one is enforced by the calling thread.
    """
    loop = _state["loop"]
    if loop is None:
        raise RuntimeError("server is not running")
    method, path = route.split()
    body = json.dumps({"note": note}) if method == "POST" else None
    future = asyncio.run_coroutine_threadsafe(_fetch(method, path, body), loop)
    return future.result(TIMEOUT)


async def _fetch(method, path, body):
    """Run one HTTP request through tornado's pure-Python client."""
    url = f"http://{HOST}:{_state['port']}{path}"
    started = time.perf_counter()
    response = await tornado.httpclient.AsyncHTTPClient().fetch(
        url,
        method=method,
        body=body,
        headers={"Content-Type": "application/json"},
        # Without this a 400 arrives as an exception, and the point of the demo is
        # to show the response either way.
        raise_error=False,
    )
    return {
        "url": url,
        "sent": body or "",
        "status": f"{response.code} {response.reason}",
        "content_type": response.headers.get("Content-Type", ""),
        "body": _pretty(response.body),
        "elapsed": (time.perf_counter() - started) * 1000,
    }


def _pretty(raw):
    """Re-indent a JSON body so it is readable on a phone-sized screen."""
    text = raw.decode(errors="replace")
    try:
        return json.dumps(json.loads(text), indent=2)
    except ValueError:
        return text
