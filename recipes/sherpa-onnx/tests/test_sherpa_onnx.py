import importlib.util
import math
import os
import ssl
import tempfile
import urllib.request

import pytest

SILERO_VAD_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
)


def test_native_module_loads():
    """Importing sherpa_onnx loads the compiled extension and, on Android, the
    bundled onnxruntime it links against."""
    import sherpa_onnx  # noqa: F401

    spec = importlib.util.find_spec("sherpa_onnx.lib._sherpa_onnx")
    assert spec is not None and spec.origin is not None
    print(f"SHERPA_NATIVE origin={spec.origin}", flush=True)


def test_high_level_api_present():
    """The Python wrappers for each speech task are importable."""
    import sherpa_onnx

    for name in (
        "OnlineRecognizer",
        "OfflineRecognizer",
        "OfflineTts",
        "VoiceActivityDetector",
        "KeywordSpotter",
    ):
        assert hasattr(sherpa_onnx, name), name


def test_native_config_objects():
    """Config objects are constructed on the C++ side and read back."""
    from sherpa_onnx.lib import _sherpa_onnx as binding

    feat = binding.FeatureExtractorConfig(sampling_rate=16000, feature_dim=80)
    assert feat.sampling_rate == 16000
    assert feat.feature_dim == 80
    assert binding.VadModelConfig().sample_rate > 0


def test_circular_buffer_roundtrip():
    """Samples pushed into the C++ CircularBuffer come back unchanged."""
    import sherpa_onnx

    buf = sherpa_onnx.CircularBuffer(1024)
    buf.push([0.1, 0.2, 0.3, 0.4])
    assert buf.size == 4
    got = buf.get(0, 4)
    assert [round(x, 6) for x in got] == [0.1, 0.2, 0.3, 0.4]


def _silero_vad_model() -> str:
    """Download silero_vad.onnx (0.6 MB) once per run; skip when offline."""
    path = os.path.join(tempfile.gettempdir(), "silero_vad.onnx")
    if not os.path.exists(path):
        try:
            import certifi

            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(SILERO_VAD_URL, context=ctx, timeout=60) as r:
                data = r.read()
        except OSError as exc:
            pytest.skip(f"cannot download silero_vad.onnx: {exc}")
        with open(path, "wb") as f:
            f.write(data)
    return path


def test_vad_inference():
    """Silero VAD runs through onnxruntime: silence yields no speech segment,
    and a loud signal is processed and flushed without error."""
    import sherpa_onnx

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = _silero_vad_model()
    config.silero_vad.threshold = 0.5
    config.sample_rate = 16000
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=10)

    window = config.silero_vad.window_size
    silence = [0.0] * 16000
    for i in range(0, len(silence), window):
        vad.accept_waveform(silence[i : i + window])
    assert vad.empty()

    tone = [0.8 * math.sin(2 * math.pi * 300 * t / 16000) for t in range(16000)]
    for i in range(0, len(tone), window):
        vad.accept_waveform(tone[i : i + window])
    vad.flush()
    while not vad.empty():
        assert len(vad.front.samples) > 0
        vad.pop()
