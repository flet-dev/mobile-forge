# srsly — bundled serializers (json/msgpack, C). https://pypi.org/project/srsly/
def test_json():
    import srsly

    obj = {"a": 1, "b": [1, 2, 3]}
    assert srsly.json_loads(srsly.json_dumps(obj)) == obj


def test_msgpack():
    import srsly

    obj = [1, "two", 3.0]
    assert srsly.msgpack_loads(srsly.msgpack_dumps(obj)) == obj
