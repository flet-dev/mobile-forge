"""Invent an order book and total it per category with the polars lazy API."""

import time

import polars as pl

OPENING_HOURS = (7, 19)
COLUMNS = ("category", "orders", "units", "revenue")

PRODUCTS = pl.DataFrame(
    {
        "product_id": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        "product": [
            "espresso",
            "flat white",
            "croissant",
            "sourdough",
            "orange juice",
            "granola",
            "dish soap",
            "kitchen roll",
            "peas",
            "ice cream",
        ],
        "category": [
            "drinks",
            "drinks",
            "bakery",
            "bakery",
            "drinks",
            "grocery",
            "household",
            "household",
            "frozen",
            "frozen",
        ],
        "unit_price": [2.40, 3.60, 2.80, 4.10, 3.20, 5.50, 1.90, 2.60, 1.40, 4.80],
    }
)

VERSION = f"polars {pl.__version__} — {pl.thread_pool_size()} worker threads"


def _order_book(rows):
    """Build the order book with polars expressions rather than Python lists.

    Every column is derived from the row index by a multiply-and-modulo, so the
    same slider position always produces the same table and a million rows cost
    milliseconds. Filling Python lists instead would dominate the timing this app
    exists to show.
    """
    return pl.DataFrame({"order_id": pl.int_range(rows, eager=True)}).with_columns(
        product_id=pl.col("order_id") * 2654435761 % PRODUCTS.height,
        quantity=pl.col("order_id") * 40503 % 4 + 1,
        hour=pl.col("order_id") * 7919 % 24,
    )


def _rollup(orders):
    """Join the orders to the catalogue and total revenue per category.

    Nothing between `lazy()` and `collect()` runs when it is written: polars
    optimises the whole plan first, which is why the opening-hours filter is
    allowed to sit after the join here — it is pushed underneath it, and the
    columns the aggregation never reads are dropped before either step.
    """
    return (
        orders.lazy()
        .join(PRODUCTS.lazy(), on="product_id")
        .filter(pl.col("hour").is_between(*OPENING_HOURS))
        .with_columns(revenue=pl.col("quantity") * pl.col("unit_price"))
        .group_by("category")
        .agg(
            orders=pl.len(),
            units=pl.col("quantity").sum(),
            revenue=pl.col("revenue").sum(),
        )
        .sort("revenue", descending=True)
        .collect()
    )


def summarise(rows):
    """Generate `rows` orders, roll them up, and return the totals and the time taken.

    The clock covers generation and `collect()` — the two steps that do real work
    — and stops before `to_dicts()`, which only converts the handful of grouped
    rows that survive. Returning dicts rather than the DataFrame keeps polars
    types out of the UI: one plain dict per category, keyed by COLUMNS.
    """
    started = time.perf_counter()
    totals = _rollup(_order_book(rows))
    elapsed = (time.perf_counter() - started) * 1000.0
    return totals.to_dicts(), elapsed
