# murmurhash — MurmurHash2/3 (Cython, C++). https://pypi.org/project/murmurhash/
def test_hash():
    from murmurhash import hash

    assert hash("apple") == hash("apple")
    assert isinstance(hash("apple"), int)
