def test_resolves_headless_pin():
    """The reason this recipe exists: the installed distribution must be
    named `opencv-python-headless` so pip pins like
    'opencv-python-headless>=4.9' (albumentations, OCR stacks) resolve to
    this wheel. importlib.metadata.version() raises PackageNotFoundError if
    nothing is installed under that name, so a clean lookup is the proof —
    the exact version value is irrelevant to the claim."""
    from importlib.metadata import version

    assert version("opencv-python-headless")


def test_image_ops_roundtrip():
    """Real image pipeline through the native core (imgcodecs + imgproc):
    encode a synthetic image to PNG, decode it back, convert to gray, and
    run Canny edge detection — exercises the C++ core."""
    import cv2
    import numpy as np

    img = np.zeros((16, 16, 3), dtype=np.uint8)
    for y in range(16):
        for x in range(16):
            img[y, x] = (y * 16, x * 16, 128)

    ok, buf = cv2.imencode(".png", img)
    assert ok and buf.nbytes > 0
    decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    assert decoded is not None and decoded.shape == img.shape

    gray = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    assert edges.shape == (16, 16)


def test_dnn_module_present():
    """The dnn module (ONNX inference) must ride along in the headless
    flavor too — it's the latent inference runtime story."""
    import cv2

    assert hasattr(cv2, "dnn")
    assert callable(cv2.dnn.blobFromImage)
