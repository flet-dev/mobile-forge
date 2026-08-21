def test_pool():
    """Construct a Pool, which proves the cymem.cymem extension loaded and initialised.

    It reaches no allocation: Pool.__cinit__ only sets up the Python-side bookkeeping.
    """
    from cymem.cymem import Pool

    pool = Pool()
    assert pool is not None
