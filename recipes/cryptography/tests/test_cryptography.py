def test_fernet():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    f = Fernet(key)
    msg = b"my deep dark secret"
    token = f.encrypt(msg)
    assert f.decrypt(token) == msg


def test_x509():
    from textwrap import dedent

    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from cryptography.x509.oid import NameOID

    cert_pem = dedent(
        """
        -----BEGIN CERTIFICATE-----
        MIIEhDCCA2ygAwIBAgIIF2d9E030vlcwDQYJKoZIhvcNAQELBQAwVDELMAkGA1UE
        BhMCVVMxHjAcBgNVBAoTFUdvb2dsZSBUcnVzdCBTZXJ2aWNlczElMCMGA1UEAxMc
        R29vZ2xlIEludGVybmV0IEF1dGhvcml0eSBHMzAeFw0xODA0MTcxMzI0MzhaFw0x
        ODA3MTAxMjM5MDBaMGkxCzAJBgNVBAYTAlVTMRMwEQYDVQQIDApDYWxpZm9ybmlh
        MRYwFAYDVQQHDA1Nb3VudGFpbiBWaWV3MRMwEQYDVQQKDApHb29nbGUgSW5jMRgw
        FgYDVQQDDA93d3cuYW5kcm9pZC5jb20wggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAw
        ggEKAoIBAQC3t8zd3s9oSLFUkogYhD//BoFwvtHnpUHW2n9g3KiAXCHHG5+8QD4Q
        abgAzrpeQqewWngE9B3Feq4rUo9vsk0UpB7Pj97TAgkkmpRMcW0lU4p4rKNhDfri
        c+SvnuZuy048v8Ta7DtMymuCIyejekjTg7Gf/U46PqK87ZbV5RTadSgfvlymnkQb
        SwJLUA8qe/H98bEARpQLyJvWi8dUSurpfKHdbXfd1Dk9GACHNAX9A4bV0BdQBmPu
        6BMGeY5O4CYwwM51U/W+ptyc5eFRMi10up1cck3Udwl/jw5OAx5NP7geuxuIc4uu
        l41Zwbnr5v6sdJJsWMvMg7ot/97+EHvXAgMBAAGjggFDMIIBPzATBgNVHSUEDDAK
        BggrBgEFBQcDATAaBgNVHREEEzARgg93d3cuYW5kcm9pZC5jb20waAYIKwYBBQUH
        AQEEXDBaMC0GCCsGAQUFBzAChiFodHRwOi8vcGtpLmdvb2cvZ3NyMi9HVFNHSUFH
        My5jcnQwKQYIKwYBBQUHMAGGHWh0dHA6Ly9vY3NwLnBraS5nb29nL0dUU0dJQUcz
        MB0GA1UdDgQWBBSYOxV7LRH/9yKSFL5jLJfhwZxCUDAMBgNVHRMBAf8EAjAAMB8G
        A1UdIwQYMBaAFHfCuFCaZ3Z2sS3ChtCDoH6mfrpLMCEGA1UdIAQaMBgwDAYKKwYB
        BAHWeQIFAzAIBgZngQwBAgIwMQYDVR0fBCowKDAmoCSgIoYgaHR0cDovL2NybC5w
        a2kuZ29vZy9HVFNHSUFHMy5jcmwwDQYJKoZIhvcNAQELBQADggEBAI4fv5P+VLSE
        /f+hOoPuxWx2TEDdc/Gt2u3XUiGkMrOSW2k1ob0kUjBDILhear3tpp+V5N5H0NzZ
        Ymvpbbl3ZD5Bk5Co9FIJwFNMfGAlzSAduuYdAblOXTkLzlyLwn5qbzDjbkBIS+0O
        l+1zga+3gZGYbDQiByFyq8P/uAKzc0BAX82bgXDkIC3E26YvvTnUpkKh6l6bOOTB
        xaTg8Uh6KsKGch837BDbNegs3wHw3T3s7PC+H7dvqjELqN7y2GNNA361/aPPCWgs
        jUsy3XnYSd8og34IzY3+W2b3TrU8P+p+pBwOjgXuNHZwobU+3/e2s4/0AfDilpI0
        KX/1hroho1I=
        -----END CERTIFICATE-----
    """
    ).encode("ASCII")
    cert = x509.load_pem_x509_certificate(cert_pem, default_backend())
    domain = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert domain == "www.android.com"


def test_openssl_is_the_static_one_from_the_support_tree():
    """These wheels statically link whatever OpenSSL the Python support tree ships,
    not the 4.x upstream's own wheels carry. Several algorithms the README lists as
    unavailable are unavailable *because* of that, so this is a tripwire on the
    support tree rather than a version check.

    It has fired once and been honoured. Wheels published up to 2026-08-22 carry
    3.0.20; the support tree pinned at PYTHON_BUILD_RELEASE=20260730 builds 3.5.7,
    so a republish moves every consumer from one to the other without a version
    change to signal it. Both were checked: the legacy-provider and round-trip
    tests below pass identically on each. A third value has NOT been checked —
    when this goes red again, re-run the unavailable-algorithm list in the README
    against the new OpenSSL before widening the tuple."""
    from cryptography.hazmat.backends.openssl.backend import backend

    text = backend.openssl_version_text()
    assert text.startswith(("OpenSSL 3.0.", "OpenSSL 3.5.")), text


def test_legacy_provider_ciphers_are_unavailable():
    """The OpenSSL legacy provider is not in the wheel (it lives in a separate
    ossl-modules/legacy.so that a static build has no path to), so the ciphers it
    holds raise instead of working. AES and 3DES are in the default provider and
    keep working — see the round-trip tests above."""
    import pytest
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives.ciphers import Cipher, modes

    try:
        from cryptography.hazmat.decrepit.ciphers.algorithms import ARC4
    except ImportError:
        from cryptography.hazmat.primitives.ciphers.algorithms import ARC4

    with pytest.raises(UnsupportedAlgorithm):
        Cipher(ARC4(b"\x00" * 16), mode=None).encryptor().update(b"probe")

    # AES is in the default provider, so the same call shape must succeed.
    from cryptography.hazmat.primitives.ciphers.algorithms import AES

    encryptor = Cipher(AES(b"\x00" * 16), modes.CBC(b"\x00" * 16)).encryptor()
    assert len(encryptor.update(b"\x00" * 16)) == 16


def test_fernet_and_scrypt_round_trip():
    """The two primitives the example app relies on: a scrypt-derived key and a
    Fernet seal/open cycle. Both are default-provider, so both must work on every
    slice regardless of the legacy gap above."""
    import base64

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    key = Scrypt(salt=b"\x01" * 16, length=32, n=2**14, r=8, p=1).derive(
        b"passphrase"
    )
    token = Fernet(base64.urlsafe_b64encode(key)).encrypt(b"on-device secret")
    assert Fernet(base64.urlsafe_b64encode(key)).decrypt(token) == b"on-device secret"
