def test_basic():
    """A capacity eviction drops the least recently used key, and keys() is MRU-first."""
    from lru import LRU

    data = LRU(3)
    data[1] = None
    data[2] = None
    data[3] = None
    data[1]  # touch key 1 (most-recently-used)
    data[4] = None  # evicts least-recently-used (= 2)
    assert data.keys() == [4, 1, 3]
