"""ruamel.yaml.clib is the standalone C accelerator that ruamel.yaml
imports if present. The recipe ships only `_ruamel_yaml.so` — it does
NOT ship the `ruamel.yaml` Python namespace package itself (that's a
separate pure-Python package on pypi). Even importing `_ruamel_yaml`
directly fails on its own because its Cython init code references the
`ruamel.yaml` namespace.

So the meaningful thing we can verify here is that the recipe actually
shipped the `.so` file at the location ruamel.yaml expects to find it.
End-to-end behavior is exercised when a downstream app installs both
ruamel.yaml.clib AND ruamel.yaml together."""

import importlib.util


def test_so_is_installed():
    """The C extension is named `_ruamel_yaml` and ships at the top
    level of site-packages. `find_spec` does not import — it just
    locates the file, which is exactly what we want."""
    spec = importlib.util.find_spec("_ruamel_yaml")
    assert spec is not None, "ruamel.yaml.clib didn't ship _ruamel_yaml.so"
    assert spec.origin is not None and spec.origin.endswith(
        (".so", ".pyd", ".dylib")
    ), f"expected a compiled extension, got {spec.origin!r}"
