def test_compress_roundtrip():
    """zstandard wraps Facebook's libzstd C library. Round-trip a payload
    big enough to actually compress."""
    import zstandard

    plain = b"the quick brown fox jumps over the lazy dog " * 50
    cctx = zstandard.ZstdCompressor(level=10)
    compressed = cctx.compress(plain)
    assert len(compressed) < len(plain)

    dctx = zstandard.ZstdDecompressor()
    assert dctx.decompress(compressed) == plain


def test_streaming():
    """Streaming API exercises a different C path (writer + reader)."""
    import io

    import zstandard

    plain = b"hello world\n" * 100
    sink = io.BytesIO()
    with zstandard.ZstdCompressor().stream_writer(sink, closefd=False) as writer:
        writer.write(plain)
    compressed = sink.getvalue()

    decompressed = (
        zstandard.ZstdDecompressor().stream_reader(io.BytesIO(compressed)).read()
    )
    assert decompressed == plain
