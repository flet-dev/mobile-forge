import numpy as np

# Native xgboost.train API throughout: the sklearn wrapper (XGBClassifier)
# would import scikit-learn, which is not in xgboost's Requires-Dist.


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
