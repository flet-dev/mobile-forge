"""Smoke test for the faiss-cpu recipe.

The PyPI package is `faiss-cpu` but the import name is `faiss`. Importing it
loads the SWIG-generated `_swigfaiss` C++ extension (which statically links
libfaiss + OpenBLAS, and — on iOS — the serial-stub libomp), proving the whole
CMake/SWIG cross-build loads on-device.
"""


def test_import_faiss():
    import faiss

    # IndexFlatL2 is the canonical brute-force L2 index; its presence proves the
    # swigfaiss C++ bindings loaded.
    assert hasattr(faiss, "IndexFlatL2")


def test_flat_index_search():
    """Build a flat L2 index, add vectors, and run a nearest-neighbour search.
    Exercises the core C++ search path (distance computation goes through the
    linked OpenBLAS, and the index build/search touch faiss's OpenMP code)."""
    import numpy as np
    import faiss

    d = 16
    xb = np.random.RandomState(0).rand(100, d).astype("float32")
    index = faiss.IndexFlatL2(d)
    index.add(xb)
    assert index.ntotal == 100

    # Query with the first 5 database vectors — each vector's nearest neighbour
    # is itself (distance ~0), a deterministic correctness check.
    distances, ids = index.search(xb[:5], 1)
    assert (ids[:, 0] == np.arange(5)).all()
    assert (distances[:, 0] < 1e-4).all()
