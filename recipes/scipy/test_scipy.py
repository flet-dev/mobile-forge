import numpy as np


def test_linalg_solve():
    """linalg.solve -> LAPACK getrf/getrs through OpenBLAS."""
    from scipy import linalg

    a = np.array([[3.0, 1.0], [1.0, 2.0]])
    b = np.array([9.0, 8.0])
    x = linalg.solve(a, b)
    assert np.allclose(a @ x, b)
    assert np.allclose(x, [2.0, 3.0])


def test_linalg_svd():
    """linalg.svd -> LAPACK gesdd; reconstruct the matrix from U S Vt."""
    from scipy import linalg

    m = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    u, s, vt = linalg.svd(m, full_matrices=False)
    assert np.allclose(u @ np.diag(s) @ vt, m)
    assert s[0] > s[1] > 0


def test_linalg_eigh():
    """eigvalsh -> symmetric eigensolver (LAPACK syevd) through OpenBLAS."""
    from scipy import linalg

    a = np.array([[2.0, 1.0], [1.0, 2.0]])
    w = np.sort(linalg.eigvalsh(a))
    assert np.allclose(w, [1.0, 3.0])


def test_linalg_cholesky():
    """cholesky -> LAPACK potrf of an SPD matrix; L @ L.T reconstructs it."""
    from scipy import linalg

    a = np.array([[4.0, 2.0], [2.0, 3.0]])
    L = linalg.cholesky(a, lower=True)
    assert np.allclose(L @ L.T, a)


def test_fft():
    """scipy.fft (vendored ducc) -> fft/ifft roundtrip; DC term equals the sum."""
    from scipy import fft

    x = np.array([1.0, 2.0, 1.0, -1.0, 1.5, 0.0, 0.0, 0.0])
    y = fft.fft(x)
    assert np.allclose(y[0].real, x.sum())
    assert np.allclose(fft.ifft(y).real, x)


def test_special_real():
    """special.gamma(0.5) == sqrt(pi); gamma(5) == 4!; erf(0) == 0."""
    import math
    from scipy import special

    assert abs(special.gamma(0.5) - math.sqrt(math.pi)) < 1e-12
    assert abs(special.gamma(5.0) - 24.0) < 1e-9
    assert abs(special.erf(0.0)) < 1e-15


def test_special_complex():
    """Complex special function -> exercises scipy.special's C99 complex math
    (clog/cpow in _complexstuff.h). loggamma(1) == 0; loggamma(1+1j) is finite."""
    from scipy import special

    assert abs(special.loggamma(1.0)) < 1e-12
    z = special.loggamma(1 + 1j)
    assert np.isfinite(z.real) and np.isfinite(z.imag)


def test_sparse_spsolve():
    """sparse CSC matrix + sparse.linalg.spsolve (SuperLU)."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve

    a = sparse.csc_matrix([[3.0, 1.0], [1.0, 2.0]])
    b = np.array([9.0, 8.0])
    x = spsolve(a, b)
    assert np.allclose(x, [2.0, 3.0])


def test_optimize():
    """optimize.minimize (BFGS) on a quadratic -> minimum at (1, 2.5)."""
    from scipy import optimize

    res = optimize.minimize(
        lambda p: (p[0] - 1.0) ** 2 + (p[1] - 2.5) ** 2, [0.0, 0.0], method="BFGS"
    )
    assert res.success
    assert np.allclose(res.x, [1.0, 2.5], atol=1e-4)


def test_integrate():
    """integrate.quad of x^2 over [0, 1] == 1/3 (QUADPACK, f2c)."""
    from scipy import integrate

    val, _ = integrate.quad(lambda x: x**2, 0.0, 1.0)
    assert abs(val - 1.0 / 3.0) < 1e-10


def test_interpolate():
    """interpolate.interp1d -> linear interp of a known line (FITPACK, f2c)."""
    from scipy import interpolate

    x = np.array([0.0, 1.0, 2.0])
    f = interpolate.interp1d(x, 2.0 * x + 1.0)
    assert abs(float(f(0.5)) - 2.0) < 1e-12


def test_stats():
    """stats.norm -> standard-normal cdf(0) == 0.5, pdf(0) == 1/sqrt(2*pi)."""
    from scipy import stats

    assert abs(stats.norm.cdf(0.0) - 0.5) < 1e-12
    assert abs(stats.norm.pdf(0.0) - 1.0 / np.sqrt(2.0 * np.pi)) < 1e-12
