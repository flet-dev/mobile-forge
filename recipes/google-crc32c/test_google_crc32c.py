def test_known_vectors():
    """google-crc32c provides hardware-accelerated CRC32C (Castagnoli).
    The C extension is the recipe's purpose — without it the package
    falls back to a slow Python impl. Use known test vectors from RFC 3720
    Appendix B."""
    import google_crc32c

    # RFC 3720 Annex B (iSCSI / SCTP CRC32C reference values)
    assert google_crc32c.value(b"") == 0
    assert google_crc32c.value(b"123456789") == 0xE3069283
    assert google_crc32c.value(b"a") == 0xC1D04330


def test_chunked_value():
    """The Checksum object's update-then-digest path lives in C too."""
    import google_crc32c

    h = google_crc32c.Checksum()
    h.update(b"123")
    h.update(b"456")
    h.update(b"789")
    assert int.from_bytes(h.digest(), "big") == 0xE3069283
