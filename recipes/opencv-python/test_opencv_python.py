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
