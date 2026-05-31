def test_frame_mask_roundtrip():
    """websockets' frame masking is XOR with a 4-byte key. The library
    exposes it via the public Frame API; if the optional C accelerator
    (`websockets.speedups`) was built it gets used transparently,
    otherwise the pure-Python fallback kicks in. Either way, masking
    twice with the same key restores the original payload — that's the
    test we actually care about."""
    from websockets.frames import apply_mask

    payload = b"the quick brown fox jumps over the lazy dog"
    mask = b"\x12\x34\x56\x78"
    masked = apply_mask(payload, mask)
    assert masked != payload
    assert apply_mask(masked, mask) == payload


def test_import_api():
    """Public top-level symbols are wired up — protects against a recipe
    that ships an extension but breaks the pure-Python API."""
    import websockets

    assert hasattr(websockets, "connect")
    assert hasattr(websockets, "serve")
