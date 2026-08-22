# pandas orders summary

600 rows of synthetic orders live as a CSV in the app's own storage. Pick **Region**,
**Product** or **Month** and [pandas](https://pandas.pydata.org/) groups the file and
shows order counts, units and revenue per group, biggest first.

What it demonstrates:

- **A CSV that belongs to the app** — the file is written on first launch with
  [`to_csv`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_csv.html)
  into [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  and read back with
  [`read_csv`](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html) on every
  launch after that. Its full path is printed at the bottom of the screen, which is the
  quickest way to see where app storage actually is on the device you are holding.
- **A named aggregation** —
  [`groupby(...).agg(orders=..., units=..., revenue=...)`](https://pandas.pydata.org/docs/reference/api/pandas.NamedAgg.html)
  produces three differently-aggregated columns in one pass, then `sort_values` orders
  them and
  [`reset_index`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.reset_index.html)
  brings the group label back off the index. The result is turned into a
  [`DataTable`](https://flet.dev/docs/controls/datatable/) through `to_dict("records")` —
  a list of plain dicts is the least awkward bridge from a frame to Flet controls, and it
  is all the UI code ever sees: the pandas work lives in `orders.py`, and `main.py` does
  not import pandas at all.
- **Compute off the UI thread** — the first read and every re-group run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  a spinner up, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a
  background thread needs.
- **Which string backend you got** — the header line reports `dtype.storage` for the
  column being grouped. It says `python` here, because the app does not depend on
  `pyarrow`; install `pyarrow` and the same line says `pyarrow`. Both give identical
  answers.
- **Dropping the test suite you will never run** — `pyproject.toml` adds
  [`[tool.flet.cleanup] package_files`](https://flet.dev/docs/publish/#compilation-and-cleanup)
  for `pandas/tests`, which Flet's default cleanup keeps. It is the largest thing in the
  wheel that an app never imports.

The dates are turned into month labels with
[`.dt.strftime`](https://pandas.pydata.org/docs/reference/api/pandas.Series.dt.strftime.html)
rather than a time-zone conversion on purpose — named IANA zones need the `tzdata` package
that this app deliberately does not carry.

Delete the app's data (or the CSV) and the next launch regenerates the same 600 rows: the
generator is seeded, so the totals on your screen should match anyone else's.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
