"""argon2-cffi-bindings ships ONLY the low-level CFFI bindings for the
Argon2 C library — module name `_argon2_cffi_bindings`. The high-level
ergonomic API (`argon2.PasswordHasher`, `argon2.exceptions`, etc.) lives
in the separate `argon2-cffi` package on PyPI. The mobile-forge recipe
only builds the bindings, so we exercise the low-level CFFI surface."""


def test_argon2_hash_roundtrip():
    """Compute a deterministic Argon2id hash + verify it. Touches both
    libargon2 hash and verify entry points through CFFI."""
    from _argon2_cffi_bindings import ffi, lib

    pwd = b"correct horse battery staple"
    salt = b"sixteen-byte-salt"  # 17 bytes is fine; libargon2 just hashes it

    # Argon2id (type=2), t=2, m=65536, parallelism=1, hashlen=32.
    # 256-byte buffer is comfortably above the encoded length for these
    # params; argon2_hash returns -31 ("Encoding failed") if too small.
    encoded = ffi.new("char[256]")
    rc = lib.argon2_hash(
        2,                # t_cost (iterations)
        65536,            # m_cost (kib)
        1,                # parallelism
        pwd, len(pwd),
        salt, len(salt),
        ffi.NULL, 32,     # raw output unused
        encoded, 256,
        2,                # Argon2_id
        0x13,             # ARGON2_VERSION_13
    )
    assert rc == 0, f"argon2_hash returned {rc}"

    enc_bytes = ffi.string(encoded)
    assert enc_bytes.startswith(b"$argon2id$"), enc_bytes

    # Verify with the correct password.
    rc = lib.argon2_verify(enc_bytes, pwd, len(pwd), 2)
    assert rc == 0, f"verify of correct pwd returned {rc}"

    # Verify with the wrong password — non-zero return.
    bad = b"wrong password"
    rc = lib.argon2_verify(enc_bytes, bad, len(bad), 2)
    assert rc != 0, "verify of wrong pwd unexpectedly succeeded"
