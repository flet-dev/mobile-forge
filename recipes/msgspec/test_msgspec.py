def test_struct_roundtrip():
    """msgspec is a Cython/C-backed schema validator. Encode + decode a
    Struct via JSON to exercise both directions of the native codec."""
    import msgspec

    class Person(msgspec.Struct):
        name: str
        age: int
        tags: list[str] = []

    p = Person(name="Ada", age=37, tags=["math", "engineering"])
    payload = msgspec.json.encode(p)
    assert isinstance(payload, bytes)
    assert msgspec.json.decode(payload, type=Person) == p


def test_invalid_input_raises():
    """Validation errors are raised in C, not Python — confirms the schema
    enforcement path is wired."""
    import msgspec

    class Person(msgspec.Struct):
        name: str
        age: int

    try:
        msgspec.json.decode(b'{"name": "Ada", "age": "not-a-number"}', type=Person)
    except msgspec.ValidationError:
        return
    raise AssertionError("expected ValidationError")
