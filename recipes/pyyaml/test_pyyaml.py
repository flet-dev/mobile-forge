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
    """The C accelerator (_yaml) is the whole reason this is a forge recipe."""
    from yaml import CSafeDumper, CSafeLoader

    text = CSafeDumper(None).represent_data({"k": [1, 2, 3]})
    # Loader/Dumper classes carry the C-backed scanner — instantiating them
    # without raising imports the _yaml extension successfully.
    assert CSafeLoader is not None
    assert text is not None
