def test_import_cv2_headless():
    """Same cv2 module as opencv-python, built from the headless sdist
    (cv2/version.py bakes headless=True). This recipe exists so packages
    that pin `opencv-python-headless` (albumentations/albucore, various
    OCR stacks) resolve on pypi.flet.dev — on mobile there is no GUI
    either way, so the flavors are functionally identical."""
    import cv2

    assert cv2.__version__.startswith("4.12")
    assert hasattr(cv2, "imencode")


def test_image_ops_roundtrip():
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


def test_resolves_headless_pin():
    """The reason this recipe exists: metadata must identify as
    opencv-python-headless so pip pins like 'opencv-python-headless>=4.9'
    (albumentations) resolve to this wheel."""
    from importlib.metadata import version

    assert version("opencv-python-headless").startswith("4.12")
