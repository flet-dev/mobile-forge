def test_roundtrip():
    """msgpack's whole reason for being a recipe is the C-extension packer
    and unpacker. A round-trip with mixed types exercises both."""
    import msgpack

    doc = {
        "name": "mobile-forge",
        "count": 42,
        "items": ["a", "b", "c"],
        "ratio": 1.5,
        "ok": True,
        "blob": b"\x00\x01\x02\x03",
    }
    packed = msgpack.packb(doc)
    assert isinstance(packed, bytes)
    assert msgpack.unpackb(packed) == doc


def test_streaming_unpacker():
    """Streaming unpack from a Reader — uses a different C path than packb."""
    import io

    import msgpack

    buf = io.BytesIO()
    for i in range(3):
        buf.write(msgpack.packb({"i": i}))
    buf.seek(0)

    unpacker = msgpack.Unpacker(buf)
    decoded = list(unpacker)
    assert decoded == [{"i": 0}, {"i": 1}, {"i": 2}]


def test_c_extension_is_in_use():
    """msgpack falls back to pure Python if `_cmsgpack` fails to import, and the
    round-trip tests above still pass, so assert the C classes are the ones bound."""
    import msgpack
    from msgpack import _cmsgpack

    assert msgpack.Packer is _cmsgpack.Packer
    assert msgpack.Unpacker is _cmsgpack.Unpacker
    assert msgpack.unpackb is _cmsgpack.unpackb
