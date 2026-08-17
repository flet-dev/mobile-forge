"""Recover a damped sinusoid buried in noise with scipy.signal, scipy.fft and scipy.optimize."""

import flet as ft
import numpy as np
import scipy
from scipy import fft, optimize, signal

SAMPLE_RATE = 500.0
DURATION = 4.0
CUTOFF = 8.0
TRUE = {"amplitude": 2.5, "decay": 0.4, "frequency": 3.0, "phase": 0.6}

t = np.arange(0.0, DURATION, 1.0 / SAMPLE_RATE)

_blas = scipy.show_config(mode="dicts")["Build Dependencies"]["blas"]
BLAS = f"{_blas.get('name', 'unknown')} {_blas.get('version', '')}".strip()


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
    clean = model(t, **TRUE)
    noisy = clean + np.random.default_rng().normal(scale=noise, size=t.size)

    # sosfiltfilt runs the filter forwards and then backwards, so the waveform the
    # fit chases is not shifted in time the way a single pass would shift it.
    sos = signal.butter(4, CUTOFF, btype="low", fs=SAMPLE_RATE, output="sos")
    filtered = signal.sosfiltfilt(sos, noisy)

    spectrum = np.abs(fft.rfft(filtered))
    peak = float(fft.rfftfreq(t.size, 1.0 / SAMPLE_RATE)[np.argmax(spectrum)])

    # curve_fit is a local optimiser: started more than about half a cycle from the
    # true frequency it settles on a harmonic, so seed it from the spectrum.
    guess = [np.abs(filtered).max(), 1.0, peak, 0.0]
    fitted, _ = optimize.curve_fit(model, t, filtered, p0=guess)

    error = float(np.sqrt(np.mean((model(t, *fitted) - clean) ** 2)))
    return peak, dict(zip(TRUE, fitted)), error


def row(label, *cells):
    """One line of the results table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    """Show a noise slider, a Fit button, and a table of true against fitted values.

    The header line reports the scipy build the app is running on, including the
    BLAS it is linked against — OpenBLAS on both mobile platforms, where a desktop
    Mac would say Accelerate.
    """

    def show_noise():
        """Report the noise the next fit will use; the slider sets it, Fit runs it."""
        caption.value = f"Noise added before filtering: {noise.value:.1f}"

    def fit():
        """Run the analysis on a background thread, so the UI stays live.

        The button stays disabled until compute() re-enables it, which keeps two
        fits from overlapping and writing the table in the wrong order.
        """
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Fit at the slider's noise level and fill in the results table.

        The body of the thread fit() starts. Push the noise up and the fitted
        amplitude starts to wander while the frequency holds: the spectrum peak
        survives noise that the tail of a decaying signal does not.
        """
        peak, fitted, error = analyse(noise.value)
        results.controls = [
            row("", "true", "fitted"),
            ft.Divider(height=1),
            *(
                row(name, f"{value:.4f}", f"{fitted[name]:.4f}")
                for name, value in TRUE.items()
            ),
            ft.Divider(height=1),
            row("spectrum peak", f"{peak:.4f} Hz"),
            row("rms error", f"{error:.2e}"),
        ]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("scipy signal fit"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"scipy {scipy.__version__} — {t.size} samples, BLAS {BLAS}",
                        size=12,
                    ),
                    caption := ft.Text(),
                    noise := ft.Slider(
                        min=0.0,
                        max=4.0,
                        value=1.0,
                        divisions=8,
                        round=1,
                        label="{value}",
                        on_change=show_noise,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Fit", icon=ft.Icons.SHOW_CHART, on_click=fit
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                ]
            ),
        )
    )

    show_noise()
    fit()


if __name__ == "__main__":
    ft.run(main)
