"""A gRPC server, grpc's own client, and a byte counter on the wire between them."""

import hashlib
import os
import pkgutil
import platform
import socket
import statistics
import threading
import time
from concurrent import futures

import flet as ft
import grpc

SERVICE = "forge.Echo"
PAYLOAD_KIB = 8
STREAM_FRAMES = 8
WARM_CALLS = 50
TRUST_STORE = ("grpc._cython", "_credentials/roots.pem")

# Counted by the relay, in bytes, in each direction. Every check reads a delta rather
# than an absolute: one channel means one TCP connection, so the counters run for the
# whole session and only the difference across a call belongs to that call.
WIRE = {"up": 0, "down": 0}
WIRE_LOCK = threading.Lock()

# A grpc.Server tears itself down once its last Python reference goes: __del__ sets a
# `server_deallocated` flag that the serving thread acts on shortly after. Flet returns
# from `main` as a matter of course, so a server left in `main`'s locals stops serving
# right after the first render and every later call comes back UNAVAILABLE, naming the
# address rather than the mistake. The channel is parked alongside it: Channel.__del__
# deliberately does not close today, but upstream's comment there says that is temporary.
LIVE = {}


def raw(data):
    """Serialise and deserialise `bytes` as themselves.

    This is the whole reason the example needs no `.proto` file, no protoc and no
    generated `_pb2_grpc.py`: gRPC only requires a pair of callables that turn a message
    into bytes and back, and for a `bytes` message that pair is the identity.
    """
    return data


