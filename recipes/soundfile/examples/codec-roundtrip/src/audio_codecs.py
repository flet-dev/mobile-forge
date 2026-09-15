"""Encode a generated signal to every container this wheel supports, decode it back,
and report what each one cost. No soundfile object escapes: callers get plain values."""

import os
import tempfile
import time

import numpy as np
import soundfile as sf

RATE = 16000
SECONDS = 2.0

# (label, libsndfile format, subtype, samplerate). Opus only accepts 48 kHz, so it
# gets its own rate rather than being silently resampled by libsndfile.
CODECS = [
    ("WAV / PCM_16", "WAV", "PCM_16", RATE),
    ("WAV / FLOAT", "WAV", "FLOAT", RATE),
    ("FLAC", "FLAC", "PCM_16", RATE),
    ("CAF / ALAC", "CAF", "ALAC_16", RATE),
    ("OGG / Vorbis", "OGG", "VORBIS", RATE),
    ("OGG / Opus", "OGG", "OPUS", 48000),
    ("MP3", "MP3", "MPEG_LAYER_III", RATE),
]


def signal(rate=RATE, seconds=SECONDS):
    """A deterministic three-partial chord — compresses like real audio, unlike a
    pure sine, so the codec sizes below are not flattering."""
    t = np.arange(int(rate * seconds)) / rate
    wave = sum(a * np.sin(2 * np.pi * f * t) for f, a in ((220, 0.5), (330, 0.3), (550, 0.2)))
    envelope = np.minimum(1.0, 8 * np.minimum(t, seconds - t))
    return (wave * envelope).astype(np.float64)


def roundtrip(label, fmt, subtype, rate):
    """Encode to a container on disk and decode it back.

    Returns the label, encoded size in bytes, encode+decode time in seconds, and the
    RMS difference from the source — quantisation-limited for the integer formats,
    audible-codec-sized for the lossy ones. Returns an `error` string instead if the
    format is not compiled in.

    Files, not io.BytesIO: a file object would route through libsndfile's virtual I/O,
    which needs a cffi callback, which needs write+execute memory that iOS refuses.
    """
    source = signal(rate)
    # FLET_APP_STORAGE_TEMP on device; tempfile's default elsewhere.
    directory = os.getenv("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()
    path = os.path.join(directory, f"roundtrip-{subtype.lower()}.{fmt.lower()}")
    started = time.monotonic()
    try:
        sf.write(path, source, rate, format=fmt, subtype=subtype)
        size = os.path.getsize(path)
        decoded, out_rate = sf.read(path)
    except Exception as exc:  # unsupported subtype, missing codec, ...
        return {"label": label, "error": str(exc)}
    finally:
        if os.path.exists(path):
            os.remove(path)
    elapsed = time.monotonic() - started

    # Lossy codecs add leading silence and pad the tail, so compare the overlap.
    n = min(len(decoded), len(source))
    rms = float(np.sqrt(np.mean((decoded[:n] - source[:n]) ** 2)))

    return {
        "label": label,
        "bytes": size,
        "ratio": (source.nbytes / size),
        "seconds": elapsed,
        "rms_error": rms,
        "frames": len(decoded),
        "rate": out_rate,
        "waveform": decoded,
    }


def run_all():
    """Round-trip every codec in CODECS, in order."""
    return [roundtrip(*entry) for entry in CODECS]


def envelope(samples, buckets=120):
    """Peak amplitude per bucket, normalised to 0..1 — enough to draw a waveform."""
    if len(samples) == 0:
        return [0.0] * buckets
    edges = np.linspace(0, len(samples), buckets + 1).astype(int)
    peaks = np.array([np.max(np.abs(samples[a:b]), initial=0.0) for a, b in zip(edges, edges[1:])])
    top = peaks.max()
    return (peaks / top if top else peaks).tolist()
