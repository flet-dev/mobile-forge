def test_filter():
    """jq is a Cython wrapper around libjq (C). Apply a filter program
    against a small JSON document — exercises the libjq parser + executor."""
    import jq

    data = {
        "users": [
            {"name": "Ada", "active": True},
            {"name": "Grace", "active": False},
            {"name": "Linus", "active": True},
        ]
    }
    program = jq.compile('.users[] | select(.active) | .name')
    active = program.input_value(data).all()
    assert active == ["Ada", "Linus"]


def test_first():
    """The `.first()` API path is a different libjq invocation."""
    import jq

    name = jq.first(".name", {"name": "mobile-forge", "id": 42})
    assert name == "mobile-forge"
