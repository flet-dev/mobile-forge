def test_basic():
    """Smoke-test core ndarray creation and elementwise arithmetic."""
    from numpy import array

    assert (array([1, 2]) + array([3, 5])).tolist() == [4, 7]


def test_matmul():
    """Exercise the dense matmul (GEMM) path and verify its result.

    Asserts correctness, not speed. mobile-forge builds numpy WITHOUT OpenBLAS
    (its config reports blas name="none"), so a dense matmul runs on the
    unaccelerated fallback whose wall-clock time swings widely on loaded /
    emulated devices and is not a reliable signal. The matmul `a @ I` must
    equal `a`; the elapsed time is printed for visibility only.
    """
    from time import time

    import numpy as np

    SIZE = 500
    a = np.random.rand(SIZE, SIZE)

    start_time = time()
    product = np.dot(a, np.eye(SIZE))  # full GEMM; a @ I == a
    duration = time() - start_time
    print(f"{duration:.3f}")

    assert product.shape == (SIZE, SIZE)
    assert np.allclose(product, a)


def test_fft():
    """Forces _pocketfft_umath.so to load — the canary for the libc++_shared
    Android dep."""
    import numpy as np

    # 8-point FFT of a pure cosine at frequency k=2. The real-input FFT of
    # cos(2π · k · n / N) has two equal-magnitude peaks at bins k and N-k.
    x = np.cos(2 * np.pi * 2 * np.arange(8) / 8)
    spectrum = np.fft.fft(x)
    magnitudes = np.abs(spectrum)

    # Peaks at bins 2 and 6 with magnitude N/2 = 4 for unit-amplitude cosine.
    assert magnitudes[2] > 3.9, f"bin 2 magnitude = {magnitudes[2]}"
    assert magnitudes[6] > 3.9, f"bin 6 magnitude = {magnitudes[6]}"
    # All other bins should be ~0 (within fp noise).
    other = max(float(magnitudes[i]) for i in (0, 1, 3, 4, 5, 7))
    assert other < 1e-6, f"unexpected non-zero bin: {other}"

    # Round-trip: inverse FFT recovers the original signal.
    recovered = np.fft.ifft(spectrum).real
    assert np.allclose(recovered, x)
