import time

import cv2
import numpy as np

SIZE = 300
STAGES = ("source", "blurred", "edges")
VERSION = f"OpenCV {cv2.__version__}"


def gui_backend():
    """Report the GUI backend OpenCV was compiled against, or "none".

    `getBuildInformation()` is a string baked into the native library at build
    time, so this is what the wheel on *this* device was configured with rather
    than a guess from the platform. A desktop `flet run` on macOS answers COCOA
    and `cv2.imshow` really does open a window there. The Android wheel answers
    NONE and the iOS wheel leaves the field blank, reported here as "none" —
    which is why every result on screen below travels as encoded bytes into an
    ft.Image instead.
    """
    for line in cv2.getBuildInformation().splitlines():
        label, _, value = line.partition(":")
        if label.strip() == "GUI":
            return value.strip() or "none"
    return "unknown"


def scene():
    """Draw a few overlapping discs and bars on a dark field.

    Synthesised rather than bundled as an asset so the app has no file to find
    at startup and every run gives the edge detector something different to
    chew on.
    """
    rng = np.random.default_rng()
    canvas = np.full((SIZE, SIZE, 3), 18, np.uint8)
    for _ in range(4):
        centre = tuple(int(v) for v in rng.integers(60, SIZE - 60, 2))
        colour = tuple(int(c) for c in rng.integers(90, 245, 3))
        cv2.circle(canvas, centre, int(rng.integers(34, 62)), colour, -1)
    for _ in range(2):
        x = int(rng.integers(20, SIZE - 60))
        colour = tuple(int(c) for c in rng.integers(90, 245, 3))
        cv2.rectangle(canvas, (x, 20), (x + 34, SIZE - 20), colour, -1)
    return canvas


def process(canvas):
    """Blur the scene, run Canny over it, and hand back every stage as JPEG.

    Three calls into compiled OpenCV code — a Gaussian blur, a colour
    conversion and the Canny edge detector — none of which care which of the
    three cv2 distributions supplied them. Returns the labelled stages, the
    share of pixels Canny marked as an edge, and the milliseconds the whole
    pipeline took.

    The blur is the conventional step before Canny rather than a repair for
    this scene, which is drawn clean and has no noise to remove: on desktop it
    moves the edge share by about a tenth of a percentage point. Where it does
    show is the strip — the middle tile is visibly softer, and its JPEG averages
    about 15% smaller than the source's.
    """
    started = time.perf_counter()
    blurred = cv2.GaussianBlur(canvas, (5, 5), 0)
    gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 180)
    elapsed = (time.perf_counter() - started) * 1000

    frames = (canvas, blurred, cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR))
    stages = [(name, jpeg(frame)) for name, frame in zip(STAGES, frames)]
    return stages, float(np.count_nonzero(edges)) / edges.size, elapsed


def jpeg(image):
    """Encode a BGR array as JPEG bytes, which ft.Image.src accepts directly.

    imencode returns a numpy buffer; ft.Image wants bytes, so tobytes() is the
    whole bridge between OpenCV and the Flet control.
    """
    _, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buffer.tobytes()
