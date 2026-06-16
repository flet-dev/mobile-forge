def test_hash():
    from murmurhash import hash

    assert hash("apple") == hash("apple")
    assert isinstance(hash("apple"), int)
