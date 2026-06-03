def test_secretbox_roundtrip():
    """PyNaCl is the Python binding for libsodium (vendored). SecretBox
    (authenticated symmetric encryption) is the canonical demo."""
    import nacl.secret
    import nacl.utils

    key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)
    box = nacl.secret.SecretBox(key)

    plaintext = b"hello recipe-tester"
    nonce = nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE)
    ciphertext = box.encrypt(plaintext, nonce)

    box2 = nacl.secret.SecretBox(key)
    assert box2.decrypt(ciphertext) == plaintext


def test_signing_roundtrip():
    """Ed25519 keypair / sign / verify — covers libsodium's
    crypto_sign_* code path."""
    import nacl.signing

    signing_key = nacl.signing.SigningKey.generate()
    verify_key = signing_key.verify_key

    message = b"a signed message"
    signed = signing_key.sign(message)

    # Verification raises BadSignatureError on tamper.
    assert verify_key.verify(signed) == message
