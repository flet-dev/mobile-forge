# preshed — fast hash maps (Cython, C++; uses cymem/murmurhash).
# https://pypi.org/project/preshed/
def test_map():
    from preshed.maps import PreshMap

    # NB: preshed reserves keys 0 and 1 as internal EMPTY/DELETED sentinels —
    # they round-trip but don't count toward len(), so use larger keys here.
    m = PreshMap()
    m[10] = 100
    m[20] = 200
    m[30] = 300

    assert m[10] == 100
    assert m[20] == 200
    assert m[30] == 300
    assert len(m) == 3
    assert m[999] is None  # missing key
    assert 10 in m and 999 not in m
