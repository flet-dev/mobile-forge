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

import grpc

SERVICE = "forge.Echo"
PAYLOAD_KIB = 8
STREAM_FRAMES = 8
WARM_CALLS = 50
TRUST_STORE = ("grpc._cython", "_credentials/roots.pem")
VERSION = f"grpcio {grpc.__version__} — Python {platform.python_version()}"

# Counted by the relay, in bytes, in each direction. Every check reads a delta rather
# than an absolute: one channel means one TCP connection, so the counters run for the
# whole session and only the difference across a call belongs to that call.
WIRE = {"up": 0, "down": 0}
WIRE_LOCK = threading.Lock()

# Every connectivity transition the channel reports, in order.
STATES = []

# A grpc.Server tears itself down once its last Python reference goes: __del__ sets a
# `server_deallocated` flag that the serving thread acts on shortly after. `start`
# below returns as a matter of course, so a server left in its locals stops serving
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
    start_bytes = wire()[0]
    calls["Digest"](body, timeout=10, compression=grpc.Compression.NoCompression)
    middle = wire()[0]
    calls["Digest"](body, timeout=10, compression=grpc.Compression.Gzip)
    end = wire()[0]
    plain, zipped = middle - start_bytes, end - middle
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


def start():
    """Stand up the server, the byte-counting relay and one channel on loopback.

    Returns the call stubs to run checks against, and the header lines the app prints
    above them: the two ports, the trust store, the OS threads gRPC's C core added and
    how long the channel took, then the cold and warm call timings. All three pieces
    are built once and reused — whichever of the server and the channel comes first is
    what starts the C core's thread pool, which is why the thread count brackets both.
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

    started = time.perf_counter()
    channel = grpc.insecure_channel(f"127.0.0.1:{relay_port}")
    channel_ms = (time.perf_counter() - started) * 1000.0
    # The synchronous Channel has no get_state() — that lives on grpc.aio.Channel only.
    # subscribe() is the equivalent here, and it reports every transition rather than
    # one snapshot.
    channel.subscribe(STATES.append, try_to_connect=True)
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

    threads = (
        f"+{after_threads - before_threads} OS threads for the server and channel"
        if before_threads is not None and after_threads is not None
        else "OS thread count needs /proc, so Android only"
    )
    lines = [
        f"serving 127.0.0.1:{backend} behind relay :{relay_port}",
        trust_store(),
        f"{threads} · channel built in {channel_ms:.1f} ms",
        warm_up(calls["Digest"]),
    ]
    return calls, lines


def run_checks(calls, size):
    """Run the six checks at `size` bytes, yielding `(label, ok, detail, ms)` each.

    A generator so a verdict can go on screen as it lands rather than all six at the
    end. Each check is timed on its own and its failure contained here, so one broken
    path becomes one failed row instead of hiding the other five — and nothing the RPC
    stack raises reaches the caller. `grpc.RpcError` is caught by name because it is
    the exception this app raises most, and the caller runs in a worker thread that
    retrieves no future, where an escaping error would vanish without a trace.
    """
    for label, check in CHECKS:
        started = time.perf_counter()
        try:
            ok, detail = check(calls, size)
        except grpc.RpcError as error:
            ok, detail = False, f"{error.code().name}: {error.details()}"
        except Exception as error:
            ok, detail = False, f"{type(error).__name__}: {error}"
        yield label, ok, detail, round((time.perf_counter() - started) * 1000.0, 1)


def transitions():
    """Name the connectivity transitions the channel has reported so far."""
    return " → ".join(state.name for state in STATES) or "no transition seen"
