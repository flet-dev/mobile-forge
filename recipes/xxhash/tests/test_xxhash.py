def test_basic():
    """Load the bundled xxHash C extension and verify a known digest."""
    import xxhash

    # xxh64 of the empty string with the default seed 0 — a stable,
    # documented vector. Proves the C extension computes correctly.
    assert xxhash.xxh64_intdigest(b"") == 0xEF46DB3751D8E999

    # Same input -> same digest, across both the streaming and one-shot APIs.
    h = xxhash.xxh3_64()
    h.update(b"mobile-forge")
    assert h.hexdigest() == xxhash.xxh3_64_hexdigest(b"mobile-forge")
    assert isinstance(xxhash.VERSION, str)  # bundled libxxhash version
