"""The sherpa-onnx side of the app: fetch a model once, then transcribe offline."""

import array
import os
import shutil
import ssl
import tarfile
import tempfile
import time
import urllib.request
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import certifi
import sherpa_onnx

MODEL = "sherpa-onnx-moonshine-tiny-en-quantized-2026-02-27"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{MODEL}.tar.bz2"
)


@dataclass
class Transcript:
    text: str
    audio_s: float
    decode_s: float


def model_dir() -> Path:
    """Where the model lives: Flet's persistent app storage on a device."""
    root = os.getenv("FLET_APP_STORAGE_DATA") or str(Path.home() / ".sherpa-demo")
    return Path(root) / MODEL


def ensure_model(report: Callable[[str], None]) -> Path:
    """Download and unpack the 29 MB model on first run; reuse it after."""
    target = model_dir()
    if (target / "tokens.txt").exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    context = ssl.create_default_context(cafile=certifi.where())
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        archive = Path(tmp) / "model.tar.bz2"
        with urllib.request.urlopen(MODEL_URL, context=context) as response:
            total = int(response.headers.get("Content-Length", 0))
            with open(archive, "wb") as f:
                done = 0
                while chunk := response.read(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    report(
                        f"Downloading model… {done / 1e6:.0f} / {total / 1e6:.0f} MB"
                    )
        report("Unpacking model…")
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        # Move into place only once complete, so an interrupted run retries.
        shutil.rmtree(target, ignore_errors=True)
        (Path(tmp) / MODEL).rename(target)
    return target


def load_recognizer(model: Path) -> sherpa_onnx.OfflineRecognizer:
    """Build the offline recognizer; this loads both ONNX models."""
    return sherpa_onnx.OfflineRecognizer.from_moonshine_v2(
        encoder=str(model / "encoder_model.ort"),
        decoder=str(model / "decoder_model_merged.ort"),
        tokens=str(model / "tokens.txt"),
        num_threads=2,
    )


def read_wav(path: Path) -> tuple[int, list[float]]:
    """Sample rate and mono float samples of a 16-bit PCM WAV file."""
    with wave.open(str(path)) as f:
        rate = f.getframerate()
        pcm = array.array("h", f.readframes(f.getnframes()))
    return rate, [s / 32768 for s in pcm]


def transcribe(recognizer: sherpa_onnx.OfflineRecognizer, path: Path) -> Transcript:
    """Decode one WAV file; sherpa-onnx resamples to the model's rate itself."""
    rate, samples = read_wav(path)
    stream = recognizer.create_stream()
    stream.accept_waveform(rate, samples)
    start = time.perf_counter()
    recognizer.decode_stream(stream)
    return Transcript(
        text=stream.result.text.strip(),
        audio_s=len(samples) / rate,
        decode_s=time.perf_counter() - start,
    )
