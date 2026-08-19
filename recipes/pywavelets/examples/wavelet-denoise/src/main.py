"""Wavelet denoising, with an on-screen check that the transform itself loses nothing."""

import struct
import threading
import zlib

import flet as ft
import numpy as np
import pywt

N = 4096
LEVEL = 6
IMAGE_LEVEL = 3

# periodization is the only mode that keeps len(coefficients) == len(signal), which is what
# makes the energy shares below add up to exactly 100%.
MODE = "periodization"

SIGNALS = ["Doppler", "Bumps", "HeaviSine", "Blocks"]
WAVELETS = ["haar", "db4", "sym8", "dmey"]

# Ships inside the wheel, so there is nothing to bundle and nothing to download.
IMAGE = pywt.data.camera().astype(np.float64) / 255.0


def encode_png(image):
    """Encode a [0, 1] float image as 8-bit greyscale PNG bytes for ft.Image(src=...).

    Hand-written because numpy is the only thing this app depends on besides Flet — there
    is no image library on device to do it.
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


SOURCE_PNG = encode_png(IMAGE)


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


def main(page: ft.Page):
    """Pick a signal, a wavelet and a noise level; every number below is computed from them."""
    lock = threading.Lock()

    def recompute():
        """Redo the whole pipeline and redraw.

        Runs in Flet's thread pool, which can overlap two runs, so the lock stops their
        writes from interleaving into the same controls and the explicit page.update() at
        the end does what auto-update does not reach.
        """
        with lock:
            wavelet = wavelets.selected[0]
            sigma = round(noise.value, 2)
            rng = np.random.default_rng(7)

            clean = pywt.data.demo_signal(signal.value, N)
            clean = clean / np.max(np.abs(clean))
            noisy = clean + sigma * rng.standard_normal(N)
            estimate = denoise_signal(noisy, wavelet)

            noisy_image = IMAGE + sigma * rng.standard_normal(IMAGE.shape)
            restored = denoise_image(noisy_image, wavelet)

            signal_error = roundtrip_error(clean, wavelet, LEVEL)
            image_error = roundtrip_error(IMAGE, wavelet, IMAGE_LEVEL)
            check.value = (
                f"round trip: signal {signal_error:.1e}   image {image_error:.1e}"
            )
            check.color = (
                ft.Colors.RED
                if max(signal_error, image_error) > 1e-9
                else ft.Colors.GREEN
            )

            report.value = (
                f"{wavelet} · sigma {sigma:.2f} · "
                f"signal {snr_db(clean, noisy):.1f} -> {snr_db(clean, estimate):.1f} dB · "
                f"image {snr_db(IMAGE, noisy_image):.1f} -> {snr_db(IMAGE, restored):.1f} dB"
            )
            bands.controls = [
                ft.Row(
                    controls=[
                        ft.Text(label, size=12, width=28),
                        ft.ProgressBar(value=share, expand=True),
                        ft.Text(f"{100.0 * share:5.2f}%", size=12, width=52),
                    ]
                )
                for label, share in band_energies(clean, wavelet)
            ]
            before.src = encode_png(noisy_image)
            after.src = encode_png(restored)
        page.update()

    def refresh():
        """Send the recompute off the UI thread — the 2-D transforms are far too slow for it."""
        page.run_thread(recompute)

    page.appbar = ft.AppBar(title=ft.Text("Wavelet denoise"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    signal := ft.Dropdown(
                        label="Signal",
                        value=SIGNALS[0],
                        options=[ft.DropdownOption(key=s, text=s) for s in SIGNALS],
                        on_select=refresh,
                    ),
                    wavelets := ft.SegmentedButton(
                        selected=["db4"],
                        segments=[
                            ft.Segment(value=w, label=ft.Text(w, size=11))
                            for w in WAVELETS
                        ],
                        on_change=refresh,
                    ),
                    noise := ft.Slider(
                        min=0.05,
                        max=0.40,
                        divisions=7,
                        round=2,
                        value=0.10,
                        label="sigma {value}",
                        on_change_end=refresh,
                    ),
                    check := ft.Text(size=15, weight=ft.FontWeight.BOLD),
                    report := ft.Text(size=12),
                    bands := ft.Column(spacing=2),
                    ft.Row(
                        controls=[
                            ft.Text(
                                caption,
                                size=11,
                                expand=True,
                                text_align=ft.TextAlign.CENTER,
                            )
                            for caption in ("noisy", "denoised")
                        ]
                    ),
                    ft.Row(
                        controls=[
                            before := ft.Image(
                                src=SOURCE_PNG,
                                height=170,
                                expand=True,
                                fit=ft.BoxFit.CONTAIN,
                                gapless_playback=True,
                            ),
                            after := ft.Image(
                                src=SOURCE_PNG,
                                height=170,
                                expand=True,
                                fit=ft.BoxFit.CONTAIN,
                                gapless_playback=True,
                            ),
                        ]
                    ),
                ],
            ),
        )
    )

    refresh()


if __name__ == "__main__":
    ft.run(main)
