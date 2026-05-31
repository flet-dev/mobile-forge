def test_from_json():
    """jiter is a Rust-backed fast JSON parser (used by pydantic). Parsing
    a mixed-type doc through `from_json` exercises the PyO3 boundary."""
    import jiter

    raw = b'{"id": 7, "tags": ["a", "b"], "ratio": 1.5, "ok": true, "n": null}'
    parsed = jiter.from_json(raw)
    assert parsed == {
        "id": 7,
        "tags": ["a", "b"],
        "ratio": 1.5,
        "ok": True,
        "n": None,
    }


def test_partial_mode():
    """`partial_mode='trailing-strings'` allows incomplete strings — a
    jiter-specific feature pydantic relies on for streaming."""
    import jiter

    parsed = jiter.from_json(b'{"name": "Ad', partial_mode="trailing-strings")
    assert parsed == {"name": "Ad"}
