def test_xirr():
    """pyxirr is a Rust port of Excel's XIRR financial function. Use a
    canonical worked example from the docstring."""
    from datetime import date

    import pyxirr

    # Cash flows: invest $1000, get $400 back after 6mo, $700 after 1yr.
    dates = [date(2020, 1, 1), date(2020, 7, 1), date(2021, 1, 1)]
    amounts = [-1000.0, 400.0, 700.0]

    rate = pyxirr.xirr(dates, amounts)
    # Annualised IRR ~12.39% — checked against the pyxirr reference.
    # Coarse band so a different rounding strategy in the Rust core
    # doesn't break the test.
    assert 0.10 < rate < 0.15


def test_npv():
    """NPV at 0% is just the sum of the cashflows — the simplest validation
    that the underlying Rust function returns plausible numbers."""
    import pyxirr

    amounts = [-100.0, 60.0, 60.0]
    # rate=0 → sum of amounts
    assert abs(pyxirr.npv(0.0, amounts) - 20.0) < 1e-9
