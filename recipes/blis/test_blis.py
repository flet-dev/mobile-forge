def test_import_blis():
    """Forces `blis/cy.cpython-*.so` + `blis/py.cpython-*.so` to load, and
    transitively `import numpy`. The published `numpy-2.2.2-4` wheel on
    pypi.flet.dev has NO `Requires-Dist: flet-libcpp-shared` in METADATA,
    so a blis-only Flet app doesn't ship libc++_shared.so. On x86_64,
    numpy's `_multiarray_umath.so` then fails to dlopen — `import numpy`
    bubbles up an ImportError to the blis side. arm64 multiarray happens
    not to need libcpp, so the basic `import blis` survives there."""
    import blis

    assert hasattr(blis, "py")


def test_einsum():
    import numpy as np
    from blis.py import einsum

    a = np.array([[1.0, 2.0], [3.0, 4.0]])
    b = np.array([[2.0, 3.0], [5.0, 7.0]])
    np.testing.assert_equal(
        np.array([[12.0, 17.0], [26.0, 37.0]]), einsum("ab,bc->ac", a, b)
    )


def test_numpy_fft():
    """The libcpp_shared canary that always fires when libcpp is missing,
    regardless of arch. blis pulls numpy transitively, and
    `_pocketfft_umath.so` carries DT_NEEDED=[libc++_shared.so] on both
    arm64 AND x86_64. Without the recipe's libcpp host dep (and a
    rebuilt numpy that carries the Requires-Dist), the dlopen aborts
    with `library "libc++_shared.so" not found`. Mirrors the canary
    added in flet-dev/mobile-forge#58 to numpy's own tests."""
    import numpy as np

    x = np.cos(2 * np.pi * 2 * np.arange(8) / 8)
    spectrum = np.fft.fft(x)
    magnitudes = np.abs(spectrum)
    # 8-point FFT of pure cos(2π·2·n/8) has equal-magnitude peaks at
    # bins 2 and 6 (N/2 = 4 for unit cosine).
    assert magnitudes[2] > 3.9
    assert magnitudes[6] > 3.9
