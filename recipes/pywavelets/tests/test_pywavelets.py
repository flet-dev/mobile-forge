import numpy as np


def test_dwt_roundtrip():
    """dwt/idwt round-trip -> exercises the _dwt extension + c_wt convolution."""
    import pywt

    x = np.linspace(0.0, 1.0, 64)
    ca, cd = pywt.dwt(x, "db2")
    y = pywt.idwt(ca, cd, "db2")
    assert np.allclose(x, y[: len(x)])


def test_wavedec_multilevel():
    """wavedec/waverec multilevel -> exercises the _pywt wavelet objects."""
    import pywt

    x = np.sin(np.linspace(0.0, 8.0 * np.pi, 128))
    coeffs = pywt.wavedec(x, "haar", level=3)
    assert len(coeffs) == 4
    y = pywt.waverec(coeffs, "haar")
    assert np.allclose(x, y[: len(x)])


def test_swt():
    """Stationary wavelet transform -> exercises the _swt extension."""
    import pywt

    x = np.arange(32, dtype=np.float64)
    coeffs = pywt.swt(x, "db1", level=2)
    assert len(coeffs) == 2
    y = pywt.iswt(coeffs, "db1")
    assert np.allclose(x, y)


def test_cwt_complex_wavelet():
    """cwt with a complex Morlet -> exercises the _cwt extension and the
    C99 complex code paths in the vendored C library."""
    import pywt

    t = np.linspace(0.0, 1.0, 200)
    x = np.sin(40.0 * np.pi * t)
    coefs, freqs = pywt.cwt(x, np.arange(1, 16), "cmor1.5-1.0")
    assert coefs.shape == (15, 200)
    assert np.iscomplexobj(coefs)
    assert np.isfinite(coefs).all()
    assert len(freqs) == 15
