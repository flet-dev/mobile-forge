# pyogrio vector I/O

A layer of synthetic weather stations — a point each, four attributes and a coordinate
reference system — written into app storage through GDAL's OGR and read straight back.
Choose GeoJSON or ESRI Shapefile, drag the slider for how many stations, and the table
reports which field names survived, what the coordinates came back as, how long each half
took and what landed on disk. Below it sits the driver table this GDAL registered.

What it demonstrates:

- **A vector round trip with no dataframe anywhere.** `pyogrio.raw.write` takes geometry as
  an array of [WKB](https://libgeos.org/specifications/wkb/) byte strings and one numpy
  array per attribute column, and `pyogrio.raw.read` hands the same shapes back — the layer
  underneath
  [`read_dataframe`](https://pyogrio.readthedocs.io/en/latest/api.html#pyogrio.read_dataframe),
  reachable with numpy alone.
- **A format is a schema, not a container.** Written identically, the two drivers disagree:
  the Shapefile truncates `station_name`, `reading_count` and `elevation_m` to ten
  characters — DBF's limit, and it says so in a `RuntimeWarning` — while GeoJSON keeps every
  name and silently narrows the 64-bit integer column to `int32`. No attribute *value* is
  lost either way.
- **A CRS written as a PROJ string rather than an EPSG code.** Naming a projection by
  authority code is a lookup in `proj.db`, which these wheels do not carry. GeoJSON reads
  the layer back as `EPSG:4326` from the driver's own compiled-in WKT; the Shapefile's
  `.prj` comes back an unnamed `GEOGCS`.
- **What the driver table proves, and what it does not.**
  [`list_drivers()`](https://pyogrio.readthedocs.io/en/latest/api.html#pyogrio.list_drivers)
  reads the registry through pyogrio's `_ogr` extension; reads and writes happen in `_io`.
  Those are two views of one library on Android and two separate libraries on iOS, which is
  why the app shows the registry and the round trip side by side.
- **Compute off the UI thread.** Each run goes through
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end), so
  one drag writes one layer. The worker body is wrapped, because a failure here is a
  `DataSourceError` rather than a crash and belongs in the status line.

Switch drivers and watch the coordinate residual: on a desktop run of 500 stations it is
exactly 0 through the Shapefile and 8.9e-16 through GeoJSON. The Shapefile stores the eight
bytes of each double; GeoJSON stores the digits and parses them back.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS and iOS-Simulator — both build and start, and then every read and write
# fails with DataSourceError. The driver table still fills in, because that is
# the half that works. See ../../README.md#install
uv run flet build ipa
uv run flet build ios-simulator
```
