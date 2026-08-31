import numpy as np
import pytest

SR_IN = 48000
SR_OUT = 16000


def _tone(sample_rate, seconds=0.5, freq=440.0):
    """Deterministic mono float32 sine — no RNG, no assets, no network."""
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    return np.sin(2.0 * np.pi * freq * t).astype(np.float32)


def test_resample_roundtrip():
    """48k->16k->48k reproduces the waveform -> the nanobind extension and the vendored
    libsoxr actually resample, not just load."""
    import soxr

    x = _tone(SR_IN)
    down = soxr.resample(x, SR_IN, SR_OUT, quality="VHQ")
    assert down.shape == (len(x) * SR_OUT // SR_IN,)
    assert down.dtype == np.float32

    up = soxr.resample(down, SR_OUT, SR_IN, quality="VHQ")
    assert up.shape == x.shape
    edge = SR_IN // 20  # drop the filter transients at both ends
    assert np.max(np.abs(up[edge:-edge] - x[edge:-edge])) < 1e-2


def test_multichannel_dtypes():
    """Every supported dtype survives a 2-D (frames, channels) resample -> covers all
    four csoxr_divide_proc_* template instantiations."""
    import soxr

    mono = _tone(SR_IN)
    for dtype in (np.float32, np.float64, np.int16, np.int32):
        x = np.stack([mono, 0.5 * mono], axis=1)
        if np.issubdtype(dtype, np.integer):
            x = (x * 20000).astype(dtype)
        else:
            x = x.astype(dtype)

        y = soxr.resample(x, SR_IN, SR_OUT)
        assert y.dtype == x.dtype
        assert y.shape == (len(mono) * SR_OUT // SR_IN, 2)


def test_stream_matches_oneshot():
    """Chunked ResampleStream output equals the one-shot resample -> exercises the
    stateful CSoxr object and its final flush."""
    import soxr

    x = _tone(SR_IN)
    stream = soxr.ResampleStream(SR_IN, SR_OUT, 1, dtype="float32", quality="HQ")
    chunk = 1024
    streamed = np.concatenate(
        [
            stream.resample_chunk(x[i : i + chunk], last=i + chunk >= len(x))
            for i in range(0, len(x), chunk)
        ]
    )

    oneshot = soxr.resample(x, SR_IN, SR_OUT, quality="HQ")
    assert streamed.shape == oneshot.shape
    assert np.max(np.abs(streamed - oneshot)) < 1e-6


def test_simd_engine_compiled_in():
    """The wheel carries libsoxr's SIMD resampling engine, not just the scalar fallback.

    libsoxr only compiles cr32s when CMake knows the target CPU, and iOS leaves
    CMAKE_SYSTEM_PROCESSOR unset unless the recipe names it -- the build stays green
    either way, so only the engine name catches the loss.
    """
    import platform

    import soxr

    if platform.machine().lower().startswith("armv"):
        # 32-bit ARM asks HWCAP for NEON at runtime, so a "cr32" here would mean
        # the device lacks NEON, not that the recipe dropped the engine.
        pytest.skip("32-bit ARM picks the engine at runtime, not at build time")

    # HQ keeps precision <= 20, which is the branch that reaches cr32s at all.
    stream = soxr.ResampleStream(SR_IN, SR_OUT, 1, dtype="float32", quality="HQ")
    assert stream._csoxr.engine() == "cr32s"
