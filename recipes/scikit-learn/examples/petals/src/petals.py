"""The scikit-learn half of the app: thirty measurements, one model, kept on disk."""

import os

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.linear_model import LogisticRegression

# FLET_APP_STORAGE_DATA is durable, app-private storage: a model written here
# survives restarts and app upgrades, unlike the cache and temp directories.
MODEL_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "petals.joblib")

# scikit-learn links no BLAS of its own, so the scipy release is as much a part of
# what fitted a model as the scikit-learn one is.
VERSIONS = (
    f"scikit-learn {sklearn.__version__}, BLAS borrowed from scipy {scipy.__version__}"
)

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


def load_or_fit():
    """Reload the saved model, or fit one and save it if this is the first launch.

    Fitting is the expensive half of the work, so it happens once per install rather
    than once per launch. Returns the estimator and a line saying which of the two
    branches ran, which is the point the example is making.
    """
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH), f"Reloaded {MODEL_PATH}"
    model = LogisticRegression().fit(PETALS, SPECIES)
    joblib.dump(model, MODEL_PATH)
    return model, f"Fitted on {len(PETALS)} samples, saved {MODEL_PATH}"


def classify(model, length, width):
    """Name the species for one petal, in cm, with the model's confidence in it.

    Both measurements arrive as free text from the UI, so float() raises on anything
    unparseable and the caller turns that into a message. predict takes a 2-D array
    and returns one even for a single row; predict_proba returns a row of class
    probabilities, whose largest entry is the confidence in the label predict chose.
    """
    petal = [[float(length), float(width)]]
    [species] = model.predict(petal)
    return species, model.predict_proba(petal).max()
