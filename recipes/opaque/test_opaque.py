"""opaque is a ctypes wrapper around libopaque (the OPAQUE asymmetric
PAKE protocol). The C lib is supplied as a host dep (`flet-libopaque`)
in the mobile-forge recipe; the wheel needs pysodium too at runtime
(handled via mobile.patch adding `install_requires=['pysodium']`)."""


def test_registration_and_credential_roundtrip():
    """Run one full OPAQUE round: client → registration → server stores
    record; client → login → server verifies; both sides derive a session
    key. The roundtrip touches every libopaque C entry point pyopaque
    wraps.

    Tuple-unpack order is per the upstream `opaque/__init__.py`:
      CreateRegistrationRequest  → (sec, request)
      CreateRegistrationResponse → (sec, pub)
      FinalizeRequest            → (rec, export_key)
      CreateCredentialRequest    → (pub, sec)   ← NB: pub first
      CreateCredentialResponse   → (resp, sk, sec)
      RecoverCredentials         → (sk, authU, export_key)
    """
    import opaque

    pwd = b"correct horse battery staple"
    ids = opaque.Ids(idu=b"user", ids=b"server")

    # --- Registration ---
    secret_client_reg, request = opaque.CreateRegistrationRequest(pwd)
    _secret_server_reg, response = opaque.CreateRegistrationResponse(request)
    record, export_key_reg = opaque.FinalizeRequest(
        secret_client_reg, response, ids
    )
    assert isinstance(record, bytes)
    assert isinstance(export_key_reg, bytes)
    assert len(export_key_reg) > 0

    # --- Credential exchange (login) ---
    # NB: CreateCredentialRequest returns (pub, sec) — pub first.
    ke1, client_state = opaque.CreateCredentialRequest(pwd)
    # CreateCredentialResponse returns (resp, sk, sec).
    ke2, sk_server, _sec = opaque.CreateCredentialResponse(
        ke1, record, ids, b""
    )
    sk_client, _auth, export_key_login = opaque.RecoverCredentials(
        ke2, client_state, b"", ids
    )

    # Both sides derived the same session key.
    assert sk_client == sk_server
    # Export key is stable across registration & login (same password).
    assert export_key_login == export_key_reg
