"""On-device smoke tests for a compute-only pyarrow (libarrow + libarrow_compute;
no parquet / dataset / acero / flight / re2 / utf8proc, and numpy is absent on the
device). Everything here uses pure-Python value paths (.to_pylist() / .as_py());
nothing calls .to_numpy()/.to_pandas() or any re2/utf8proc string kernel.

Tests are ordered so a failure pinpoints the layer: import first (core libarrow),
the compute kernels last (the separate libarrow_compute .so + its rpath)."""


def test_import_version():
    """Canary: importing pyarrow loads the `pyarrow.lib` Cython module, which
    dynamically links the bundled/sibling libarrow — proof the C++ core resolved."""
    import pyarrow as pa

    assert pa.__version__


def test_array_and_table():
    """Arrays + a columnar Table round-trip through pure-python value paths."""
    import pyarrow as pa

    a = pa.array([1, 2, 3, 4])
    assert a.to_pylist() == [1, 2, 3, 4]

    t = pa.Table.from_pydict({"x": [1, 2, 3], "y": ["a", "b", "c"]})
    assert t.num_rows == 3
    assert t.column_names == ["x", "y"]
    assert t.column("x").to_pylist() == [1, 2, 3]


def test_recordbatch_and_schema():
    """Schema/types + RecordBatch construction."""
    import pyarrow as pa

    schema = pa.schema([("id", pa.int64()), ("name", pa.string())])
    rb = pa.RecordBatch.from_arrays(
        [pa.array([1, 2]), pa.array(["x", "y"])], schema=schema
    )
    assert rb.num_rows == 2
    assert rb.schema.field("id").type == pa.int64()
    assert rb.column(1).to_pylist() == ["x", "y"]


def test_ipc_roundtrip():
    """Serialize a RecordBatch to an Arrow IPC stream buffer and read it back —
    exercises the IPC module (arrow::ipc) with no pandas/numpy."""
    import pyarrow as pa

    batch = pa.RecordBatch.from_arrays(
        [pa.array([10, 20, 30]), pa.array(["p", "q", "r"])], names=["n", "s"]
    )

    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    buf = sink.getvalue()

    with pa.ipc.open_stream(pa.BufferReader(buf)) as reader:
        out = reader.read_all()

    assert out.num_rows == 3
    assert out.column("n").to_pylist() == [10, 20, 30]
    assert out.column("s").to_pylist() == ["p", "q", "r"]


def test_compute_kernels():
    """The separate libarrow_compute .so: dependency-free arithmetic/comparison/
    aggregate kernels (no re2/utf8proc). Runs last so a dlopen/rpath failure here
    is isolated to the compute lib."""
    import pyarrow as pa
    import pyarrow.compute as pc

    arr = pa.array([1, 2, 3, 4])
    assert pc.sum(arr).as_py() == 10
    assert pc.add(arr, pa.scalar(10)).to_pylist() == [11, 12, 13, 14]
    assert pc.equal(arr, pa.array([1, 9, 3, 9])).to_pylist() == [True, False, True, False]

    mm = pc.min_max(arr)
    assert mm["min"].as_py() == 1
    assert mm["max"].as_py() == 4
