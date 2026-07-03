def test_basic():
    """time-machine's `travel()` is implemented as a C extension — it
    patches `time.time()`, `datetime.now()`, etc. at the CPython level."""
    import datetime

    import time_machine

    with time_machine.travel("2020-04-12 12:00:00+00:00", tick=False):
        now = datetime.datetime.now(datetime.timezone.utc)
        assert now.year == 2020
        assert now.month == 4
        assert now.day == 12
        assert now.hour == 12

    # Outside the `with`, time is back to the real wall clock.
    real_year = datetime.datetime.now().year
    assert real_year != 2020 or datetime.datetime.now().day != 12
