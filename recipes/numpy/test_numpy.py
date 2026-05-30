def test_basic():
    from numpy import array

    assert (array([1, 2]) + array([3, 5])).tolist() == [4, 7]


def test_performance():
    from time import time

    import numpy as np

    start_time = time()
    SIZE = 500
    a = np.random.rand(SIZE, SIZE)
    b = np.random.rand(SIZE, SIZE)
    np.dot(a, b)

    # With OpenBLAS, the test devices take at most 0.4 seconds. Without OpenBLAS, they take
    # at least 1.0 seconds.
    duration = time() - start_time
    print(f"{duration:.3f}")
    assert duration < 0.7


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
