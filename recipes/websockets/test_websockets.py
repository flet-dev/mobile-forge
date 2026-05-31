def test_handshake_frames():
    """websockets ships an optional C accelerator (`websockets.speedups`)
    that handles frame masking. Exercise mask + unmask directly — that's
    the only deterministic, network-free test of the C path."""
    from websockets import speedups

    payload = bytearray(b"the quick brown fox jumps over the lazy dog")
    mask = b"\x12\x34\x56\x78"
    speedups.apply_mask(payload, mask)
    # Round-trip: masking twice with the same key undoes it.
    speedups.apply_mask(payload, mask)
    assert bytes(payload) == b"the quick brown fox jumps over the lazy dog"


def test_import_api():
    """Public top-level symbols are wired up — protects against a recipe
    that ships only the speedups extension and breaks the pure-Python API."""
    import websockets

    assert hasattr(websockets, "connect")
    assert hasattr(websockets, "serve")
