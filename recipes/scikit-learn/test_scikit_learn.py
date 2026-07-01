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
