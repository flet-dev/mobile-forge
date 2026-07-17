def test_resolves_contrib_pin():
    """The distribution must be installed under the name
    `opencv-contrib-python` so pip pins like 'opencv-contrib-python>=4.9'
    resolve to this wheel. importlib.metadata.version() raises
    PackageNotFoundError if nothing is installed under that name, so a clean
    lookup is the proof — the version value is irrelevant to the claim."""
    from importlib.metadata import version

    assert version("opencv-contrib-python")


def test_image_ops_roundtrip():
    """Real image pipeline through the native core (imgcodecs + imgproc):
    encode a synthetic image to PNG, decode it back, convert to gray, and
    run Canny edge detection — exercises the main-module C++ core."""
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
    """The dnn module (ONNX inference) rides along here too — it's the
    latent inference runtime story, shared with the main opencv wheels."""
    import cv2

    assert hasattr(cv2, "dnn")
    assert callable(cv2.dnn.blobFromImage)


def test_contrib_module_works():
    """The reason this wheel exists over plain opencv-python: a contrib-only
    module must actually load and run. img_hash is a stable, dependency-free
    contrib module — a perceptual hash of identical images matches, and a
    different image hashes differently."""
    import cv2
    import numpy as np

    a = np.zeros((32, 32, 3), dtype=np.uint8)
    b = a.copy()
    b[:16] = 255  # visibly different top half

    ha = cv2.img_hash.averageHash(a)
    ha_again = cv2.img_hash.averageHash(a.copy())
    hb = cv2.img_hash.averageHash(b)

    assert np.array_equal(ha, ha_again)
    assert not np.array_equal(ha, hb)
