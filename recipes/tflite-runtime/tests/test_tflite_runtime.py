import os

MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dense_relu.tflite")


def test_interpreter_surface():
    """The Interpreter class and its wrapper module load (the pybind .so is
    the whole recipe)."""
    from tflite_runtime.interpreter import Interpreter, load_delegate  # noqa: F401

    assert Interpreter is not None


def test_real_inference():
    """Real inference through the bundled 1KB dense+relu model (committed
    test asset, generated and validated with desktop TF 2.21: fixed weights,
    seed 42). Runs everywhere -- CI emulator included."""
    import numpy as np
    from tflite_runtime.interpreter import Interpreter

    interpreter = Interpreter(model_path=MODEL)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]

    assert inp["shape"].tolist() == [1, 4]
    assert out["shape"].tolist() == [1, 3]

    x = np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32)
    interpreter.set_tensor(inp["index"], x)
    interpreter.invoke()
    y = interpreter.get_tensor(out["index"])

    # Desktop-recorded expectation (XNNPACK delegate): relu clamps lanes 0-1.
    expected = np.array([[0.0, 0.0, 2.817584753036499]], dtype=np.float32)
    np.testing.assert_allclose(y, expected, rtol=1e-5, atol=1e-6)


def test_invoke_twice():
    """Tensor re-set + second invoke exercises the wrapper's buffer
    handling; a zeros probe reduces the graph to relu(bias), whose value is
    desktop-recorded."""
    import numpy as np
    from tflite_runtime.interpreter import Interpreter

    interpreter = Interpreter(model_path=MODEL)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]

    interpreter.set_tensor(inp["index"], np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32))
    interpreter.invoke()
    first = interpreter.get_tensor(out["index"]).copy()
    assert first.max() > 0

    interpreter.set_tensor(inp["index"], np.zeros((1, 4), dtype=np.float32))
    interpreter.invoke()
    second = interpreter.get_tensor(out["index"])
    expected = np.array([[0.6648852825164795, 0.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(second, expected, rtol=1e-5, atol=1e-6)
