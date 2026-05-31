def test_basic():
    """Round-trip a small document through PyYAML's C-loader and C-dumper."""
    import yaml

    doc = {
        "name": "mobile-forge",
        "components": ["recipes", "tests", "ci"],
        "android": {"api": 24, "abi": ["arm64-v8a", "x86_64"]},
        "iOS": {"min": "13.0"},
    }
    text = yaml.safe_dump(doc, sort_keys=True)
    assert yaml.safe_load(text) == doc


def test_c_extension():
    """The C accelerator (_yaml) is what this recipe primarily exists for.

    PyYAML exposes `CSafeDumper`/`CSafeLoader` only when the `_yaml` C
    extension successfully imports — otherwise they're simply absent
    from the `yaml` package namespace (no exception, no None — just
    missing names). Probe by importing `_yaml` and checking it carries
    the Cython-emitted `CParser` class. That assertion fires both when
    the .so was never shipped AND when libyaml fails to load at import
    time on the device."""
    import _yaml

    assert hasattr(_yaml, "CParser"), (
        "PyYAML's _yaml C extension loaded but is missing CParser — "
        "libyaml probably failed to load at import time"
    )
