def test_basic():
    """Confirm the Rust extension loads and round-trips a msgpack payload."""
    import ormsgpack

    payload = {
        "library": "ormsgpack",
        "active": True,
        "tags": ["mobile", "python", "flet"],
        "ratio": 3.141592653589793,
        "nothing": None,
    }

    packed = ormsgpack.packb(payload)
    assert isinstance(packed, bytes)  # ormsgpack returns bytes
    assert ormsgpack.unpackb(packed) == payload
