"""Smoke test for the pyerfa recipe.

pyerfa's import name is `erfa` (NOT `pyerfa`). erfa/__init__.py does
`from .core import *` and `from .ufunc import (...)` at import, so importing
`erfa` forces the single Py_LIMITED_API C extension (erfa/ufunc.abi3.so) to
dlopen — proving the vendored liberfa static C and the numpy-ufunc glue
cross-compiled and load on-device.
"""


def test_import_erfa():
    import erfa

    assert erfa.__version__
    assert hasattr(erfa, "ufunc")


def test_cal2jd_roundtrip():
    """Exercise the ERFA C path end-to-end through the numpy ufunc: convert a
    Gregorian calendar date to a two-part Julian Date. 2000-01-01 ->
    JD 2451544.5 (MJD zero-point 2400000.5 + MJD 51544.0). Proves the compiled
    ERFA routines actually run and numpy ufunc dispatch works on the device."""
    import erfa

    djm0, djm = erfa.cal2jd(2000, 1, 1)
    assert abs((djm0 + djm) - 2451544.5) < 1e-6
