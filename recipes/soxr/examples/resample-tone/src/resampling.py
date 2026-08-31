import time

import numpy as np

import soxr

SOURCE_RATE = 48000
SECONDS = 10
TARGET_RATES = [8000, 16000, 22050, 44100]
QUALITIES = ["QQ", "LQ", "MQ", "HQ", "VHQ"]


def tone(sample_rate=SOURCE_RATE, seconds=SECONDS, freq=440.0):
    """Build a float32 sine of the given length, standing in for recorded audio.

    Generated rather than bundled so the example ships no asset, and float32 because
    that is what a capture API hands you and what soxr resamples fastest.
    """
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    return np.sin(2.0 * np.pi * freq * t).astype(np.float32)


def convert(source, target_rate, quality="HQ"):
    """Resample `source` to `target_rate`, returning (frames_out, seconds_elapsed).

    Timed here rather than in the UI so the measurement covers only soxr's work.
    """
    started = time.perf_counter()
    out = soxr.resample(source, SOURCE_RATE, target_rate, quality=quality)
    return len(out), time.perf_counter() - started


def engine_for(quality):
    """Name the libsoxr core a quality setting selects on this device.

    'cr32s' is the SIMD core; 'cr32' and 'cr64' are scalar. VHQ reads 'cr64' on ARM
    because the double-precision core's SIMD variant is AVX-only. Reaching through the
    private `_csoxr` is the only way to see the choice, and seeing it is the point.
    """
    stream = soxr.ResampleStream(
        SOURCE_RATE, 16000, 1, dtype="float32", quality=quality
    )
    return stream._csoxr.engine()
