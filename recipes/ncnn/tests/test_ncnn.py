import os

import numpy as np

# A weightless graph in ncnn's text .param format: Input -> global max
# Pooling. Real graph execution through the full Net/Extractor machinery
# with an EMPTY .bin (pooling has no weights) — no model downloads.
PARAM = """7767517
2 2
Input            input    0 1 input
Pooling          gmp      1 1 input output 0=0 4=1
"""


def test_mat_numpy_roundtrip():
    """ncnn.Mat shares memory semantics with numpy — the tensor bridge every
    real pipeline uses."""
    import ncnn

    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    mat = ncnn.Mat(arr)
    back = np.array(mat)
    assert back.shape == (3, 4)
    assert np.array_equal(back, arr)


def test_weightless_graph_inference(tmp_path):
    """Load a param graph + empty bin, run the Extractor — proves the whole
    inference engine (layer registry, blob allocator, threading) on-device."""
    import ncnn

    param = tmp_path / "tiny.param"
    param.write_text(PARAM)
    bin_path = tmp_path / "tiny.bin"
    bin_path.write_bytes(b"")

    net = ncnn.Net()
    assert net.load_param(str(param)) == 0
    assert net.load_model(str(bin_path)) == 0

    # ncnn layers operate on (c, h, w) — a 2D array would be pooled per-row.
    x = np.zeros((1, 4, 4), dtype=np.float32)
    x[0, 2, 1] = 42.5
    ex = net.create_extractor()
    ex.input("input", ncnn.Mat(x))
    ret, out = ex.extract("output")
    assert ret == 0
    result = np.array(out).flatten()
    assert result.shape == (1,) and result[0] == 42.5


def test_cpu_info():
    import ncnn

    # model-free CPU introspection (big.LITTLE awareness on device)
    assert ncnn.get_cpu_count() >= 1
