import time

import cv2
import numpy as np

WIDTH, HEIGHT = 420, 560
LINES = (
    "OpenCV contrib modules",
    "",
    "A phone camera never sees a flat page. A",
    "lamp on one side, a hand on the other, and",
    "the paper arrives with a gradient baked",
    "into it. One global cut point cannot",
    "survive that, so the shadowed corner turns",
    "solid black and takes the text with it.",
    "",
    "cv2.ximgproc.niBlackThreshold picks a cut",
    "point per pixel from the local mean and",
    "standard deviation. Sauvola adds the term",
    "that pushes the threshold down where the",
    "neighbourhood is flat, so paper stays",
    "paper and only real strokes survive.",
    "",
    "It is not in the base opencv-python wheel.",
)

# Names only; inventory() looks every one of them up in the wheel that actually
# loaded rather than trusting this list. Each entry is a module and one function
# inside it, and neither exists in the base opencv-python build.
CONTRIB = (
    ("ximgproc", "niBlackThreshold", "local thresholding, thinning, edge filters"),
    ("xphoto", "createSimpleWB", "white balance, denoise, inpaint"),
    ("legacy", "TrackerMOSSE_create", "the pre-5.0 tracker API"),
    ("bgsegm", "createBackgroundSubtractorMOG", "extra background subtractors"),
    ("img_hash", "averageHash", "perceptual hashes for near-duplicate detection"),
    ("ml", "SVM_create", "SVM, random trees, k-NN — not in the base OpenCV 5 build"),
    ("face", "LBPHFaceRecognizer_create", "face recognisers and landmark fitters"),
    ("text", "OCRTesseract_create", "OCR front end; the engine is not in the wheel"),
    ("optflow", "createOptFlow_DeepFlow", "DeepFlow, PCAFlow, RLOF"),
    ("quality", "QualitySSIM_create", "SSIM, PSNR, GMSD, BRISQUE"),
    ("xfeatures2d", "BEBLID_create", "BEBLID, TEBLID, FREAK, DAISY, LATCH"),
    ("wechat_qrcode", "WeChatQRCode", "QR decoder; its two model paths are optional"),
    ("dnn_superres", "DnnSuperResImpl_create", "upscaling, with a model file"),
    ("plot", "Plot2d_create", "Plot2d"),
)

METHODS = ("Otsu", "Adaptive", "Sauvola")
VERSION = f"OpenCV {cv2.__version__} — {WIDTH}x{HEIGHT} page"


def inventory():
    """Report which contrib functions the installed cv2 binary actually carries.

    Probing the function rather than stopping at hasattr(cv2, "ximgproc") makes
    the same row honest in both places the app runs. On device cv2 is the native
    extension, so a missing module is simply absent; under `flet run` cv2 is an
    ordinary package, and if both OpenCV distributions reach the dependency list
    the loser's cv2/ximgproc/ stays on disk holding nothing but a type stub. It
    then imports as an empty namespace module and the module name ticks anyway.
    """
    return [
        (f"{name}.{symbol}", note, hasattr(getattr(cv2, name, None), symbol))
        for name, symbol, note in CONTRIB
    ]


def photograph(shadow):
    """Render a page of text, then light it badly, and return it with its truth mask.

    The mask is captured before the lighting and noise go on, so it is exactly
    which pixels are ink. That is what makes the score in binarise() meaningful:
    the app is not guessing at the right answer, it drew it.

    `shadow` is how dark the bottom-right corner ends up, 0.0 for none and 1.0
    for almost black.
    """
    page = np.full((HEIGHT, WIDTH), 236, np.uint8)
    for index, text in enumerate(LINES):
        cv2.putText(
            page,
            text,
            (24, 46 + index * 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            100,
            1,
            cv2.LINE_AA,
        )
    ink = page < 170

    ramp_y = np.linspace(0, 1, HEIGHT, dtype=np.float32)[:, None]
    ramp_x = np.linspace(0, 1, WIDTH, dtype=np.float32)[None, :]
    lighting = 1.0 - shadow * np.clip(0.55 * ramp_y + 0.55 * ramp_x, 0, 1) ** 1.6

    rng = np.random.default_rng(7)
    lit = page.astype(np.float32) * lighting + rng.normal(0, 8, page.shape)
    return np.clip(lit, 0, 255).astype(np.uint8), ink


def binarise(photo, ink, method):
    """Turn the photographed page into black-on-white three ways and score each.

    Otsu and adaptiveThreshold are in every OpenCV build. Sauvola is
    cv2.ximgproc.niBlackThreshold, which only exists in the contrib wheel, and
    is the one call in this app that the base opencv-python cannot make.

    Returns the PNG the UI shows plus three numbers: the share of real ink
    recovered, the share of blank paper wrongly called ink, and the
    milliseconds spent. Otsu keeps the text and ruins the paper; that is the
    whole argument for a per-pixel threshold.
    """
    started = time.perf_counter()
    if method == "Otsu":
        _, mask = cv2.threshold(photo, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif method == "Adaptive":
        mask = cv2.adaptiveThreshold(
            photo, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8
        )
    else:
        mask = cv2.ximgproc.niBlackThreshold(
            photo,
            255,
            cv2.THRESH_BINARY,
            31,
            0.15,
            binarizationMethod=cv2.ximgproc.BINARIZATION_SAUVOLA,
            r=64,
        )
    elapsed = (time.perf_counter() - started) * 1000

    marked = mask == 0
    recall = 100 * float(np.count_nonzero(marked & ink)) / float(np.count_nonzero(ink))
    blank = ~ink
    smudge = (
        100 * float(np.count_nonzero(marked & blank)) / float(np.count_nonzero(blank))
    )
    return _png(mask), recall, smudge, elapsed


def _png(image):
    """Encode the mask as PNG bytes, which ft.Image.src takes directly.

    PNG rather than the JPEG a photo would want: the result is two-valued, so
    each scanline is long runs of one byte and DEFLATE has almost nothing left to
    store. Measured on the three masks here, PNG comes out four to six times
    smaller than JPEG at quality 82, and this buffer crosses the Flet transport
    on every run.
    """
    _, buffer = cv2.imencode(".png", image)
    return buffer.tobytes()
