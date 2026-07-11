def test_uuid4_random_and_versioned():
    """uuid4() yields distinct version-4 UUIDs (exercises the rand-backed Rust path)."""
    import uuid_utils

    a = uuid_utils.uuid4()
    b = uuid_utils.uuid4()
    assert a != b
    assert a.version == 4


def test_uuid5_is_deterministic():
    """uuid5() is a pure namespace+name hash: same inputs match, different names differ."""
    import uuid_utils

    ns = uuid_utils.NAMESPACE_DNS
    assert uuid_utils.uuid5(ns, "flet.dev") == uuid_utils.uuid5(ns, "flet.dev")
    assert uuid_utils.uuid5(ns, "flet.dev") != uuid_utils.uuid5(ns, "example.com")
    assert uuid_utils.uuid5(ns, "flet.dev").version == 5


def test_str_roundtrip():
    """A generated UUID stringifies and parses back to an equal UUID."""
    import uuid_utils

    u = uuid_utils.uuid4()
    assert uuid_utils.UUID(str(u)) == u
