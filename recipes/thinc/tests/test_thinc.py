def test_import():
    """The package imports. This path is pure Python: a bare `import thinc` loads
    none of the six extensions and does not read _custom_kernels.cu."""
    import thinc


def test_numpy_ops_gemm():
    """Importing thinc.api loads five of the six extensions — numpy_ops, cblas,
    linalg, premap_ids, sparselinear — and reads _custom_kernels.cu off disk. The
    gemm itself lands in the blis wheel's own extension, via blis.py.gemm."""
    import numpy
    from thinc.api import NumpyOps

    ops = NumpyOps()
    a = numpy.ones((2, 3), dtype="float32")
    b = numpy.ones((3, 4), dtype="float32")
    out = ops.gemm(a, b)
    assert out.shape == (2, 4)
    assert float(out[0, 0]) == 3.0


def test_linear_forward():
    """A Linear forward pass adds thinc's Model machinery — parameter allocation,
    init, __call__ — over the same NumpyOps.gemm path. Nothing in this file reaches
    extra/search, the sixth extension."""
    import numpy
    from thinc.api import Linear

    model = Linear(nO=4, nI=3)
    model.initialize(X=numpy.zeros((1, 3), dtype="float32"))
    Y, _ = model(numpy.ones((2, 3), dtype="float32"), is_train=False)
    assert Y.shape == (2, 4)