def payload(size):
    """Build `size` deterministic, highly compressible bytes.

    Deterministic so two devices produce the same digest and can be compared directly;
    compressible so the gzip check has something visible to show on the wire.
    """
    return (bytes(range(256)) * (size // 256 + 1))[:size]


def frame(index, size):
    """Build stream frame `index`, which the client recomputes to check what arrived."""
    seed = hashlib.sha256(f"frame-{index}".encode()).digest()
    return (seed * (size // len(seed) + 1))[:size]


def trust_store():
    """Report grpc's own CA bundle, or why it could not be read.

    This is the one line worth reading off a real device: the C core fetches
    `roots.pem` through exactly this call when it needs default TLS roots, so a copy
    lost in packaging would otherwise surface only as a handshake failure much later.
    A failure is rendered rather than raised, because an exception escaping `main` gets
    a Flet crash screen — the least useful place for this particular answer to land.
    """
    try:
        roots = pkgutil.get_data(*TRUST_STORE)
        return (
            f"trust store {len(roots):,} B, "
            f"{roots.count(b'BEGIN CERTIFICATE')} certificates"
        )
    except Exception as error:
        return f"trust store UNREADABLE — {type(error).__name__}: {error}"


def os_threads():
    """Count the process's OS threads, or `None` where that cannot be answered.

    gRPC's C core runs its own thread pool, and those threads are invisible to
    `threading.enumerate()` — reading `/proc/self/task` is the only way an app sees
    them. Android has `/proc`; iOS does not, and neither does macOS.
    """
    try:
        return len(os.listdir("/proc/self/task"))
    except OSError:
        return None


def warm_up(call):
    """Time one cold call and `WARM_CALLS` warm ones, or say why they could not run.

    Rendered rather than raised, for the same reason `trust_store` is: these are the
    first calls the app makes, so a loopback the OS did not allow fails *here* — and an
    `RpcError` escaping `main` gets a Flet crash screen, taking the two lines above it
    down with it. Those two, the port and the trust store, are the whole reason to run
    this on a device. A loopback that is not working says so again a moment later, as
    six red rows.
    """
    try:
        started = time.perf_counter()
        call(payload(1024), timeout=10)
        first_ms = (time.perf_counter() - started) * 1000.0
        warm = []
        for _ in range(WARM_CALLS):
            started = time.perf_counter()
            call(payload(1024), timeout=10)
            warm.append((time.perf_counter() - started) * 1000.0)
    except grpc.RpcError as error:
        return f"loopback UNUSABLE — {error.code().name}: {error.details()}"
    return (
        f"first call {first_ms:.1f} ms · warm median "
        f"{statistics.median(warm):.2f} ms over {WARM_CALLS} calls"
    )


def handle_digest(request, context):
    """Answer with the length and SHA-256 of exactly the bytes that arrived.

    The digest is what makes the unary check a real cross-check rather than a plausible
    number: the client compares it against a hash of what it sent, so a truncated or
    mangled message shows up as a failed row instead of a slightly wrong length.
    """
    return f"{len(request)}:{hashlib.sha256(request).hexdigest()}".encode()


def handle_frames(request, context):
    """Stream back `count` frames of `size` bytes, both taken from the request."""
    count, size = (int(part) for part in request.split(b":"))
    for index in range(count):
        yield frame(index, size)


def handle_slow(request, context):
    """Outlast any deadline the client is willing to wait for, then give up.

    Polling `context.is_active()` rather than sleeping straight through matters more
    than it looks: the servicer pool here is four threads, and a handler that sleeps on
    past a cancelled call holds one of them. A few slider drags would otherwise leave
    every later check queued behind an RPC nobody is waiting for.
    """
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and context.is_active():
        time.sleep(0.02)
    return b"too late"


def handle_abort(request, context):
    """Fail the call deliberately, with a status code and a detail string."""
    context.abort(grpc.StatusCode.FAILED_PRECONDITION, "payload rejected on purpose")


def handle_metadata(request, context):
    """Read the client's `x-req` header and hand it back as trailing metadata."""
    sent = dict(context.invocation_metadata()).get("x-req", "")
    context.set_trailing_metadata((("x-echo", sent),))
    return b"metadata seen"


HANDLERS = {
    "Digest": grpc.unary_unary_rpc_method_handler(
        handle_digest, request_deserializer=raw, response_serializer=raw
    ),
    "Frames": grpc.unary_stream_rpc_method_handler(
        handle_frames, request_deserializer=raw, response_serializer=raw
    ),
    "Slow": grpc.unary_unary_rpc_method_handler(
        handle_slow, request_deserializer=raw, response_serializer=raw
    ),
    "Abort": grpc.unary_unary_rpc_method_handler(
        handle_abort, request_deserializer=raw, response_serializer=raw
    ),
    "Metadata": grpc.unary_unary_rpc_method_handler(
        handle_metadata, request_deserializer=raw, response_serializer=raw
    ),
}


def pump(source, sink, key):
    """Copy one direction of a relayed connection, counting the bytes as they pass."""
    while True:
        try:
            chunk = source.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        with WIRE_LOCK:
            WIRE[key] += len(chunk)
        try:
            sink.sendall(chunk)
        except OSError:
            break
    try:
        sink.shutdown(socket.SHUT_WR)
    except OSError:
        pass


def accept_loop(listener, backend):
    """Forward every accepted connection to the real server on two pump threads."""
    while True:
        try:
            downstream, _ = listener.accept()
        except OSError:
            return
        upstream = socket.create_connection(("127.0.0.1", backend))
        for source, sink, key in (
            (downstream, upstream, "up"),
            (upstream, downstream, "down"),
        ):
            threading.Thread(target=pump, args=(source, sink, key), daemon=True).start()


def start_relay(backend):
    """Listen on an OS-assigned port and relay it to `backend`, returning the port.

    gRPC reports no wire sizes of its own, so the only way to show what HTTP/2 framing
    and gzip actually cost is to count the bytes underneath it.
    """
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    threading.Thread(target=accept_loop, args=(listener, backend), daemon=True).start()
    return listener.getsockname()[1]


def wire():
    """Snapshot the relay's two counters."""
    with WIRE_LOCK:
        return WIRE["up"], WIRE["down"]


def check_unary(calls, size):
    """Send one payload and confirm the length and digest the server computed."""
    body = payload(size)
    answer = calls["Digest"](body, timeout=10).decode()
    expected = f"{len(body)}:{hashlib.sha256(body).hexdigest()}"
    return answer == expected, f"{len(body):,} B · sha {answer.split(':')[1][:12]}…"


def check_stream(calls, size):
    """Read a server-streamed response and check every frame and the frame count."""
    request = f"{STREAM_FRAMES}:{size // STREAM_FRAMES}".encode()
    frames = list(calls["Frames"](request, timeout=10))
    ok = len(frames) == STREAM_FRAMES and all(
        got == frame(index, size // STREAM_FRAMES) for index, got in enumerate(frames)
    )
    total = sum(len(got) for got in frames)
    return ok, f"{len(frames)}/{STREAM_FRAMES} frames · {total:,} B · all bytes match"


def check_deadline(calls, size):
    """Give a two-second handler 150 ms and expect the deadline to fire."""
    try:
        calls["Slow"](b"", timeout=0.15)
    except grpc.RpcError as error:
        ok = error.code() is grpc.StatusCode.DEADLINE_EXCEEDED
        return ok, f"{error.code().name} · {error.details()!r}"
    return False, "the slow handler answered, which it should not have"


def check_abort(calls, size):
    """Confirm a server-side abort arrives with its code *and* its detail intact."""
    try:
        calls["Abort"](b"", timeout=10)
    except grpc.RpcError as error:
        ok = error.code() is grpc.StatusCode.FAILED_PRECONDITION
        return ok, f"{error.code().name} · {error.details()!r}"
    return False, "the abort handler returned normally"


def check_metadata(calls, size):
    """Send a request header and read it back out of the trailing metadata."""
    _, call = calls["Metadata"].with_call(
        b"", timeout=10, metadata=(("x-req", "loopback"),)
    )
    trailing = dict(call.trailing_metadata())
    return (
        trailing.get("x-echo") == "loopback",
        f"trailing x-echo={trailing.get('x-echo')!r}",
    )


def check_gzip(calls, size):
    """Send the same payload twice, uncompressed then gzipped, and weigh both.

    The two calls are identical apart from `compression=`, so the difference between
    the relay's two deltas is gzip and nothing else. gRPC's menu is only
    `NoCompression`, `Deflate` and `Gzip` — there is no zstd or brotli in this build.
    """
    body = payload(size)
    start = wire()[0]
    calls["Digest"](body, timeout=10, compression=grpc.Compression.NoCompression)
    middle = wire()[0]
    calls["Digest"](body, timeout=10, compression=grpc.Compression.Gzip)
    end = wire()[0]
    plain, zipped = middle - start, end - middle
    ok = 0 < zipped < plain
    return ok, f"{len(body):,} B → {plain:,} B plain, {zipped:,} B gzipped"


CHECKS = (
    ("unary digest", check_unary),
    ("server stream", check_stream),
    ("deadline", check_deadline),
    ("abort status", check_abort),
    ("metadata", check_metadata),
    ("gzip on the wire", check_gzip),
)


def check_row(label, ok, detail, elapsed):
    """Lay one check out as a verdict line with its detail wrapping underneath.

    Two lines rather than one wide Row: the details are long enough that a
    non-scrolling Row would show Flutter's overflow stripes on a phone.
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


def main(page: ft.Page):
    """Stand up a server, a relay and a channel on loopback, then check the six paths.

    `main` is deliberately synchronous: gRPC's blocking API releases the GIL for the
    whole of a call, so the natural home for the work is a `page.run_thread` worker and
    there is no event loop to keep anything on. The server, the relay and the channel
    are built once here and reused — whichever of the server and the channel comes first
    is what starts the C core's thread pool, which is why the count below brackets both.
    """
    before_threads = os_threads()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    server.add_generic_rpc_handlers(
        (grpc.method_handlers_generic_handler(SERVICE, HANDLERS),)
    )
    backend = server.add_insecure_port("127.0.0.1:0")
    server.start()
    LIVE["server"] = server
    relay_port = start_relay(backend)

    states = []
    started = time.perf_counter()
    channel = grpc.insecure_channel(f"127.0.0.1:{relay_port}")
    channel_ms = (time.perf_counter() - started) * 1000.0
    # The synchronous Channel has no get_state() — that lives on grpc.aio.Channel only.
    # subscribe() is the equivalent here, and it reports every transition rather than
    # one snapshot.
    channel.subscribe(states.append, try_to_connect=True)
    LIVE["channel"] = channel
    after_threads = os_threads()

    calls = {
        "Frames": channel.unary_stream(
            f"/{SERVICE}/Frames", request_serializer=raw, response_deserializer=raw
        )
    }
    for name in ("Digest", "Slow", "Abort", "Metadata"):
        calls[name] = channel.unary_unary(
            f"/{SERVICE}/{name}", request_serializer=raw, response_deserializer=raw
        )

    timing = warm_up(calls["Digest"])
    trust = trust_store()
    threads = (
        f"+{after_threads - before_threads} OS threads for the server and channel"
        if before_threads is not None and after_threads is not None
        else "OS thread count needs /proc, so Android only"
    )

    def run_suite():
        """Run the six checks over one channel, appending each row as it lands.

        Every check is timed and its failure contained, so one broken path shows as one
        red row instead of hiding the other five. `grpc.RpcError` is caught by name
        because it is the exception this app raises most and `page.run_thread` retrieves
        no future — an escaping error would vanish without a crash, a log line or a
        clue. The body ends in `page.update()` for the same reason: Flet's auto-update
        fires around event handlers, not inside a worker thread.
        """
        size = int(slider.value) * 1024
        results.controls = []
        footer.value = f"running at {size:,} B…"
        page.update()

        passed = 0
        total = 0.0
        try:
            for label, check in CHECKS:
                started = time.perf_counter()
                try:
                    ok, detail = check(calls, size)
                except grpc.RpcError as error:
                    ok, detail = False, f"{error.code().name}: {error.details()}"
                except Exception as error:
                    ok, detail = False, f"{type(error).__name__}: {error}"
                elapsed = round((time.perf_counter() - started) * 1000.0, 1)
                passed += ok
                total += elapsed
                results.controls.append(check_row(label, ok, detail, elapsed))
                page.update()
            seen = " → ".join(state.name for state in states) or "no transition seen"
            footer.value = (
                f"{passed}/{len(CHECKS)} checks passed · {total:.1f} ms in total · "
                f"channel {seen}"
            )
        finally:
            slider.disabled = False
            page.update()

    def describe():
        """Keep the caption in step with the slider as it is dragged."""
        caption.value = f"{int(slider.value)} KiB per payload"

    def rerun():
        """Re-run the suite in a worker thread when the slider is released.

        The disable happens here rather than inside `run_suite`, and is read back as the
        re-entrancy guard: `run_thread` only schedules, so a flag set in the worker has
        not happened yet when this handler returns and Flet pushes the slider's state.
        Two releases in that window would queue two runs into one results column.
        """
        if slider.disabled:
            return
        slider.disabled = True
        page.run_thread(run_suite)

    page.appbar = ft.AppBar(title=ft.Text("gRPC loopback"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"grpcio {grpc.__version__} — Python "
                        f"{platform.python_version()} on {page.platform.value}",
                        size=12,
                    ),
                    ft.Text(
                        f"serving 127.0.0.1:{backend} behind relay :{relay_port}",
                        size=12,
                    ),
                    ft.Text(trust, size=12),
                    ft.Text(
                        f"{threads} · channel built in {channel_ms:.1f} ms",
                        size=12,
                    ),
                    ft.Text(timing, size=12),
                    caption := ft.Text(f"{PAYLOAD_KIB} KiB per payload"),
                    slider := ft.Slider(
                        min=1,
                        max=64,
                        value=PAYLOAD_KIB,
                        divisions=63,
                        label="{value} KiB",
                        on_change=describe,
                        on_change_end=rerun,
                    ),
                    results := ft.Column(spacing=8),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    slider.disabled = True
    page.run_thread(run_suite)


if __name__ == "__main__":
    ft.run(main)
