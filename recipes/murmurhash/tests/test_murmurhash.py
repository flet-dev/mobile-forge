def test_hash():
    """murmurhash is a Cython binding for MurmurHash3_x86_32. `hash` is a
    `cpdef` in `mrmr`, the only extension in the wheel, so this reaches the
    whole native surface the package exposes to Python. It asserts only that
    two calls agree with each other: a platform returning different numbers
    from desktop would still pass, so this is not evidence of the constants
    the README quotes."""
    from murmurhash import hash

    assert hash("apple") == hash("apple")
    assert isinstance(hash("apple"), int)
