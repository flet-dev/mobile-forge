def test_import_aes():
    """`from Crypto.Cipher import AES` walks through
    `Crypto/Util/_raw_api.py`, which on import resolves its native-call
    interface. Without cffi installed, that code falls back to
    `ctypes.pythonapi.PyObject_GetBuffer` — and on Android that attribute
    access fails with `AttributeError: undefined symbol: PyObject_GetBuffer`
    because Flet's bootstrap loads libpython.so via Dart's
    DynamicLibrary.open which defaults to RTLD_LOCAL, hiding libpython
    symbols from `dlsym(RTLD_DEFAULT)`. The recipe's mobile.patch adds
    `install_requires=['cffi']` so pip pulls cffi alongside, the cffi
    fast path wins, and the broken ctypes path never runs."""
    from Crypto.Cipher import AES

    assert hasattr(AES, "new")
    assert AES.MODE_CBC > 0


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
