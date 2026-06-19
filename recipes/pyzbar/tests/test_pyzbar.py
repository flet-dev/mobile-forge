def test_libzbar_loads():
    """The patched ctypes loader finds + dlopens the bundled libzbar on-device
    (the whole point of the recipe). Raises ImportError if libzbar is missing."""
    from pyzbar import zbar_library

    libzbar, _deps = zbar_library.load()
    assert libzbar is not None


def test_decode_scan_path():
    """A blank 64x64 greyscale (Y800) buffer scans cleanly through libzbar.

    Importing pyzbar.pyzbar already loaded libzbar; this exercises the full
    ctypes -> libzbar decode path with no symbols present (no camera, files, or
    network, so it's emulator/simulator-safe)."""
    from pyzbar.pyzbar import decode

    assert decode((bytes(64 * 64), 64, 64)) == []
