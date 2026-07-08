import os

import numpy as np

# 170-byte y = relu(x @ W + b) graph generated with the onnx package
# (opset 17); real MatMul/Add/Relu execution, no downloads.
MODEL = os.path.join(os.path.dirname(__file__), "tiny_mlp.onnx")


def test_inference_session():
    """The keystone check: InferenceSession loads and executes a real graph
    through the CPU EP on-device."""
    import onnxruntime as ort

    sess = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    x = np.array([[1.0, 2.0, 3.0], [-1.0, -2.0, -3.0]], dtype=np.float32)
    (y,) = sess.run(None, {"x": x})

    # W = [[1,0],[0,1],[1,1]], b = [0.5, -0.5]  =>  relu([x0+x2+.5, x1+x2-.5])
    expected = np.maximum(
        np.stack([x[:, 0] + x[:, 2] + 0.5, x[:, 1] + x[:, 2] - 0.5], axis=1), 0
    )
    assert y.shape == (2, 2)
    assert np.allclose(y, expected)


def test_providers_and_metadata():
    import onnxruntime as ort

    assert "CPUExecutionProvider" in ort.get_available_providers()
    sess = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    assert [i.name for i in sess.get_inputs()] == ["x"]
    assert [o.name for o in sess.get_outputs()] == ["y"]
    assert ort.__version__.startswith("1.27")


def test_session_options_threads():
    """SessionOptions plumbing — the knob apps use per the P-core rule."""
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    sess = ort.InferenceSession(MODEL, opts, providers=["CPUExecutionProvider"])
    x = np.ones((4, 3), dtype=np.float32)
    (y,) = sess.run(None, {"x": x})
    assert y.shape == (4, 2)
