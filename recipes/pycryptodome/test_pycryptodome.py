def test_aes_cbc_roundtrip():
    """pycryptodome is a from-scratch C-extension crypto library (the
    `Crypto.*` namespace). Encrypt + decrypt covers the AES C code."""
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
    from Crypto.Util.Padding import pad, unpad

    key = get_random_bytes(32)  # AES-256
    iv = get_random_bytes(16)
    plaintext = b"hello mobile-forge"

    encryptor = AES.new(key, AES.MODE_CBC, iv)
    ct = encryptor.encrypt(pad(plaintext, AES.block_size))

    decryptor = AES.new(key, AES.MODE_CBC, iv)
    assert unpad(decryptor.decrypt(ct), AES.block_size) == plaintext


def test_sha256_vector():
    """SHA-256 has well-known reference vectors. NIST FIPS 180-4."""
    from Crypto.Hash import SHA256

    h = SHA256.new()
    h.update(b"abc")
    assert h.hexdigest() == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
