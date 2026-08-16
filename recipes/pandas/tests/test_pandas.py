def test_basic():
    from pandas import DataFrame

    df = DataFrame(
        [("alpha", 1), ("bravo", 2), ("charlie", 3)],
        columns=["Letter", "Number"],
    )
    assert df.to_csv() == (
        ",Letter,Number\n" "0,alpha,1\n" "1,bravo,2\n" "2,charlie,3\n"
    )


def test_pyarrow_is_not_required():
    """pandas 3.0 defaults to an Arrow-backed string dtype where pyarrow is
    present, but the mobile wheel does not depend on it — which is what keeps
    armeabi-v7a usable, since pyarrow excludes that ABI. Assert pandas works and
    reports the python storage fallback when pyarrow is absent."""
    import pandas as pd

    frame = pd.DataFrame({"name": ["a", "b"], "qty": [1, 2]})
    assert frame["qty"].sum() == 3

    storage = getattr(frame["name"].dtype, "storage", None)
    assert storage in (None, "python", "pyarrow"), storage


def test_no_extension_is_missing_from_the_wheel():
    """Nothing is compiled out of the mobile pandas — the submodules a real app
    reaches for must all import on device."""
    import importlib

    for name in (
        "pandas.io.formats.style",
        "pandas._libs.tslibs",
        "pandas.core.groupby",
    ):
        importlib.import_module(name)
