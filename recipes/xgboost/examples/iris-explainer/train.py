"""Train the model this app ships, on a desktop.

Run it with `uv run --group train python train.py`. It writes
src/assets/iris_xgb.joblib, the file the app loads on the device.
"""

import joblib
from sklearn.datasets import load_iris
from xgboost import XGBClassifier

features, species = load_iris(return_X_y=True)
model = XGBClassifier(n_estimators=30, max_depth=3, random_state=0)
model.fit(features, species)
joblib.dump(model, "src/assets/iris_xgb.joblib", compress=3)
