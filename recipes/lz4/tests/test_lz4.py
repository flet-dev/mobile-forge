import random

# `lz4 -9 --content-size -BX` (the reference CLI, v1.10.0) over
# b"flet + lz4 on a phone\n" * 300: content size, block and content checksums.
CLI_FRAME = bytes.fromhex(
    "04224d187c40c819000000000000ac3a000000ff07666c6574202b206c7a34206f6e2061"
    "2070686f6e650a1600ffffffffffffffffffffffffffffffffffffffffffffffffffb350"
    "686f6e650a07ddbf300000000019ef2271"
)
CLI_PAYLOAD = b"flet + lz4 on a phone\n" * 300


def _payload():
    """Half repetitive text, half seeded noise, so every codec path does real work."""
    text = b"".join(b"event %05d level=info msg=ok\n" % i for i in range(4000))
    return text + random.Random(0).randbytes(len(text))


def test_frame_roundtrip_with_checksums():
    """A frame carrying size and both checksums round-trips -> lz4frame.c and the
    vendored xxhash are compiled in, not just the block codec."""
    import lz4.frame

    data = _payload()
    frame = lz4.frame.compress(
        data, content_checksum=True, block_checksum=True, store_size=True
    )
    info = lz4.frame.get_frame_info(frame)
    assert info["content_checksum"] and info["block_checksum"]
    assert info["content_size"] == len(data)
    assert lz4.frame.decompress(frame) == data


def test_block_modes_roundtrip():
    """Default, accelerated and HC block modes round-trip, with and without the size
    header -> covers both lz4.c and lz4hc.c in the _block extension."""
    import lz4.block

    data = _payload()
    # "fast" only differs from "default" once acceleration is above 1.
    for mode, extra in (
        ("default", {}),
        ("fast", {"acceleration": 8}),
        ("high_compression", {}),
    ):
        packed = lz4.block.compress(data, mode=mode, **extra)
        assert lz4.block.decompress(packed) == data

        raw = lz4.block.compress(data, mode=mode, store_size=False, **extra)
        assert lz4.block.decompress(raw, uncompressed_size=len(data)) == data


def test_incremental_matches_oneshot():
    """Chunked LZ4FrameCompressor/Decompressor output decodes to the same bytes as
    one-shot calls -> the stateful frame context objects work on device."""
    import lz4.frame

    data = _payload()
    step = 7000
    with lz4.frame.LZ4FrameCompressor() as compressor:
        frame = compressor.begin(len(data))
        for i in range(0, len(data), step):
            frame += compressor.compress(data[i : i + step])
        frame += compressor.flush()

    decompressor = lz4.frame.LZ4FrameDecompressor()
    out = b"".join(
        decompressor.decompress(frame[i : i + 512]) for i in range(0, len(frame), 512)
    )
    assert decompressor.eof
    assert out == data == lz4.frame.decompress(frame)


def test_frame_file_roundtrip(tmp_path):
    """lz4.frame.open writes a standard .lz4 file to device storage in pieces and
    reads it back -> the file API streams, not only in-memory buffers."""
    import lz4.frame

    data = _payload()
    path = tmp_path / "events.lz4"
    with lz4.frame.open(path, "wb", compression_level=9) as f:
        for i in range(0, len(data), 7000):
            f.write(data[i : i + 7000])

    assert path.read_bytes()[:4] == b"\x04\x22\x4d\x18"  # LZ4 frame magic
    assert path.stat().st_size < len(data)
    with lz4.frame.open(path, "rb") as f:
        assert f.read() == data


def test_decodes_reference_cli_frame():
    """A frame written by the reference lz4 CLI decodes on device -> the wheel
    interoperates with lz4 outside Python, checksums verified."""
    import lz4.frame

    assert lz4.frame.decompress(CLI_FRAME) == CLI_PAYLOAD
