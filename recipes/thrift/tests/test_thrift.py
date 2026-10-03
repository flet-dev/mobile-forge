import threading

import pytest
from thrift.protocol import TBinaryProtocol, TCompactProtocol
from thrift.protocol.TBase import TBase
from thrift.server import THttpServer
from thrift.Thrift import TMessageType, TType
from thrift.transport import THttpClient, TSocket, TTransport
from thrift.TSerialization import deserialize, serialize


class Point(TBase):
    __slots__ = ("x", "label")

    def __init__(self, x=None, label=None):
        self.x = x
        self.label = label


Point.thrift_spec = (
    None,
    (1, TType.I32, "x", None, None),
    (2, TType.STRING, "label", "UTF8", None),
)


class Record(TBase):
    __slots__ = ("id", "name", "ratio", "flag", "blob", "origin", "points", "tags")

    def __init__(
        self,
        id=None,
        name=None,
        ratio=None,
        flag=None,
        blob=None,
        origin=None,
        points=None,
        tags=None,
    ):
        self.id = id
        self.name = name
        self.ratio = ratio
        self.flag = flag
        self.blob = blob
        self.origin = origin
        self.points = points
        self.tags = tags


Record.thrift_spec = (
    None,
    (1, TType.I64, "id", None, None),
    (2, TType.STRING, "name", "UTF8", None),
    (3, TType.DOUBLE, "ratio", None, None),
    (4, TType.BOOL, "flag", None, None),
    (5, TType.STRING, "blob", "BINARY", None),
    (6, TType.STRUCT, "origin", [Point, Point.thrift_spec], None),
    (7, TType.LIST, "points", (TType.STRUCT, [Point, Point.thrift_spec], False), None),
    (8, TType.MAP, "tags", (TType.STRING, "UTF8", TType.I32, None, False), None),
)

PROTOCOLS = {
    "binary": (
        TBinaryProtocol.TBinaryProtocolAcceleratedFactory(fallback=False),
        TBinaryProtocol.TBinaryProtocolFactory(),
    ),
    "compact": (
        TCompactProtocol.TCompactProtocolAcceleratedFactory(fallback=False),
        TCompactProtocol.TCompactProtocolFactory(),
    ),
}

WRAPPERS = {
    "framed": TTransport.TFramedTransport,
    "buffered": TTransport.TBufferedTransport,
    "bare": lambda transport: transport,
}


def _record():
    return Record(
        id=-(2**40) - 7,
        name="flet → thrift",
        ratio=3.25,
        flag=True,
        blob=bytes(range(256)),
        origin=Point(0, "o"),
        points=[Point(i, "p%d" % i) for i in (-1, 0, 1, 300)],
        tags={"a": 1, "b": -2, "c": 2**31 - 1},
    )


def _reply_with_same_record(iprot, oprot):
    """Server side of the echo call: read a Record and send it straight back."""
    name, _, seqid = iprot.readMessageBegin()
    record = Record()
    record.read(iprot)
    iprot.readMessageEnd()
    oprot.writeMessageBegin(name, TMessageType.REPLY, seqid)
    record.write(oprot)
    oprot.writeMessageEnd()
    oprot.trans.flush()


class _EchoProcessor:
    """The processor interface THttpServer drives."""

    def on_message_begin(self, func):
        pass

    def process(self, iprot, oprot):
        _reply_with_same_record(iprot, oprot)


def _counting_client(transport):
    """A strict accelerated protocol whose native encode/decode calls are counted.
    Built before any server starts, so a missing codec fails at once."""
    proto = TBinaryProtocol.TBinaryProtocolAccelerated(transport, fallback=False)
    counts = {"encode": 0, "decode": 0}
    encode, decode = proto._fast_encode, proto._fast_decode

    def counted_encode(*args):
        counts["encode"] += 1
        return encode(*args)

    def counted_decode(*args):
        counts["decode"] += 1
        return decode(*args)

    proto._fast_encode, proto._fast_decode = counted_encode, counted_decode
    return proto, counts


def _call(proto):
    """Send the record as an `echo` CALL and return the decoded REPLY."""
    proto.writeMessageBegin("echo", TMessageType.CALL, 1)
    _record().write(proto)
    proto.writeMessageEnd()
    proto.trans.flush()
    proto.readMessageBegin()
    reply = Record()
    reply.read(proto)
    proto.readMessageEnd()
    return reply


