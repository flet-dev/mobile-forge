def test_dataframe_aggregation():
    """Construct a small DataFrame and aggregate via polars."""
    import polars as pl

    df = pl.DataFrame(
        {
            "category": ["a", "b", "a", "b", "a"],
            "value": [1, 2, 3, 4, 5],
        }
    )

    result = df.group_by("category").agg(pl.col("value").sum()).sort("category")
    rows = result.to_dicts()

    # a: 1+3+5=9, b: 2+4=6
    assert rows[0] == {"category": "a", "value": 9}
    assert rows[1] == {"category": "b", "value": 6}
