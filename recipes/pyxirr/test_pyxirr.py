def test_basic():
    """Proves the wheel loads and the Rust solver works: irr() finds the rate
    where npv() == 0, so we check both the known value and the npv round-trip."""
    import pyxirr

    amounts = [-100, 39, 59, 55, 20]
    r = pyxirr.irr(amounts)
    assert abs(r - 0.2809484211599611) < 1e-6
    assert abs(pyxirr.npv(r, amounts)) < 1e-6


def test_xirr():
    """XIRR is the function pyxirr is named after. Exercises date parsing and
    the day-count engine (defaults to ACT_365F) on top of the solver."""
    import pyxirr
    from datetime import date

    dates = [date(2020, 1, 1), date(2021, 1, 1), date(2022, 1, 1)]
    amounts = [-1000, 750, 500]
    rate = pyxirr.xirr(dates, amounts)
    assert abs(rate - 0.17500926461545202) < 1e-4
    assert abs(pyxirr.xnpv(rate, dates, amounts)) < 1e-4
