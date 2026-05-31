def test_hashtriemap():
    """rpds-py is a Rust port of immutable persistent data structures
    (used by jsonschema). HashTrieMap covers the PyO3 dict-like surface."""
    from rpds import HashTrieMap

    m = HashTrieMap()
    m1 = m.insert("a", 1).insert("b", 2)
    m2 = m1.insert("c", 3)

    # Persistence: m1 is unchanged by inserting into it.
    assert dict(m1) == {"a": 1, "b": 2}
    assert dict(m2) == {"a": 1, "b": 2, "c": 3}

    assert m1.get("a") == 1
    assert m1.get("missing") is None


def test_hashtrieset():
    """HashTrieSet — same PyO3 surface but set semantics."""
    from rpds import HashTrieSet

    s = HashTrieSet().insert(1).insert(2).insert(3)
    assert 2 in s
    assert 99 not in s
    assert len(s) == 3

    # Removing yields a new set, original unchanged.
    s2 = s.remove(2)
    assert 2 in s
    assert 2 not in s2
