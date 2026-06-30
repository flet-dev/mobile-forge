def test_basic():
    """Load scipy and exercise the BLAS/LAPACK backend (Accelerate on iOS)."""
    import numpy as np
    from scipy import linalg

    a = np.array([[3.0, 1.0], [1.0, 2.0]])
    b = np.array([9.0, 8.0])
    x = linalg.solve(a, b)  # LAPACK getrf/getrs -> proves BLAS/LAPACK works
    assert np.allclose(a @ x, b)
