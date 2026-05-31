def test_c_loader_dumper_loaded():
    """ruamel.yaml.clib is the C accelerator for ruamel.yaml. The
    CSafeDumper / CSafeLoader classes are exposed only when the C lib
    actually loaded — otherwise the module re-exports None."""
    from ruamel.yaml.cyaml import CSafeDumper, CSafeLoader

    assert CSafeDumper is not None, "CSafeDumper missing — clib didn't load"
    assert CSafeLoader is not None, "CSafeLoader missing — clib didn't load"


def test_roundtrip_through_ruamel():
    """End-to-end: ruamel.yaml uses the C lib by default if it loaded.
    Round-trip a doc to confirm key+value survival."""
    from io import StringIO

    from ruamel.yaml import YAML

    yaml = YAML(typ="safe", pure=False)  # `pure=False` → use C lib
    data = {"alpha": 1, "beta": 2, "gamma": 3}
    out = StringIO()
    yaml.dump(data, out)
    text = out.getvalue()
    assert "alpha" in text and "gamma" in text
    parsed = yaml.load(text)
    assert parsed == data
