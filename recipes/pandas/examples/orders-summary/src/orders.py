import os
import random
from datetime import date, timedelta

import pandas as pd

# FLET_APP_STORAGE_DATA is durable, app-private storage. Flet also makes it the working
# directory on device, so a bare "orders.csv" would land there too — this spells it out.
CSV_PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.csv")

ROWS = 600
REGIONS = ("North", "South", "East", "West")
PRODUCTS = ("Anvil", "Rocket", "Magnet", "Rope", "Paint")

# Column to group by, and the heading to put over it.
GROUPINGS = {"region": "Region", "product": "Product", "month": "Month"}

VERSION = f"pandas {pd.__version__}"

_frame = None


def write_sample_csv():
    """Write the app's own CSV on first launch, so nothing has to be bundled or fetched."""
    rng = random.Random(20260816)  # seeded, so every install shows the same totals
    start = date(2026, 1, 1)
    pd.DataFrame(
        [
            {
                "date": start + timedelta(days=rng.randrange(180)),
                "region": rng.choice(REGIONS),
                "product": rng.choice(PRODUCTS),
                "units": rng.randrange(1, 25),
                "unit_price": round(rng.uniform(4.0, 90.0), 2),
            }
            for _ in range(ROWS)
        ]
    ).to_csv(CSV_PATH, index=False)


def orders():
    """Return the frame, reading it from app storage the first time and keeping it.

    The sample file is written first when it is missing, so a fresh install has something
    to show and every launch after that is a plain read of a file the app owns. Holding
    the frame here is what makes switching between the three groupings re-group what is
    already in memory rather than re-read the file.
    """
    global _frame
    if _frame is None:
        if not os.path.exists(CSV_PATH):
            write_sample_csv()
        frame = pd.read_csv(CSV_PATH, parse_dates=["date"])
        frame["revenue"] = frame["units"] * frame["unit_price"]
        # strftime rather than a tz conversion: named IANA zones need the tzdata package,
        # which this app deliberately does not depend on.
        frame["month"] = frame["date"].dt.strftime("%Y-%m")
        _frame = frame
    return _frame


def summarise(key):
    """Group the orders by one column into counts, units and revenue, biggest first.

    The three differently-aggregated columns come from a single named aggregation rather
    than three passes. `reset_index` moves the group label off the index, where
    `to_dict("records")` would not see it, and renaming it to a fixed `label` means the
    caller never has to know which column was grouped.

    Returns the rows as plain dicts, how many orders were read, and the storage pandas
    picked for text columns — `python` here, or `pyarrow` when that optional package
    happens to be installed alongside.
    """
    frame = orders()
    summary = (
        frame.groupby(key)
        .agg(
            orders=("units", "size"),
            units=("units", "sum"),
            revenue=("revenue", "sum"),
        )
        .sort_values("revenue", ascending=False)
        .reset_index()
        .rename(columns={key: "label"})
    )
    dtype = frame[key].dtype
    return summary.to_dict("records"), len(frame), getattr(dtype, "storage", str(dtype))
