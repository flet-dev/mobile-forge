def test_secretbox_roundtrip():
    """pysodium is the lightweight libsodium ctypes wrapper (different from
    PyNaCl, which is the cffi wrapper). Round-trip through crypto_secretbox
    confirms the libsodium shared lib is loadable and the FFI signatures
    match."""
    import pysodium

    key = pysodium.randombytes(pysodium.crypto_secretbox_KEYBYTES)
    nonce = pysodium.randombytes(pysodium.crypto_secretbox_NONCEBYTES)
    plaintext = b"hello mobile-forge"

    ciphertext = pysodium.crypto_secretbox(plaintext, nonce, key)
    assert pysodium.crypto_secretbox_open(ciphertext, nonce, key) == plaintext


def test_hash_known_vector():
    """libsodium's generichash (BLAKE2b). Empty input is a stable vector."""
    import pysodium

    out = pysodium.crypto_generichash(b"")
    # BLAKE2b-256 of empty input — well-known reference vector.
    assert out.hex() == (
        "0e5751c026e543b2e8ab2eb06099daa1d1e5df47778f7787faab45cdf12fe3a8"
    )
