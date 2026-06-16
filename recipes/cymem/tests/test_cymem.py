def test_pool():
    from cymem.cymem import Pool

    # Constructing the Cython Pool proves the extension loaded.
    pool = Pool()
    assert pool is not None
