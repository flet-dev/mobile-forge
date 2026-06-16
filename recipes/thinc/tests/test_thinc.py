def test_import():
    """thinc imports and its compiled C++ extensions load (numpy_ops, cblas,
    sparselinear, premap_ids — which link cymem/preshed/murmurhash/blis)."""
    import thinc


def test_numpy_ops_gemm():
    """NumpyOps.gemm goes through the compiled numpy_ops backend (cimports
    cymem/preshed/murmurhash/numpy) and the cblas backend (cimports blis.cy)."""
    import numpy
    from thinc.api import NumpyOps

    ops = NumpyOps()
    a = numpy.ones((2, 3), dtype="float32")
    b = numpy.ones((3, 4), dtype="float32")
    out = ops.gemm(a, b)
    assert out.shape == (2, 4)
    assert float(out[0, 0]) == 3.0


def test_linear_forward():
    """A small Linear layer forward pass exercises the ML stack end to end."""
    import numpy
    from thinc.api import Linear

    model = Linear(nO=4, nI=3)
    model.initialize(X=numpy.zeros((1, 3), dtype="float32"))
    Y, _ = model(numpy.ones((2, 3), dtype="float32"), is_train=False)
    assert Y.shape == (2, 4)
