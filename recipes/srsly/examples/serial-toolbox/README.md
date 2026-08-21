# srsly serial toolbox

One record set, sent through every serialiser [`srsly`](https://github.com/explosion/srsly)
carries, on the device you are holding. The table reports the size each format produced, how
long the encode and decode took, and whether the object that came back still compares equal to
the one that went in; pick 200, 1000 or 2000 records to see which of those numbers scale and
which do not. Below it, the same records go to disk through the file API, and two panels show
what is actually doing the work.

What it demonstrates:

- **One API, five formats.**
  [`srsly.json_dumps`](https://github.com/explosion/srsly#function-srslyjson_dumps),
  [`msgpack_dumps`](https://github.com/explosion/srsly#function-srslymsgpack_dumps),
  [`pickle_dumps`](https://github.com/explosion/srsly#function-srslypickle_dumps) and
  [`yaml_dumps`](https://github.com/explosion/srsly#function-srslyyaml_dumps) take the same
  argument and each has a matching `*_loads`, so the app loops over a table of pairs and treats
  the choice of format as data. The fifth is file-only:
  [`write_jsonl`](https://github.com/explosion/srsly#function-srslywrite_jsonl) and its gzip
  twin write into
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  and are read straight back, one call each way.
- **The "same" column is the point.** Every format brings the records back except JSON,
  because srsly's JSON is [ujson](https://github.com/ultrajson/ultrajson) 1.35 and that
  release writes ten digits after the decimal point and never an exponent. Each record
  carries two floats picked to show both halves of that: `value` is a third plus a seventh,
  so it comes back rounded, and `drift` sits below the tenth decimal place, so JSON writes it
  as `0.0` and loses it outright. At 2000 records, neither field survives in a single one.
- **Two of the four are compiled and two are not.** The *Vendored inside srsly* panel reads
  each module's `__loader__` — `ExtensionFileLoader` means a real extension, and it is worth
  asking for rather than `__file__`, which a native module on Android can lack entirely. The
  panel also carries the version numbers and explains the timings: YAML is a 2019 pure-Python
  [ruamel.yaml](https://yaml.readthedocs.io/) costing hundreds of milliseconds where msgpack
  costs a fraction of one.
- **Two msgpacks in one process.** The app depends on the
  [`msgpack`](https://github.com/msgpack/msgpack-python) wheel too and prints both version
  numbers in its first line. Plain records pack to identical bytes; an `ExtType` built by the
  wrong one of the two silently arrives as a list.
- **Compute off the UI thread** — the round trips run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  picker disabled and a spinner up, the worker body is wrapped so a failure cannot leave the
  controls locked, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs.

The last line under the table is the one to remember: a msgpack read that fails leaves the
cyclic garbage collector switched off for the whole process, because srsly brackets the
unpack with `gc.disable()`/`gc.enable()` and no `try`/`finally`.

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
