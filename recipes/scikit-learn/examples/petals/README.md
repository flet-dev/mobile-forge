# petals

A one-screen iris classifier. On the first launch it fits a
[`LogisticRegression`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html)
on thirty petal measurements and writes the fitted model to app storage; on every launch
after that it reloads that file instead of fitting again. Type a petal length and width,
tap Classify, and the species and confidence come back from the model on the device. Kill
the app and reopen it: the line at the bottom, which also prints the full path the model
lives at, changes from *Fitted…* to *Reloaded…*.

What it demonstrates:

- **A fitted model in app storage** — [joblib](https://joblib.readthedocs.io/en/stable/generated/joblib.dump.html)
  writes `petals.joblib` into
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  the app-private directory that is never auto-deleted and is included in backups, so the
  expensive half of the work happens exactly once per install.
- **Fitting off the UI thread** — `fit` runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the Classify button disabled until it lands, and the background handler ends with the
  explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that
  auto-update does not do for you. `predict` on a single row stays on the event handler.
- **Where the linear algebra comes from** — the header prints the scipy version next to the
  scikit-learn one, because scikit-learn takes its BLAS from `scipy.linalg.cython_blas`
  rather than linking one of its own.
- **The Android `extract_packages` entry** — `pyproject.toml` carries
  `extract_packages = ["sklearn"]`, without which `import sklearn` fails on device.

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
