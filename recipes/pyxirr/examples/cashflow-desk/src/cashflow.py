import time

import pyxirr

# The market spelling of the convention, not the DayCount attribute name:
# day_count="ACT_365F" raises ValueError, day_count="ACT/365F" is accepted.
DAY_COUNT = "ACT/365F"

# The rate window the profile is sampled across. The guess slider uses the same
# window, so a guess can be read against the crossings it is being aimed at.
RATE_MIN, RATE_MAX = -0.9, 3.0
CELLS = 48

VERSION = f"pyxirr {pyxirr.__version__} · {DAY_COUNT}"

# Dates are plain ISO strings. pyxirr parses them in Rust, so nothing here
# imports datetime -- but the padding is not optional: "2022-3-14" is rejected.
SCHEDULES = {
    "Rental flat": (
        ("2022-03-14", -240000.0),
        ("2022-09-30", 8400.0),
        ("2023-03-31", 8400.0),
        ("2023-09-29", 8600.0),
        ("2024-04-02", 8600.0),
        ("2024-09-30", 8800.0),
        ("2025-06-13", 274000.0),
    ),
    "Mine site": (
        ("2020-01-02", -1000000.0),
        ("2021-01-04", 4100000.0),
        ("2022-01-03", -4100000.0),
        ("2023-01-03", 1000000.0),
    ),
    "Research grant": (
        ("2024-02-01", 5000.0),
        ("2024-08-01", 5000.0),
        ("2025-02-03", 5000.0),
    ),
    "Clawback": (
        ("2024-01-02", -100000.0),
        ("2025-01-02", 300000.0),
        ("2026-01-02", -300000.0),
    ),
}


def payments(name):
    """Split a schedule into the two parallel sequences xirr and xnpv take."""
    dates, amounts = zip(*SCHEDULES[name])
    return list(dates), list(amounts)


def profile(dates, amounts):
    """Sample XNPV across the whole rate window in a single call.

    xnpv broadcasts over an iterable of rates and hands back a list, so the
    entire curve is one trip into Rust rather than one per point. Only the
    sign of each sample is used: a sign change between two neighbours is a
    rate at which the schedule breaks even, which is the definition of an IRR.
    """
    step = (RATE_MAX - RATE_MIN) / (CELLS - 1)
    rates = [RATE_MIN + i * step for i in range(CELLS)]
    return rates, pyxirr.xnpv(rates, dates, amounts, day_count=DAY_COUNT)


def roots(dates, amounts, rates, curve):
    """Find every rate at which this schedule breaks even, not only one of them.

    xirr returns a single root and `guess` is what picks it. Upstream's own way
    to enumerate them is to run the *NPV curve* through zero_crossing_points --
    the same helper the report points at the amounts, aimed at the profile
    instead -- and restart xirr from inside each bracket it hands back.

    The two uses answer different questions, and that is the whole lesson.
    Sign changes in the amounts bound how many roots can exist; sign changes in
    the curve are where they actually are. The clawback schedule changes sign
    twice and has none at all.

    silent=True because a schedule with no sign change raises rather than
    returning None, and a bracket found by eye is not a promise of convergence.
    """
    found = set()
    for index in pyxirr.zero_crossing_points(curve):
        rate = pyxirr.xirr(
            dates, amounts, guess=rates[index], day_count=DAY_COUNT, silent=True
        )
        if rate is not None:
            # Roots reached from neighbouring brackets differ in the last few
            # bits; rounding makes them one entry, and the +0.0 folds the -0.0
            # that a root at exactly zero comes back as.
            found.add(round(rate, 6) + 0.0)
    return sorted(found)


def analyse(name, guess):
    """Solve one schedule and report enough to judge whether to believe it.

    XIRR is *defined* as the rate at which XNPV is zero, so the answer and its
    residual XNPV belong on screen together. On the rental schedule that
    residual is around 4e-4 against the 556,800 the schedule moves -- a
    root-finder's zero, not an algebraic one.

    pyxirr separates three kinds of not-an-answer, and they need different
    handling:

    * a schedule with no sign change raises InvalidPaymentsError, which is the
      one failure `silent=True` converts into None;
    * a curve that never reaches zero returns None *without* raising, silent
      or not -- non-convergence is a value here, not an exception;
    * a malformed date string raises ValueError, which `silent=True` does not
      suppress either.

    Returns the rate (or None), the message if it raised, the residual, the
    gross amount moved, the sign changes and whether there is exactly one of
    them, all roots, the sampled profile, the profile cell the guess started
    in, and the microseconds the single solve took.
    """
    dates, amounts = payments(name)
    error = None
    started = time.perf_counter()
    try:
        rate = pyxirr.xirr(dates, amounts, guess=guess, day_count=DAY_COUNT)
    except pyxirr.InvalidPaymentsError as exc:
        rate, error = None, str(exc)
    micros = (time.perf_counter() - started) * 1e6

    residual = None
    if rate is not None:
        residual = pyxirr.xnpv(rate, dates, amounts, day_count=DAY_COUNT)

    rates, curve = profile(dates, amounts)
    return {
        "rate": rate,
        "error": error,
        "residual": residual,
        "gross": sum(abs(a) for a in amounts),
        "crossings": pyxirr.zero_crossing_points(amounts),
        "conventional": pyxirr.is_conventional_cash_flow(amounts),
        "roots": roots(dates, amounts, rates, curve),
        "profile": (rates, curve),
        "near": min(range(CELLS), key=lambda i: abs(rates[i] - guess)),
        "micros": micros,
    }
