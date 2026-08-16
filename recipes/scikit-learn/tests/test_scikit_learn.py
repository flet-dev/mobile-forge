import numpy as np


def test_linear_regression():
    """LinearRegression -> exercises the scipy.linalg (BLAS) solve path."""
    from sklearn.linear_model import LinearRegression

    x = np.array([[1.0], [2.0], [3.0], [4.0]])
    y = np.array([2.0, 4.0, 6.0, 8.0])
    m = LinearRegression().fit(x, y)
    assert abs(m.coef_[0] - 2.0) < 1e-9
    assert abs(m.intercept_) < 1e-9
    assert np.allclose(m.predict([[5.0]]), [10.0])


def test_svc():
    """SVC(linear) -> exercises the vendored libsvm C++ extension."""
    from sklearn.svm import SVC

    x = np.array([[0.0, 0.0], [0.2, 0.1], [1.0, 1.0], [0.9, 1.1]])
    y = np.array([0, 0, 1, 1])
    clf = SVC(kernel="linear").fit(x, y)
    assert clf.predict([[0.95, 1.0]])[0] == 1
    assert clf.predict([[0.05, 0.05]])[0] == 0


def test_kmeans():
    """KMeans -> exercises the Cython (+ optional OpenMP) compute path."""
    from sklearn.cluster import KMeans

    x = np.array([[0.0, 0.0], [0.1, 0.1], [10.0, 10.0], [10.1, 9.9]])
    km = KMeans(n_clusters=2, n_init=1, random_state=0).fit(x)
    assert len(set(km.labels_.tolist())) == 2
    # the two near-origin points share a cluster; the two near-(10,10) share the other
    assert km.labels_[0] == km.labels_[1]
    assert km.labels_[2] == km.labels_[3]
    assert km.labels_[0] != km.labels_[2]


def test_repr_html_css_is_readable():
    """sklearn reads estimator.css through Path(__file__) while importing, which
    is the exact read that fails inside Android's sitepackages.zip. This is what
    makes `extract_packages: [sklearn]` mandatory for consumers, so keep it a
    test rather than only a sentence in the README."""
    from sklearn.utils._repr_html.estimator import _CSS_STYLE

    assert isinstance(_CSS_STYLE, str) and _CSS_STYLE.strip()


def test_openmp_matches_the_platform():
    """OpenMP is compiled in on Android and out on iOS
    (disable-openmp-non-android.patch). Guard that against silently inverting on
    a bump — it is the difference between a multi-core and a single-core fit."""
    import sys

    from sklearn.utils._openmp_helpers import _openmp_parallelism_enabled

    if sys.platform == "android":
        assert _openmp_parallelism_enabled()
    elif sys.platform == "ios":
        assert not _openmp_parallelism_enabled()


def test_blas_comes_from_scipy():
    """No BLAS is linked into scikit-learn; it borrows scipy's through
    scipy.linalg.cython_blas capsules. Make that a runtime fact rather than an
    inference from DT_NEEDED."""
    import sys

    import numpy as np
    from sklearn.utils.extmath import safe_sparse_dot

    import sklearn.utils._cython_blas  # noqa: F401

    assert "scipy.linalg.cython_blas" in sys.modules
    product = safe_sparse_dot(np.array([[1.0, 2.0]]), np.array([[3.0], [4.0]]))
    assert np.allclose(product, [[11.0]]), product


def test_model_round_trips_through_app_storage(tmp_path):
    """The Storage section tells consumers to joblib.dump a fitted model into
    FLET_APP_STORAGE_DATA and reload it next launch. Exercise that whole path on
    device, including joblib itself."""
    import os

    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    features = np.array([[1.0], [2.0], [7.0], [8.0]])
    labels = np.array([0, 0, 1, 1])
    model = LogisticRegression().fit(features, labels)

    target = os.path.join(
        os.environ.get("FLET_APP_STORAGE_DATA", str(tmp_path)), "m.joblib"
    )
    joblib.dump(model, target)
    reloaded = joblib.load(target)

    probe = np.array([[1.5], [7.5]])
    assert list(reloaded.predict(probe)) == list(model.predict(probe))
