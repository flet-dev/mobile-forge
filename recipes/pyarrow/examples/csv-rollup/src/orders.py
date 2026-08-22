import os
import random
import time

import pyarrow as pa
import pyarrow.compute as pc
from pyarrow import csv

CITIES = ("Lagos", "Nairobi", "Cairo", "Accra", "Kigali", "Dakar")
SEED = 20260817

# Flet makes FLET_APP_STORAGE_DATA the working directory on device, so a bare
# "orders.csv" would land here anyway; naming it behaves the same on desktop.
CSV_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.csv")

# The build describing itself: how many compute functions this Arrow registers, and
# whether it carries the gzip codec — the one functional difference between the two
# mobile platforms.
BUILD = (
    f"pyarrow {pa.__version__} — {len(pc.list_functions())} compute functions, "
    f"gzip codec {'yes' if pa.Codec.is_available('gzip') else 'no'}"
)


def write_orders(rows):
    """Invent `rows` orders and write them out with Arrow's CSV writer.

    The seed is fixed, so every install produces the same totals and two devices can
    be compared against each other directly.
    """
    rng = random.Random(SEED)
    table = pa.table(
        {
            "city": [rng.choice(CITIES) for _ in range(rows)],
            "amount": [round(rng.uniform(5.0, 500.0), 2) for _ in range(rows)],
        }
    )
    csv.write_csv(table, CSV_PATH)


def roll_up(table):
    """Count, total and average `amount` per city, largest total first.

    `table.group_by(...).aggregate(...)` is the call you would reach for, and it
    raises here: grouped aggregation runs on Acero, which these wheels are not built
    with. The kernels themselves are all present, so the grouping is done by hand —
    `pc.unique` for the distinct keys, then one boolean mask per key and the scalar
    aggregates over the rows it selects. Passing a mask is also why the filter is
    spelled `pc.equal(...)` and not `pc.field("city") == city`: an expression would
    send `Table.filter` through Acero as well.
    """
    rows = []
    for city in pc.unique(table["city"]).to_pylist():
        amounts = table.filter(pc.equal(table["city"], city))["amount"]
        rows.append(
            (city, len(amounts), pc.sum(amounts).as_py(), pc.mean(amounts).as_py())
        )
    return sorted(rows, key=lambda entry: entry[2], reverse=True)


def round_trip(rows):
    """Write `rows` orders to app storage, parse them back, and total them per city.

    Returns plain values for the UI: the per-city rows, the totals across all cities,
    the size of the file on disk against the size of the Arrow table it parsed into,
    and the two timings worth looking at. Only Arrow's own work is timed — inventing
    the rows in Python dominates the wall clock of a run and would drown out both
    figures.
    """
    write_orders(rows)

    started = time.perf_counter()
    table = csv.read_csv(CSV_PATH)
    parse_ms = (time.perf_counter() - started) * 1000.0

    started = time.perf_counter()
    totals = roll_up(table)
    group_ms = (time.perf_counter() - started) * 1000.0

    return {
        "totals": totals,
        "rows": table.num_rows,
        "total": pc.sum(table["amount"]).as_py(),
        "csv_mb": os.path.getsize(CSV_PATH) / 1e6,
        "arrow_mb": table.nbytes / 1e6,
        "parse_ms": parse_ms,
        "group_ms": group_ms,
    }
