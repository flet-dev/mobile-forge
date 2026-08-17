# polars sales rollup

A slider sets how many orders to invent — 50 000 to a million. Each release joins them to a
ten-row product catalogue, keeps the ones placed during opening hours and totals revenue per
category, then shows the result and how long it took.

What it demonstrates:

- **A whole pipeline as one plan** — [`lazy()`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.lazy.html),
  a join, a filter, [`group_by(...).agg(...)`](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.group_by.html),
  a sort, and one [`collect()`](https://docs.pola.rs/api/python/stable/reference/lazyframe/api/polars.LazyFrame.collect.html)
  at the end. The filter is written *after* the join and still runs before it: polars pushes
  predicates down and drops the columns the aggregation never reads, so the join sees a
  smaller table than the code describes. Print
  [`.explain()`](https://docs.pola.rs/api/python/stable/reference/lazyframe/api/polars.LazyFrame.explain.html)
  on the pipeline to watch it happen.
- **How many cores you actually get** — the header line reports
  [`thread_pool_size()`](https://docs.pola.rs/api/python/stable/reference/api/polars.thread_pool_size.html),
  the size of the rayon pool the aggregation runs on. On a phone it is the core count, not 1.
- **Compute off the UI thread** — the run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  slider disabled and a spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a background
  thread needs. `collect()` is parallel inside, but it still blocks the thread that calls it.
- **Generating data with expressions instead of Python** — the order book is built from
  [`int_range`](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.int_range.html)
  and arithmetic, so a million rows appear in milliseconds. Building the same rows as Python
  lists would take longer than the query being measured.

The work is triggered by the slider's `on_change_end`, not `on_change`, so dragging across the
range runs the pipeline once rather than twenty times.

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

`pyproject.toml` limits the Android build to `arm64-v8a` and `x86_64`. polars publishes no
32-bit-ARM wheel, so leaving `armeabi-v7a` in the list fails the build.
