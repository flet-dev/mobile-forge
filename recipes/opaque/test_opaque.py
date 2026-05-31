"""opaque is a ctypes wrapper around libopaque (the OPAQUE asymmetric
PAKE protocol). The C lib is supplied as a host dep (`flet-libopaque`)
in the mobile-forge recipe; the wheel needs pysodium too at runtime
(handled via mobile.patch adding `install_requires=['pysodium']`)."""


def test_registration_and_credential_roundtrip():
    """Run one full OPAQUE round: client → registration → server stores
    user record; client → login → server verifies; both sides derive a
    session key. The roundtrip touches every libopaque C entry point
    pyopaque wraps.

    Function-by-function this is the API per `opaque/__init__.py`:
      CreateRegistrationRequest(pwd)        → (sec, request)
      CreateRegistrationResponse(request)   → (sec, pub)
      FinalizeRequest(sec, pub, ids)        → (registration_record, export_key)
      StoreUserRecord(sec, registration_record) → user_record
        — combines the server's REGISTER_SECRET (skS+kU) with the
          client's REGISTRATION_RECORD into the USER_RECORD that
          CreateCredentialResponse expects. The byte layout differs
          between sec and user_record, so we MUST use this helper
          rather than naive concatenation.
      CreateCredentialRequest(pwd)          → (pub, sec)   ← NB: pub first
      CreateCredentialResponse(pub, rec, ids, ctx) → (resp, sk, sec)
      RecoverCredentials(resp, sec, ctx, ids) → (sk, authU, export_key)
    """
    import opaque

    pwd = b"correct horse battery staple"
    ids = opaque.Ids(idu=b"user", ids=b"server")

    # --- Registration ---
    secret_client_reg, request = opaque.CreateRegistrationRequest(pwd)
    secret_server_reg, response = opaque.CreateRegistrationResponse(request)
    registration_record, export_key_reg = opaque.FinalizeRequest(
        secret_client_reg, response, ids
    )
    assert isinstance(registration_record, bytes)
    assert isinstance(export_key_reg, bytes)
    assert len(export_key_reg) > 0

    # Server stores the long-lived user record (server's sec + client's
    # registration_record, properly rearranged by libopaque).
    user_record = opaque.StoreUserRecord(secret_server_reg, registration_record)

    # --- Credential exchange (login) ---
    ke1, client_state = opaque.CreateCredentialRequest(pwd)
    ke2, sk_server, _server_session_sec = opaque.CreateCredentialResponse(
        ke1, user_record, ids, b""
    )
    sk_client, _authU, export_key_login = opaque.RecoverCredentials(
        ke2, client_state, b"", ids
    )

    # Both sides derived the same session key.
    assert sk_client == sk_server
    # Export key is stable across registration & login (same password).
    assert export_key_login == export_key_reg
