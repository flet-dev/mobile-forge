def test_basic():
    """Unicode-aware patterns the stdlib `re` can't handle — that's why the
    `regex` C extension is shipped as a recipe."""
    import regex

    # Property-class match (\p{L} = any unicode letter). stdlib `re` raises.
    m = regex.match(r"\p{L}+", "Καλημέρα")
    assert m is not None
    assert m.group(0) == "Καλημέρα"

    # Possessive quantifier + atomic group — also regex-only syntax.
    m = regex.match(r"(?>a+)b", "aaab")
    assert m is not None
    assert m.group(0) == "aaab"


def test_findall():
    import regex

    assert regex.findall(r"\d+", "10 frogs, 200 toads") == ["10", "200"]
