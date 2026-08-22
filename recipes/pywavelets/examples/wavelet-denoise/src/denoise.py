"""The pywavelets half of the app: transforms, thresholding and a PNG writer, no Flet."""

import struct
import zlib

import numpy as np
import pywt

N = 4096
LEVEL = 6
IMAGE_LEVEL = 3

# periodization is the only mode whose coefficient count equals the signal length, so a band's
# energy is a share of the signal's energy rather than of a padded total.
MODE = "periodization"

SIGNALS = ["Doppler", "Bumps", "HeaviSine", "Blocks"]
WAVELETS = ["haar", "db4", "sym8", "dmey"]

_image = None


def source_image():
    """The 512x512 `camera` scene that ships inside the wheel, as float in [0, 1].

    Read on first use rather than at import. pywt.data.camera() goes through
    importlib.resources, which on Android has to materialise the .npz out of the zipped
    site-packages, and that is not work for the startup path.
    """
    global _image
    if _image is None:
        _image = pywt.data.camera().astype(np.float64) / 255.0
    return _image


def encode_png(image):
    """Encode a [0, 1] float image as 8-bit greyscale PNG bytes for ft.Image(src=...).

    Hand-written because numpy is the only thing this app depends on besides Flet — there
    example's dependencies are Flet, numpy and pywavelets, and
    adding an image library just to save a PNG is not worth it.
    """
    samples = (np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    height, width = samples.shape
    raw = b"".join(b"\x00" + samples[y].tobytes() for y in range(height))

    def chunk(tag, payload):
        """One PNG chunk: length, tag, payload, CRC of tag and payload."""
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def snr_db(clean, estimate):
    """Signal-to-noise ratio of an estimate against the clean reference, in dB."""
    return 10.0 * np.log10(np.sum(clean**2) / np.sum((clean - estimate) ** 2))


def universal_threshold(finest, count):
    """Donoho's sqrt(2 log n) threshold, scaled by a median-absolute-deviation noise estimate.

    The estimate comes from the finest detail band, which is almost all noise — that is what
    lets the method work without being told how much noise there is.
    """
    return np.median(np.abs(finest)) / 0.6745 * np.sqrt(2.0 * np.log(count))


def denoise_signal(noisy, wavelet):
    """VisuShrink a 1-D signal: soft-threshold every detail band, keep the approximation."""
    coefficients = pywt.wavedec(noisy, wavelet, mode=MODE, level=LEVEL)
    threshold = universal_threshold(coefficients[-1], noisy.size)
    shrunk = [coefficients[0]]
    shrunk += [pywt.threshold(c, threshold, "soft") for c in coefficients[1:]]
    return pywt.waverec(shrunk, wavelet, mode=MODE)[: noisy.size]


def denoise_image(noisy, wavelet):
    """VisuShrink a 2-D image; the finest diagonal band carries the noise estimate."""
    coefficients = pywt.wavedec2(noisy, wavelet, mode=MODE, level=IMAGE_LEVEL)
    threshold = universal_threshold(coefficients[-1][-1], noisy.size)
    shrunk = [coefficients[0]]
    shrunk += [
        tuple(pywt.threshold(b, threshold, "soft") for b in bands)
        for bands in coefficients[1:]
    ]
    height, width = noisy.shape
    return pywt.waverec2(shrunk, wavelet, mode=MODE)[:height, :width]


def roundtrip_error(x, wavelet, level):
    """Largest |x - reconstruction| relative to max|x|, after a full decompose/recompose.

    Deliberately independent of everything else on screen: an orthogonal wavelet lands on
    double round-off, and a filter bank that does not invert cannot hide behind a good SNR.
    Both waverec calls are sliced because they return an even length.
    """
    if x.ndim == 1:
        coefficients = pywt.wavedec(x, wavelet, mode=MODE, level=level)
        rebuilt = pywt.waverec(coefficients, wavelet, mode=MODE)[: x.size]
    else:
        coefficients = pywt.wavedec2(x, wavelet, mode=MODE, level=level)
        height, width = x.shape
        rebuilt = pywt.waverec2(coefficients, wavelet, mode=MODE)[:height, :width]
    return float(np.max(np.abs(x - rebuilt)) / np.max(np.abs(x)))


def band_energies(x, wavelet):
    """Share of the signal's energy held by each band, coarsest first."""
    coefficients = pywt.wavedec(x, wavelet, mode=MODE, level=LEVEL)
    energies = np.array([float(np.sum(c**2)) for c in coefficients])
    labels = [f"A{LEVEL}"] + [f"D{i}" for i in range(LEVEL, 0, -1)]
    return list(zip(labels, energies / energies.sum()))


def analyse(signal_name, wavelet, sigma):
    """Run the whole pipeline once and return plain values for the UI to render.

    Everything on screen comes out of this call: the two round-trip residuals that grade the
    filter bank itself, the four SNRs that grade the denoising, the per-band energy shares,
    and the two PNGs. The generator is seeded, so a given signal, wavelet and sigma reproduce
    exactly and any change on screen is a change in the transform rather than in the noise.
    """
    rng = np.random.default_rng(7)
    image = source_image()

    clean = pywt.data.demo_signal(signal_name, N)
    clean = clean / np.max(np.abs(clean))
    noisy = clean + sigma * rng.standard_normal(N)
    estimate = denoise_signal(noisy, wavelet)

    noisy_image = image + sigma * rng.standard_normal(image.shape)
    restored = denoise_image(noisy_image, wavelet)

    return {
        "signal_residual": roundtrip_error(clean, wavelet, LEVEL),
        "image_residual": roundtrip_error(image, wavelet, IMAGE_LEVEL),
        "signal_snr": (snr_db(clean, noisy), snr_db(clean, estimate)),
        "image_snr": (snr_db(image, noisy_image), snr_db(image, restored)),
        "bands": band_energies(clean, wavelet),
        "noisy_png": encode_png(noisy_image),
        "restored_png": encode_png(restored),
    }
