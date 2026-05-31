"""opaque is a ctypes wrapper around libopaque (the OPAQUE asymmetric
PAKE protocol). The C lib is supplied as a host dep (`flet-libopaque`)
in the mobile-forge recipe; the wheel needs pysodium too at runtime
(handled via mobile.patch adding `install_requires=['pysodium']`)."""


def test_registration_and_credential_roundtrip():
    """Run one full OPAQUE round: client → registration → server stores
    record; client → login → server verifies; both sides derive a session
    key. The roundtrip touches every libopaque C entry point pyopaque
    wraps."""
    import opaque

    pwd = b"correct horse battery staple"
    ids = opaque.Ids(idu=b"user", ids=b"server")

    # --- Registration ---
    secret_client, request = opaque.CreateRegistrationRequest(pwd)
    secret_server, response = opaque.CreateRegistrationResponse(request)
    record, export_key_reg = opaque.FinalizeRequest(secret_client, response, ids)
    assert isinstance(record, bytes)
    assert isinstance(export_key_reg, bytes)
    assert len(export_key_reg) > 0

    # --- Credential exchange (login) ---
    client_state, ke1 = opaque.CreateCredentialRequest(pwd)
    sk_server, ke2, _auth_req = opaque.CreateCredentialResponse(ke1, record, ids, b"")
    sk_client, _auth_resp, export_key_login = opaque.RecoverCredentials(
        ke2, client_state, b"", ids
    )

    # Both sides derived the same session key.
    assert sk_client == sk_server
    # Export key is stable across registration & login (same password).
    assert export_key_login == export_key_reg
