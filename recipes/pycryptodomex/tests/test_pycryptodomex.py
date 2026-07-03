def test_aes_gcm_roundtrip():
    """pycryptodomex is the same C library as pycryptodome but installed
    under the `Cryptodome.*` namespace to coexist with `pycrypto`. AES-GCM
    is the most common AEAD use case."""
    from Cryptodome.Cipher import AES
    from Cryptodome.Random import get_random_bytes

    key = get_random_bytes(32)
    nonce = get_random_bytes(12)
    aad = b"recipe-test"
    plaintext = b"a quiet sentence to encrypt"

    enc = AES.new(key, AES.MODE_GCM, nonce=nonce)
    enc.update(aad)
    ct, tag = enc.encrypt_and_digest(plaintext)

    dec = AES.new(key, AES.MODE_GCM, nonce=nonce)
    dec.update(aad)
    assert dec.decrypt_and_verify(ct, tag) == plaintext


def test_sha256_vector():
    """Sanity-check the hash C code is wired under the Cryptodome namespace."""
    from Cryptodome.Hash import SHA256

    h = SHA256.new()
    h.update(b"abc")
    assert h.hexdigest() == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
