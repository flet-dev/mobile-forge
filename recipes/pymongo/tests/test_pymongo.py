def test_bson_roundtrip():
    """pymongo bundles a `_cbson` C extension that encodes BSON. We can
    exercise it without a MongoDB server by going through bson directly."""
    import bson

    doc = {
        "_id": 42,
        "name": "mobile-forge",
        "tags": ["recipes", "ci"],
        "nested": {"version": 1, "active": True},
    }
    raw = bson.encode(doc)
    assert isinstance(raw, bytes)
    assert bson.decode(raw) == doc


def test_objectid():
    """ObjectId() generates a 12-byte id — implemented in C for speed."""
    from bson.objectid import ObjectId

    oid = ObjectId()
    assert len(oid.binary) == 12
    # Round-trip through hex.
    assert ObjectId(str(oid)) == oid


def test_client_offline():
    """Instantiating MongoClient with `connect=False` doesn't open a
    socket — confirms the import + class construction work, which is the
    most we can do without a real server."""
    from pymongo import MongoClient

    c = MongoClient("mongodb://localhost:27017", connect=False)
    assert c is not None
    c.close()
