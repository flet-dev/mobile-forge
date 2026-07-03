def test_basic():
    import ujson

    data = {
        "name": "flet",
        "version": 1,
        "active": True,
        "tags": ["mobile", "python"],
        "ratio": 3.141592653589793,
        "nothing": None,
    }
    encoded = ujson.dumps(data)
    assert isinstance(encoded, str)

    decoded = ujson.loads(encoded)
    assert decoded == data


def test_double_conversion():
    import ujson

    pi = 3.141592653589793
    assert ujson.loads(ujson.dumps(pi)) == pi
