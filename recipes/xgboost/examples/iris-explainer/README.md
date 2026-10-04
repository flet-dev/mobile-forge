# xgboost iris explainer

A gradient-boosted classifier trained on a desktop and shipped inside the app as a `.joblib`
file. Four sliders set a flower's sepal and petal measurements; the app names the species,
shows the probability of each, and breaks the winning score down by measurement. The header
line says which XGBoost build is running and whether it has OpenMP.

What it demonstrates:

- **The train-on-desktop, predict-on-device workflow.** [`train.py`](train.py) fits an
  `XGBClassifier` on scikit-learn's iris data and writes
  [`src/assets/iris_xgb.joblib`](src/assets/iris_xgb.joblib); the app reads it from
  [`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
  with [`joblib.load`](https://joblib.readthedocs.io/en/stable/generated/joblib.load.html).
- **No scikit-learn on the device.** It was needed to train the model, but the app's
  dependencies are XGBoost and joblib alone — a bare `XGBClassifier` predicts without it.
  The species names live in the app because the model's `classes_` would need scikit-learn.
- **Explaining a prediction.**
  [`pred_contribs=True`](https://xgboost.readthedocs.io/en/stable/python/python_api.html#xgboost.Booster.predict)
  returns XGBoost's TreeSHAP values; the bars are the winning class's, green where a
  measurement raised its score and red where it lowered it.
- **Load off the UI thread, predict on it.** Loading runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), which
  needs the explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
  it ends with. A prediction from a model this size takes milliseconds, so it runs directly
  in the sliders' change handler; the footer shows the time.
- **Shedding scipy's test suites.** `import xgboost` loads scipy, and the
  `[tool.flet.cleanup]` table in [`pyproject.toml`](pyproject.toml) keeps its tests, and
  numpy's, out of the app.

To retrain, run `uv run --group train python train.py` with the XGBoost version the app
pins.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
