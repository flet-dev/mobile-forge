"""Smoke test for the <package> recipe.

This file is shipped alongside the recipe's meta.yaml. It is NOT executed
during `forge` builds (the cross-compiled wheel can't load on the build
machine). It runs on the target device when the package is loaded by a
test harness.

Convention in mobile-forge:
- Bare `def test_*()` functions, no pytest fixtures, no `unittest.TestCase`
  (both work, but bare functions are the dominant style across recipes/)
- EVERY test function has a docstring — one line saying what it proves
- NO version-assertion tests (`assert pkg.__version__ == ...`) — they add
  nothing over the pinned install and break on every version bump
- One or two tests is enough — this is a smoke test, not a full coverage suite
- Keep tests deterministic and network-free (fixed seeds; no downloads; asset
  files only if tiny and shipped in the recipe's tests/ dir)
- Test-only deps (e.g. numpy for a package that doesn't require it) go in
  tests/requirements.txt — one PEP 508 spec per line

Replace <package> with the import name (NOT the PyPI name — these can differ).
"""


def test_basic():
    """Confirm the wheel loads and the main module is importable.

    The single most useful test — proves the .so / extension module
    cross-compiled correctly and all runtime deps (libc++_shared.so on Android,
    libopenssl, etc.) resolve at load time.
    """
    import <package>

    # Replace with a 1-2 line check that exercises the C-extension path.
    # Examples:
    #   - construct the main type and verify a simple attribute
    #   - do a basic encode/decode round-trip
    #   - call the function the package is named after
    assert hasattr(<package>, "<some_attribute_or_function>")


# Optional: a second test that exercises a specific code path you want to
# verify cross-compiles correctly. Common patterns:
#   - For Rust packages: instantiate a PyO3 class and call a method
#   - For C++ extensions: trigger the C++ path (e.g., float formatting via
#     bundled double-conversion library)
#   - For native-lib consumers: do something that exercises the linked library
#
# def test_<specific_path>():
#     import <package>
#     # ... exercise the path ...
#     assert ...
