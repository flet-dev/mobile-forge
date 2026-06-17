def test_libmagic_loads():
    """Importing magic runs the patched ctypes loader for the bundled libmagic
    (raises ImportError on-device if libmagic can't be found/loaded)."""
    import magic

    assert magic.libmagic is not None


def test_detect_from_buffer():
    """from_buffer() identifies a type through libmagic + the bundled magic.mgc
    database — proving the .so AND the magic DB both load and a real detection
    runs through the C library (in-memory, so emulator/sim-safe).

    Uses a minimal but VALID PNG (signature + a real IHDR chunk); the bare
    8-byte signature alone is reported as generic "data"."""
    import magic

    png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    )
    assert "PNG" in magic.from_buffer(png)
    assert magic.from_buffer(png, mime=True) == "image/png"
