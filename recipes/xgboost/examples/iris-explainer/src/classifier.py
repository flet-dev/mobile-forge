import os
import time
from dataclasses import dataclass

import joblib
import numpy as np
import xgboost as xgb

MODEL_FILE = "iris_xgb.joblib"

# XGBoost encodes classes as 0..n-1, so the names live with the app.
SPECIES = ("setosa", "versicolor", "virginica")

# Label, slider minimum, maximum and starting value, in centimetres.
FEATURES = (
    ("Sepal length", 4.3, 7.9, 5.8),
    ("Sepal width", 2.0, 4.4, 3.0),
    ("Petal length", 1.0, 6.9, 4.4),
    ("Petal width", 0.1, 2.5, 1.3),
)


@dataclass
class Prediction:
    """One classification as plain values, ready for the UI."""

    species: str
    probabilities: list[float]
    contributions: list[float]
    elapsed_ms: float


def load():
    """Load the classifier train.py wrote into the app's assets.

    A .joblib file is a pickle, and unpickling runs code, so load only a file your
    own build shipped. Built apps and `flet run` put the assets folder in
    FLET_ASSETS_DIR; a plain `python main.py` does not, hence the fallback.
    """
    assets = os.getenv("FLET_ASSETS_DIR") or os.path.join(
        os.path.dirname(__file__), "assets"
    )
    return joblib.load(os.path.join(assets, MODEL_FILE))


def describe(model):
    """Name the model and the build running it, so a device run shows which it got."""
    rounds = model.get_booster().num_boosted_rounds()
    openmp = "on" if xgb.build_info()["USE_OPENMP"] else "off"
    return f"xgboost {xgb.__version__} · {rounds} rounds · OpenMP {openmp}"


def predict(model, measurements):
    """Classify one flower and say how much each measurement pushed the winner.

    `pred_contribs=True` is XGBoost's built-in TreeSHAP: per class, one score per
    feature plus a bias column, which together sum to that class's raw margin.
    """
    row = np.asarray([measurements], dtype=np.float32)
    start = time.perf_counter()
    probabilities = model.predict_proba(row)[0]
    winner = int(probabilities.argmax())
    shap = model.get_booster().predict(xgb.DMatrix(row), pred_contribs=True)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return Prediction(
        species=SPECIES[winner],
        probabilities=probabilities.tolist(),
        contributions=shap[0, winner, :-1].tolist(),
        elapsed_ms=elapsed_ms,
    )