def _socket_echo(wrap):
    """One echo call over a loopback TCP socket; returns (reply, native counts)."""
    server = TSocket.TServerSocket(host="127.0.0.1", port=0)
    server.listen()
    try:
        sock = TSocket.TSocket("127.0.0.1", server.handle.getsockname()[1])
        sock.setTimeout(10000)
        proto, counts = _counting_client(wrap(sock))

        def serve():
            trans = wrap(server.accept())
            served = TBinaryProtocol.TBinaryProtocolAccelerated(trans, fallback=False)
            _reply_with_same_record(served, served)
            trans.close()

        threading.Thread(target=serve, daemon=True).start()
        proto.trans.open()
        reply = _call(proto)
        proto.trans.close()
    finally:
        server.close()
    return reply, counts


def _http_echo(wrap):
    """One echo call to a loopback THttpServer; returns (reply, native counts)."""
    server = THttpServer.THttpServer(
        _EchoProcessor(),
        ("127.0.0.1", 0),
        TBinaryProtocol.TBinaryProtocolAcceleratedFactory(fallback=False),
    )
    serving = None
    try:
        client = THttpClient.THttpClient(
            "http://127.0.0.1:%d/" % server.httpd.server_address[1]
        )
        client.setTimeout(10000)
        proto, counts = _counting_client(wrap(client))
        serving = threading.Thread(target=server.serve, daemon=True)
        serving.start()
        proto.trans.open()
        reply = _call(proto)
        proto.trans.close()
    finally:
        # shutdown() waits for serve_forever() and would block if it never started.
        if serving:
            server.httpd.shutdown()
        server.httpd.server_close()
    return reply, counts


def test_fastbinary_is_native():
    """The C++ fastbinary extension imports from the wheel as compiled code."""
    from thrift.protocol import fastbinary

    for fn in ("encode_binary", "decode_binary", "encode_compact", "decode_compact"):
        assert type(getattr(fastbinary, fn)).__name__ == "builtin_function_or_method"


def test_accelerated_protocols_bind_native_codec():
    """Accelerated protocols use fastbinary, not the silent pure-Python fallback."""
    from thrift.protocol import fastbinary
    from thrift.transport.TTransport import TMemoryBuffer

    binary = TBinaryProtocol.TBinaryProtocolAccelerated(TMemoryBuffer(), fallback=False)
    compact = TCompactProtocol.TCompactProtocolAccelerated(
        TMemoryBuffer(), fallback=False
    )
    assert binary._fast_encode is fastbinary.encode_binary
    assert binary._fast_decode is fastbinary.decode_binary
    assert compact._fast_encode is fastbinary.encode_compact
    assert compact._fast_decode is fastbinary.decode_compact


@pytest.mark.parametrize("name", sorted(PROTOCOLS))
def test_accelerated_bytes_match_pure_python(name):
    """The native encoder produces exactly the pure-Python wire bytes."""
    fast, pure = PROTOCOLS[name]
    assert serialize(_record(), fast) == serialize(_record(), pure)


@pytest.mark.parametrize("name", sorted(PROTOCOLS))
def test_accelerated_round_trip(name):
    """Nested struct/list/map/binary fields survive a native encode/decode."""
    fast, pure = PROTOCOLS[name]
    data = serialize(_record(), fast)
    assert deserialize(Record(), data, fast) == _record()
    assert deserialize(Record(), data, pure) == _record()


@pytest.mark.parametrize(
    "wrapper, native_decodes", [("framed", 1), ("buffered", 1), ("bare", 0)]
)
def test_socket_call_native_codec_use(wrapper, native_decodes):
    """A loopback TCP call round-trips on any transport. The request is always
    encoded natively, but the reply is decoded natively only through a framed or
    buffered transport (the README's client setup)."""
    reply, counts = _socket_echo(WRAPPERS[wrapper])
    assert reply == _record()
    assert counts == {"encode": 1, "decode": native_decodes}


@pytest.mark.parametrize("wrapper, native_decodes", [("buffered", 1), ("bare", 0)])
def test_http_call_native_codec_use(wrapper, native_decodes):
    """THttpClient behaves like a bare socket: replies are decoded natively only
    when it is wrapped in a TBufferedTransport, as the README advises."""
    reply, counts = _http_echo(WRAPPERS[wrapper])
    assert reply == _record()
    assert counts == {"encode": 1, "decode": native_decodes}
