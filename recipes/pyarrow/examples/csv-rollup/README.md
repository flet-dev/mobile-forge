# pyarrow csv rollup

A slider sets how many orders to invent — 10 000 to 100 000. **Roll up** writes them to a CSV
in app storage, reads the file straight back with
[Arrow's own CSV reader](https://arrow.apache.org/docs/python/csv.html), totals it per city,
and reports how long each half took.

What it demonstrates:

- **A group-by without Acero.** `table.group_by(...).aggregate(...)` is the obvious call and it
  raises on these wheels, so `roll_up()` does the same job with the kernels that *are* here:
  [`pc.unique`](https://arrow.apache.org/docs/python/generated/pyarrow.compute.unique.html)
  for the distinct keys, then a boolean mask per key and
  [`pc.sum`](https://arrow.apache.org/docs/python/generated/pyarrow.compute.sum.html) /
  [`pc.mean`](https://arrow.apache.org/docs/python/generated/pyarrow.compute.mean.html)
  over the rows it selects. The mask matters: handing
  [`Table.filter`](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html#pyarrow.Table.filter)
  an [expression](https://arrow.apache.org/docs/python/generated/pyarrow.compute.field.html)
  instead would route it through Acero too.
- **A file the app owns, read by native code.**
  [`csv.write_csv`](https://arrow.apache.org/docs/python/generated/pyarrow.csv.write_csv.html)
  and
  [`csv.read_csv`](https://arrow.apache.org/docs/python/generated/pyarrow.csv.read_csv.html)
  take an ordinary path under
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data);
  the footer shows the size of the file on disk against the size of the Arrow table it parsed
  into, and the parse and the group-by timed separately.
- **What this build actually contains.** The header prints how many
  [compute functions](https://arrow.apache.org/docs/python/api/compute.html) are registered and
  whether the gzip codec is there — `yes` on iOS, `no` on Android, which is the one functional
  difference between the two platforms.
- **Compute off the UI thread** — the round trip runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button disabled and a spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a background
  thread needs.

The row generator is seeded, so the totals come out the same on every install and two devices
can be compared directly. Only the two Arrow steps are timed: inventing the rows in Python
dominates the wall clock of a run and would drown out the numbers worth looking at, which is
also why the spinner covers the whole round trip and not just the parse.

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

`pyproject.toml` limits the Android build to `arm64-v8a` and `x86_64`. There is no 32-bit-ARM
pyarrow wheel, so leaving `armeabi-v7a` in the default list fails the build.
