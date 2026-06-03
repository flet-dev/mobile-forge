def test_import_cv2():
    """`import cv2` triggers OpenCV's native .so dlopen and transitively
    `import numpy`. The published `numpy-2.2.2-4` wheel on pypi.flet.dev
    has NO `Requires-Dist: flet-libcpp-shared` in METADATA, and the
    published `opencv-python` wheel also doesn't declare it, so a
    cv2-only Flet app doesn't bundle libc++_shared.so. On x86_64 numpy
    fails at multiarray; on arm64 `import cv2` works (arm64 numpy
    multiarray doesn't need libcpp) but `cv2.dft(...)` or any code path
    that pulls `np.fft.*` then fires the gap. The recipe's defensive
    libcpp host dep + Requires-Dist injection closes both."""
    import cv2

    assert cv2.__version__
    assert hasattr(cv2, "imencode")


def test_numpy_fft():
    """libcpp_shared canary that fires on every Android arch via
    `_pocketfft_umath.so` (DT_NEEDED=[libc++_shared.so] on both arm64
    AND x86_64). cv2 doesn't naturally call numpy.fft, but this
    surfaces the libcpp gap the recipe's defensive
    `flet-libcpp-shared` host dep closes."""
    import numpy as np

    x = np.cos(2 * np.pi * 2 * np.arange(8) / 8)
    spectrum = np.fft.fft(x)
    magnitudes = np.abs(spectrum)
    assert magnitudes[2] > 3.9
    assert magnitudes[6] > 3.9


def test_image_encode_decode():
    """opencv-python wraps OpenCV's C++ core. Encode + decode a small
    NumPy image round-trip — covers the JPEG codec path."""
    import cv2
    import numpy as np

    # Construct a 16x16 image with a diagonal gradient.
    img = np.zeros((16, 16, 3), dtype=np.uint8)
    for y in range(16):
        for x in range(16):
            img[y, x] = (y * 16, x * 16, 128)

    ok, buf = cv2.imencode(".png", img)
    assert ok
    assert buf.nbytes > 0

    decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == img.shape


def test_resize():
    """Resize hits a different C++ code path (cv::resize)."""
    import cv2
    import numpy as np

    src = np.zeros((20, 30, 3), dtype=np.uint8)
    out = cv2.resize(src, (60, 40))
    assert out.shape == (40, 60, 3)
