def test_parse_and_arithmetic():
    """pendulum vendors a Rust-based parser (the recipe's reason for existing).
    Exercising parse() + duration arithmetic touches the native path."""
    import pendulum

    dt = pendulum.parse("2026-05-31T10:30:00Z")
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 31

    dt2 = dt.add(days=2, hours=3)
    assert dt2.day == 2
    assert dt2.month == 6


def test_timezone():
    import pendulum

    paris = pendulum.now("Europe/Paris")
    utc = paris.in_timezone("UTC")
    # Same instant, different wall-clock.
    assert paris.timestamp() == utc.timestamp()
    assert paris.timezone_name == "Europe/Paris"
    assert utc.timezone_name == "UTC"
