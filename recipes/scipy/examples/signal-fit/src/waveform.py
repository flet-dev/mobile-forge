import numpy as np
import scipy
from scipy import fft, optimize, signal

SAMPLE_RATE = 500.0
DURATION = 4.0
CUTOFF = 8.0
TRUE = {"amplitude": 2.5, "decay": 0.4, "frequency": 3.0, "phase": 0.6}

T = np.arange(0.0, DURATION, 1.0 / SAMPLE_RATE)


def _blas_name():
    """Name and version of the BLAS scipy is linked against, from its build config.

    OpenBLAS on both mobile platforms; a desktop Mac says Accelerate instead, which
    is the difference the mobile wheels deliberately remove. The lookup is guarded
    because the shape of that dict belongs to scipy: this runs at import, so an
    exception here would leave the app blank rather than cost one word of a header.
    """
    try:
        blas = scipy.show_config(mode="dicts")["Build Dependencies"]["blas"]
        return f"{blas.get('name', 'unknown')} {blas.get('version', '')}".strip()
    except Exception:
        return "unknown"


VERSION = f"scipy {scipy.__version__} — {T.size} samples, BLAS {_blas_name()}"


def model(t, amplitude, decay, frequency, phase):
    """The damped sinusoid, used both to generate the signal and to fit it back."""
    return amplitude * np.exp(-decay * t) * np.sin(2.0 * np.pi * frequency * t + phase)


def analyse(noise):
    """Bury the true waveform in noise, filter it, and fit its parameters back out.

    Three stages of compiled scipy in one call — a Butterworth low-pass, an FFT to
    find the dominant frequency, and a least-squares fit seeded from that peak.
    Returns the peak, the fitted parameters keyed by the same names as TRUE, and
    the RMS error against the noise-free signal, which is what says whether the
    recovery actually worked.
    """
    clean = model(T, **TRUE)
    noisy = clean + np.random.default_rng().normal(scale=noise, size=T.size)

    # sosfiltfilt runs the filter forwards and then backwards, so the waveform the
    # fit chases is not shifted in time the way a single pass would shift it.
    sos = signal.butter(4, CUTOFF, btype="low", fs=SAMPLE_RATE, output="sos")
    filtered = signal.sosfiltfilt(sos, noisy)

    spectrum = np.abs(fft.rfft(filtered))
    peak = float(fft.rfftfreq(T.size, 1.0 / SAMPLE_RATE)[np.argmax(spectrum)])

    # curve_fit is a local optimiser: started more than about half a cycle from the
    # true frequency it settles on a harmonic, so seed it from the spectrum.
    guess = [np.abs(filtered).max(), 1.0, peak, 0.0]
    fitted, _ = optimize.curve_fit(model, T, filtered, p0=guess)

    error = float(np.sqrt(np.mean((model(T, *fitted) - clean) ** 2)))
    return peak, dict(zip(TRUE, fitted)), error
