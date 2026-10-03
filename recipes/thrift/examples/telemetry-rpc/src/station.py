"""A Thrift telemetry service and its client, both on 127.0.0.1, plus a codec benchmark.

The server half exists only so the example runs without a backend. In a real app you
keep `submit()` and point it at your own host and port.
"""

import math
import threading
import time

from telemetry import Telemetry
from telemetry.ttypes import InvalidReading, Reading, Summary
from thrift.protocol import TBinaryProtocol, TCompactProtocol, TJSONProtocol
from thrift.server import TServer
from thrift.transport import TSocket, TTransport
from thrift.TSerialization import deserialize, serialize

SENSORS = 12
SAMPLES = 32

# (name, accelerated factory, plain pure-Python factory). JSON has no native codec.
CODECS = [
    (
        "binary",
        TBinaryProtocol.TBinaryProtocolAcceleratedFactory(),
        TBinaryProtocol.TBinaryProtocolFactory(),
    ),
    (
        "compact",
        TCompactProtocol.TCompactProtocolAcceleratedFactory(),
        TCompactProtocol.TCompactProtocolFactory(),
    ),
    ("JSON", None, TJSONProtocol.TJSONProtocolFactory()),
]


def native_codec():
    """True when thrift's C++ fastbinary codec is loaded, False on a pure-Python build."""
    try:
        from thrift.protocol import fastbinary  # noqa: F401
    except ImportError:
        return False
    return True


def batch(bad_sensor=None):
    """A deterministic batch of readings; `bad_sensor` gets an impossible temperature."""
    readings = []
    for i in range(SENSORS):
        sensor = f"s{i:02d}"
        celsius = 18 + 6 * math.sin(i)
        readings.append(
            Reading(
                sensor=sensor,
                taken_at_ms=1_760_000_000_000 + i * 1000,
                celsius=-300.0 if sensor == bad_sensor else celsius,
                samples=[celsius + 0.1 * math.sin(i + k) for k in range(SAMPLES)],
                tags={"site": "roof" if i % 2 else "lab", "unit": "C"},
            )
        )
    return readings


class Handler:
    """Server-side implementation of the `Telemetry` service from telemetry.thrift."""

    def submit(self, readings):
        """Summarise a batch, rejecting any reading below absolute zero."""
        for reading in readings:
            if reading.celsius < -273.15:
                raise InvalidReading(
                    sensor=reading.sensor,
                    reason=f"{reading.celsius} °C is below absolute zero",
                )
        warmest = max(readings, key=lambda r: r.celsius)
        return Summary(
            count=len(readings),
            mean_celsius=sum(r.celsius for r in readings) / len(readings),
            max_celsius=warmest.celsius,
            warmest_sensor=warmest.sensor,
        )


class _LoopbackServerSocket(TSocket.TServerSocket):
    """Binds an ephemeral port up front, so the port is known before serve() runs."""

    def __init__(self):
        """Listen on 127.0.0.1 with a port picked by the OS."""
        super().__init__(host="127.0.0.1", port=0)
        super().listen()
        self.port = self.handle.getsockname()[1]

    def listen(self):
        """Already listening; serve() calls this again and must not rebind."""


def start_server():
    """Serve `Telemetry` from a daemon thread and return its port."""
    socket = _LoopbackServerSocket()
    server = TServer.TThreadedServer(
        Telemetry.Processor(Handler()),
        socket,
        TTransport.TFramedTransportFactory(),
        TBinaryProtocol.TBinaryProtocolAcceleratedFactory(),
        daemon=True,
    )
    threading.Thread(target=server.serve, daemon=True).start()
    return socket.port


def submit(port, readings, host="127.0.0.1"):
    """Call `Telemetry.submit` and return (Summary, milliseconds).

    The socket is wrapped in a framed transport: the native decoder only runs on a
    buffering transport, and framing has to match what the server speaks.
    """
    socket = TSocket.TSocket(host, port)
    socket.setTimeout(5000)
    transport = TTransport.TFramedTransport(socket)
    client = Telemetry.Client(TBinaryProtocol.TBinaryProtocolAccelerated(transport))
    transport.open()
    try:
        started = time.perf_counter()
        summary = client.submit(readings)
        return summary, (time.perf_counter() - started) * 1e3
    finally:
        transport.close()


def _window(factory, payload, seconds):
    """Serialize-plus-deserialize round trips per second over one short window."""
    done = 0
    started = time.perf_counter()
    while time.perf_counter() - started < seconds:
        deserialize(Telemetry.submit_args(), serialize(payload, factory), factory)
        done += 1
    return done / (time.perf_counter() - started)


def codec_rows(readings, seconds=0.6, windows=6):
    """Wire size and throughput of the `submit` payload in each protocol.

    Each row: name, bytes, native round trips/s (None when unavailable), pure-Python
    round trips/s. Native and pure windows alternate and each keeps its best, like
    timeit, so a busy moment on the device hits both alike.
    """
    payload = Telemetry.submit_args(readings=readings)
    native = native_codec()
    rows = []
    for name, accelerated, plain in CODECS:
        size = len(serialize(payload, plain))
        timed = [plain] + ([accelerated] if accelerated and native else [])
        best = [0.0] * len(timed)
        for _ in range(windows):
            for i, factory in enumerate(timed):
                best[i] = max(best[i], _window(factory, payload, seconds / windows / 2))
        rows.append((name, size, best[1] if len(best) > 1 else None, best[0]))
    return rows
