"""An iris classifier fitted on device, saved with joblib, and reloaded on the next launch."""

import os

import flet as ft
import joblib
import numpy as np
import scipy
import sklearn
from sklearn.linear_model import LogisticRegression

# FLET_APP_STORAGE_DATA is durable, app-private storage: a model written here
# survives restarts and app upgrades, unlike the cache and temp directories.
MODEL_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "petals.joblib")

# Petal length and width in cm, from Fisher's iris measurements.
PETALS = np.array(
    [
        [1.4, 0.2],
        [1.7, 0.4],
        [1.5, 0.2],
        [1.5, 0.4],
        [1.7, 0.2],
        [1.6, 0.2],
        [1.6, 0.2],
        [1.2, 0.2],
        [1.3, 0.3],
        [1.4, 0.3],
        [4.7, 1.4],
        [4.5, 1.3],
        [3.5, 1.0],
        [4.4, 1.4],
        [4.8, 1.8],
        [4.4, 1.4],
        [3.8, 1.1],
        [4.5, 1.6],
        [4.4, 1.2],
        [4.2, 1.2],
        [6.0, 2.5],
        [6.6, 2.1],
        [5.1, 2.0],
        [5.3, 2.3],
        [5.7, 2.3],
        [6.0, 1.8],
        [6.1, 1.9],
        [6.1, 2.3],
        [5.6, 2.4],
        [5.2, 2.3],
    ]
)
SPECIES = np.array(["setosa"] * 10 + ["versicolor"] * 10 + ["virginica"] * 10)


def main(page: ft.Page):
    """Two petal measurements, a Classify button, and the species the model predicts.

    The line at the bottom says whether this launch fitted the model or reloaded the
    one in app storage, and prints the path it lives at.
    """

    model = None

    def prepare():
        """Reload the saved model, or fit one and save it if this is the first launch.

        Fitting is the expensive half, so it happens once per install rather than once
        per launch. Runs in the thread pool and enables Classify when it lands.
        """
        nonlocal model
        if os.path.exists(MODEL_PATH):
            model = joblib.load(MODEL_PATH)
            status.value = f"Reloaded {MODEL_PATH}"
        else:
            model = LogisticRegression().fit(PETALS, SPECIES)
            joblib.dump(model, MODEL_PATH)
            status.value = f"Fitted on {len(PETALS)} samples, saved {MODEL_PATH}"
        button.disabled = False
        page.update()  # auto-update does not reach background threads

    def classify():
        """Predict the species for the two typed measurements.

        Both fields are free text, so anything unparseable is answered on screen
        rather than raised. Stays on the event handler, which is why nothing here
        updates the page itself.
        """
        try:
            petal = [[float(length.value), float(width.value)]]
        except (TypeError, ValueError):
            result.value = "Enter two numbers"
            return
        [species] = model.predict(petal)
        result.value = f"{species} — {model.predict_proba(petal).max():.0%} confident"

    page.appbar = ft.AppBar(title=ft.Text("Petal classifier"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"scikit-learn {sklearn.__version__}, "
                        f"BLAS borrowed from scipy {scipy.__version__}",
                        size=12,
                    ),
                    ft.Row(
                        controls=[
                            length := ft.TextField(
                                label="Petal length (cm)",
                                value="4.5",
                                keyboard_type=ft.KeyboardType.NUMBER,
                                expand=True,
                            ),
                            width := ft.TextField(
                                label="Petal width (cm)",
                                value="1.4",
                                keyboard_type=ft.KeyboardType.NUMBER,
                                expand=True,
                            ),
                        ]
                    ),
                    button := ft.Button(
                        content="Classify",
                        icon=ft.Icons.SCIENCE,
                        disabled=True,
                        on_click=classify,
                    ),
                    result := ft.Text(size=22, weight=ft.FontWeight.BOLD),
                    status := ft.Text("Fitting…", size=11, selectable=True),
                ]
            ),
        )
    )

    # fit() is CPU-bound and would block the first frame; predict() on one row is not.
    page.run_thread(prepare)


if __name__ == "__main__":
    ft.run(main)
