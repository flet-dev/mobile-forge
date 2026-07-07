import ctypes
import struct


def _spec(TensorSpec, data, shape):
    # serialize() takes raw pointers (TensorSpec); a ctypes buffer keeps the
    # memory alive for the duration of the call. Constructor takes
    # python-style dtype names ("float32"); headers/output use safetensors
    # format codes ("F32").
    buf = ctypes.create_string_buffer(data, len(data))
    spec = TensorSpec(
        dtype="float32", shape=shape, data_ptr=ctypes.addressof(buf), data_len=len(data)
    )
    return spec, buf


def test_serialize_deserialize_roundtrip():
    """safetensors is a PyO3 wrapper around the Rust core. Round-trip a
    tensor through the bytes-level API — no numpy/torch needed."""
    from safetensors import TensorSpec, deserialize, serialize

    data = struct.pack("<2f", 1.0, 2.0)
    spec, buf = _spec(TensorSpec, data, [2])
    blob = serialize({"emb": spec})
    out = dict(deserialize(bytes(blob)))

    assert out["emb"]["dtype"] == "F32"
    assert list(out["emb"]["shape"]) == [2]
    assert bytes(out["emb"]["data"]) == data


def test_serialize_file_roundtrip(tmp_path):
    """serialize_file writes through the Rust file path; numpy-free (the
    recipe-tester app only ships the recipe's own hard deps, and safetensors
    has none — safe_open needs a framework module, so it lives in the
    numpy-gated test below)."""
    from safetensors import TensorSpec, deserialize, serialize_file

    data = struct.pack("<4f", 1.0, 2.0, 3.0, 4.0)
    spec, buf = _spec(TensorSpec, data, [2, 2])
    path = str(tmp_path / "weights.safetensors")
    serialize_file({"w": spec}, path)

    with open(path, "rb") as f:
        out = dict(deserialize(f.read()))
    assert list(out["w"]["shape"]) == [2, 2]
    assert bytes(out["w"]["data"]) == data


def test_numpy_safe_open_roundtrip(tmp_path):
    """The numpy integration + mmap safe_open path is what downstream
    consumers (model2vec) use."""
    import pytest

    np = pytest.importorskip("numpy")
    from safetensors import safe_open
    from safetensors.numpy import load, save_file

    arr = np.arange(6, dtype=np.float32).reshape(2, 3)
    path = str(tmp_path / "weights.safetensors")
    save_file({"emb": arr}, path)

    with safe_open(path, framework="numpy") as f:
        assert f.keys() == ["emb"]
        assert np.array_equal(f.get_tensor("emb"), arr)

    with open(path, "rb") as fh:
        import safetensors.numpy as st_np

        assert np.array_equal(st_np.load(fh.read())["emb"], arr)
