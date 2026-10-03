import os
import platform
import sys

import numpy as np
import pytest

HERE = os.path.dirname(__file__)

# iris_classifier.joblib was written on a desktop with xgboost 3.4.1 and
# scikit-learn 1.9.0:
#   model = XGBClassifier(n_estimators=8, max_depth=2, random_state=0)
#   model.fit(*load_iris(return_X_y=True))
#   joblib.dump(model, "iris_classifier.joblib", compress=3)
# IRIS_PROBA is that model's predict_proba(IRIS_ROWS), computed there.
IRIS_ROWS = [[5.1, 3.5, 1.4, 0.2], [6.6, 3.0, 4.4, 1.4], [6.7, 3.1, 5.6, 2.4]]
IRIS_PROBA = [
    [0.922946, 0.039821, 0.037233],
    [0.04813, 0.903655, 0.048215],
    [0.037542, 0.04443, 0.918028],
]


def _data(seed=0, n=400):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 5)).astype(np.float32)
    y = ((X[:, 0] > 0) & (X[:, 1] < 0.5) | (X[:, 2] > 1.0)).astype(np.int32)
    return X, y


def test_train_and_predict():
    """Full train->predict loop through the ctypes C API (libxgboost)."""
    import xgboost as xgb

    X, y = _data()
    booster = xgb.train(
        {"objective": "binary:logistic", "nthread": 2, "seed": 0},
        xgb.DMatrix(X, label=y),
        num_boost_round=30,
    )
    acc = ((booster.predict(xgb.DMatrix(X)) > 0.5) == y).mean()
    assert acc > 0.95


def test_model_save_load_roundtrip(tmp_path):
    """Persistence in the portable UBJSON format."""
    import xgboost as xgb

    X, y = _data(seed=1)
    dtrain = xgb.DMatrix(X, label=y)
    booster = xgb.train({"objective": "binary:logistic", "seed": 0}, dtrain, 10)

    path = str(tmp_path / "model.ubj")
    booster.save_model(path)
    loaded = xgb.Booster(model_file=path)
    assert np.allclose(loaded.predict(xgb.DMatrix(X)), booster.predict(xgb.DMatrix(X)))


def test_pred_contribs_treeshap():
    """predict(pred_contribs=True) is built-in TreeSHAP — feature attribution
    without the (numba-blocked) shap package."""
    import xgboost as xgb

    X, y = _data(seed=2)
    dtrain = xgb.DMatrix(X, label=y)
    booster = xgb.train({"objective": "binary:logistic", "seed": 0}, dtrain, 10)

    dtest = xgb.DMatrix(X[:8])
    contrib = booster.predict(dtest, pred_contribs=True)
    assert contrib.shape == (8, X.shape[1] + 1)  # + bias column
    raw = booster.predict(dtest, output_margin=True)
    assert np.allclose(contrib.sum(axis=1), raw, atol=1e-5)


def test_desktop_joblib_classifier():
    """A desktop-trained XGBClassifier loaded from .joblib predicts exactly as it
    did there, with no scikit-learn installed in the app."""
    import joblib

    model = joblib.load(os.path.join(HERE, "iris_classifier.joblib"))
    proba = model.predict_proba(np.asarray(IRIS_ROWS))
    assert np.allclose(proba, IRIS_PROBA, atol=1e-5)
    assert model.predict(np.asarray(IRIS_ROWS)).tolist() == [0, 1, 2]


def test_openmp_matches_platform():
    """OpenMP is compiled in on Android, where flet-libomp ships the runtime,
    and out on iOS, which has none."""
    import xgboost as xgb

    if hasattr(sys, "getandroidapilevel"):
        assert xgb.build_info()["USE_OPENMP"] is True
    elif sys.platform == "ios" or platform.system() == "iOS":
        assert xgb.build_info()["USE_OPENMP"] is False
    else:
        pytest.skip("not a mobile build")
