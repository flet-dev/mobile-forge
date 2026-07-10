def test_speedups_extension_loaded():
    """The whole reason tornado needs a recipe is the compiled
    `tornado.speedups` abi3 extension. With TORNADO_EXTENSION=1 the pure-Python
    fallback is disabled, so a successful import proves the .so cross-compiled
    and loaded rather than silently degrading."""
    from tornado import speedups

    assert hasattr(speedups, "websocket_mask")


def test_websocket_mask_roundtrip():
    """XOR-masking is an involution: masking twice restores the input. A
    13-byte payload deliberately exercises all three loops in speedups.c —
    the 64-bit block, the 32-bit block, and the single-byte tail."""
    from tornado.speedups import websocket_mask

    mask = b"\xa1\xb2\xc3\xd4"
    data = b"hello, world!"
    assert websocket_mask(mask, websocket_mask(mask, data)) == data


def test_ioloop_asyncio_bridge():
    """jupyter-client (the reason this package is requested) drives tornado
    through tornado.ioloop, which is a thin wrapper over asyncio. Importing it
    pulls tornado.platform.asyncio and confirms that path loads on mobile."""
    import tornado.ioloop

    assert tornado.ioloop.IOLoop is not None
