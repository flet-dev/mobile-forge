import io
import sys

import numpy as np
import pytest
import soundfile as sf

SR = 16000


def _tone(seconds=0.25, freq=440.0, sample_rate=SR):
    """Deterministic mono float64 sine — no RNG, no assets, no network."""
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    return np.sin(2.0 * np.pi * freq * t)


def test_libsndfile_loaded():
    """The cffi loader found the flet-libsndfile .so and bound the C API — this is
    the single claim the mobile patch exists to make true."""
    assert sf.__libsndfile_version__
    assert sf.SoundFile is not None


def test_wav_roundtrip(tmp_path):
    """A float64 signal written as 32-bit float WAV reads back bit-identical, with
    the samplerate and channel count preserved."""
    path = str(tmp_path / "tone.wav")
    x = _tone()
    sf.write(path, x, SR, subtype="DOUBLE")

    y, sr = sf.read(path)
    assert sr == SR
    assert y.shape == x.shape
    np.testing.assert_array_equal(y, x)


def test_stereo_and_int_subtypes(tmp_path):
    """Two-channel PCM_16 and PCM_24 round-trip within their quantisation step —
    covers the integer conversion paths, not just the float passthrough."""
    x = np.stack([_tone(), 0.5 * _tone(freq=880.0)], axis=1)
    for subtype, step in (("PCM_16", 2**-15), ("PCM_24", 2**-23)):
        path = str(tmp_path / f"{subtype}.wav")
        sf.write(path, x, SR, subtype=subtype)
        y, sr = sf.read(path)
        assert sr == SR
        assert y.shape == x.shape
        assert np.max(np.abs(y - x)) <= step


@pytest.mark.parametrize(
    "fmt, ext, subtype, lossy",
    [
        ("WAV", "wav", "PCM_16", False),
        ("AIFF", "aiff", "PCM_16", False),
        ("AU", "au", "PCM_16", False),
        ("CAF", "caf", "PCM_16", False),
        ("W64", "w64", "PCM_16", False),
        ("RF64", "rf64", "PCM_16", False),
        ("FLAC", "flac", "PCM_16", False),
        ("OGG", "ogg", "VORBIS", True),
        ("OGG", "opus", "OPUS", True),
        ("MP3", "mp3", "MPEG_LAYER_III", True),
    ],
)
def test_container_roundtrip(tmp_path, fmt, ext, subtype, lossy):
    """Every container this wheel's libsndfile is built for encodes and decodes on
    device — including the ones that only work because flet-libflac, flet-libogg,
    flet-libvorbis, flet-libopus, flet-libmpg123 and flet-libmp3lame are linked in.
    Opus resamples to 48 kHz internally, so its frame count is not compared."""
    path = str(tmp_path / f"tone.{ext}")
    x = _tone(seconds=0.5)
    sr = 48000 if subtype == "OPUS" else SR
    sf.write(path, x, sr, format=fmt, subtype=subtype)

    y, out_sr = sf.read(path)
    assert out_sr == sr
    assert y.ndim == 1
    if lossy:
        # Codec delay and framing make a sample-wise comparison meaningless;
        # assert the decode produced a real signal of roughly the right length.
        assert y.size >= x.size // 2
        assert np.sqrt(np.mean(y**2)) > 0.1
    else:
        assert y.shape == x.shape
        assert np.max(np.abs(y - x)) <= 2**-15


@pytest.mark.skipif(sys.platform == "ios", reason="no W+X memory for ffi.callback()")
def test_read_from_file_object():
    """sf.read() works on an in-memory binary stream via libsndfile's virtual I/O —
    the path an app takes for audio fetched over the network, where there may be
    no real file to open. Android only; see the iOS counterpart below."""
    buf = io.BytesIO()
    x = _tone()
    sf.write(buf, x, SR, format="WAV", subtype="DOUBLE")

    buf.seek(0)
    y, sr = sf.read(buf)
    assert sr == SR
    np.testing.assert_array_equal(y, x)


@pytest.mark.skipif(sys.platform != "ios", reason="iOS-only limitation")
def test_file_object_is_unavailable_on_ios():
    """Passing a file object on iOS raises MemoryError, and this is permanent: virtual
    I/O hands libsndfile a `ffi.callback()`, cffi writes that trampoline at runtime, and
    iOS refuses write+execute pages to an app without the JIT entitlement. Asserted
    rather than skipped so the README's "write it to a file first" guidance is checked,
    and so a future cffi or OS change that lifts it does not go unnoticed."""
    buf = io.BytesIO()
    with pytest.raises(MemoryError, match="write.execute"):
        sf.write(buf, _tone(), SR, format="WAV", subtype="DOUBLE")


def test_path_roundtrip_is_the_ios_workaround(tmp_path):
    """The replacement for the file-object path: spill the bytes to a real file and read
    it back. Works on every platform, so an app needs no per-platform branch."""
    raw = io.BytesIO()
    x = _tone()
    try:
        sf.write(raw, x, SR, format="WAV", subtype="DOUBLE")
        encoded = raw.getvalue()
    except MemoryError:  # iOS: produce the same bytes without virtual I/O
        staged = str(tmp_path / "staged.wav")
        sf.write(staged, x, SR, subtype="DOUBLE")
        encoded = open(staged, "rb").read()

    path = tmp_path / "from_bytes.wav"
    path.write_bytes(encoded)
    y, sr = sf.read(str(path))
    assert sr == SR
    np.testing.assert_array_equal(y, x)


def test_blockwise_read(tmp_path):
    """SoundFile seeking and block reads reassemble the whole signal — the memory-
    bounded path for files too large to hold in RAM on a phone."""
    path = str(tmp_path / "tone.wav")
    x = _tone(seconds=1.0)
    sf.write(path, x, SR, subtype="DOUBLE")

    with sf.SoundFile(path) as f:
        assert len(f) == x.size
        assert f.samplerate == SR
        assert f.channels == 1

        blocks = [f.read(1024) for _ in range(int(np.ceil(x.size / 1024)))]
        np.testing.assert_array_equal(np.concatenate(blocks), x)

        f.seek(SR // 2)
        np.testing.assert_array_equal(f.read(100), x[SR // 2 : SR // 2 + 100])


def test_available_formats_advertises_the_linked_codecs():
    """libsndfile's own format registry lists the codec containers, proving they
    were compiled in rather than merely present at link time."""
    formats = sf.available_formats()
    for fmt in ("WAV", "AIFF", "AU", "CAF", "W64", "RF64", "FLAC", "OGG", "MP3"):
        assert fmt in formats, f"{fmt} missing from {sorted(formats)}"

    assert set(sf.available_subtypes("FLAC")) >= {"PCM_16", "PCM_24"}
    assert set(sf.available_subtypes("OGG")) == {"VORBIS", "OPUS"}
    assert "MPEG_LAYER_III" in sf.available_subtypes("MP3")
    # ALAC ships inside libsndfile itself, no external library involved.
    assert "ALAC_16" in sf.available_subtypes("CAF")
