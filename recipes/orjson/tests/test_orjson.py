def test_basic():
    """Confirm the wheel loads and round-trips a representative payload."""
    import orjson

    payload = {
        "library": "orjson",
        "version": orjson.__version__,
        "active": True,
        "tags": ["mobile", "python", "flet"],
        "ratio": 3.141592653589793,
        "nothing": None,
    }

    encoded = orjson.dumps(payload)
    assert isinstance(encoded, bytes)  # orjson returns bytes, not str

    decoded = orjson.loads(encoded)
    assert decoded == payload


def test_numeric_precision():
    """Round-trip a float at the f64 precision boundary."""
    import orjson

    pi = 3.141592653589793
    assert orjson.loads(orjson.dumps(pi)) == pi
