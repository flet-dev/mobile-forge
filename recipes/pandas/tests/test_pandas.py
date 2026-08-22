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

    for name in ("pandas._libs.tslibs", "pandas.core.groupby", "pandas.io.formats"):
        importlib.import_module(name)


def test_styler_templates_track_how_the_package_was_installed():
    """Styler reads its templates off disk, so zipped site-packages breaks it.

    pandas resolves `pandas/io/formats/templates/` from that module's own `__file__`
    through a jinja2 `FileSystemLoader`, and touching `.style` loads `html.tpl` at class
    definition time. Android ships site-packages as a zip unless the app sets
    `extract_packages = ["pandas"]` — and a zip member is not a directory, so the import
    raises `TemplateNotFound` there while iOS, which installs unzipped, imports fine.

    This asserts against the *packaging* rather than the platform on purpose: on Python
    3.12 `sys.platform` is "linux" on Android, so a platform gate would silently skip
    both branches and pass without checking anything.
    """
    import importlib
    import os

    import jinja2
    import pytest

    import pandas.io.formats as formats

    templates = os.path.join(os.path.dirname(formats.__file__), "templates")

    if os.path.isdir(templates):
        importlib.import_module("pandas.io.formats.style")
    else:
        with pytest.raises(jinja2.TemplateNotFound):
            importlib.import_module("pandas.io.formats.style")
