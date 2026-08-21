# bson store

Sensor readings kept in a file in the app's own storage, written as BSON documents. Each tap
appends one more and the list is read back off disk, newest first. Underneath, a fresh document
is round-tripped field by field: what went in, what came back, whether the two are identical,
and whether `json` would have taken it at all. There is no MongoDB anywhere in this app.

What it demonstrates:

- **A document store that is just a file** —
  [`bson.encode`](https://pymongo.readthedocs.io/en/stable/api/bson/index.html#bson.encode)
  produces a self-delimiting document, so appending one is a single `write` with no header,
  separator or index, and
  [`decode_file_iter`](https://pymongo.readthedocs.io/en/stable/api/bson/index.html#bson.decode_file_iter)
  walks them back one at a time. The file lives in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  and the layout is the one [`mongodump`](https://www.mongodb.com/docs/database-tools/mongodump/)
  writes.
- **The types that make it worth doing** — an
  [`ObjectId`](https://pymongo.readthedocs.io/en/stable/api/bson/objectid.html) minted on the
  phone with no server to ask,
  [`Decimal128`](https://pymongo.readthedocs.io/en/stable/api/bson/decimal128.html) for a
  temperature that must not become a binary float,
  [`Int64`](https://pymongo.readthedocs.io/en/stable/api/bson/int64.html),
  [`Binary`](https://pymongo.readthedocs.io/en/stable/api/bson/binary.html) for a raw payload,
  and a real datetime. Four of the five are a `TypeError` to `json.dumps`.
- **Two round trips that are not exact** — a datetime keeps only whole milliseconds, and a
  generic (subtype 0) `Binary` comes back as plain `bytes`. The `same` column says so rather
  than hiding it, and
  [`CodecOptions(tz_aware=True)`](https://pymongo.readthedocs.io/en/stable/api/bson/codec_options.html)
  is what lets the decoded timestamp be converted for display instead of arriving naive.
- **The C accelerator, with a number attached** —
  [`bson.has_c()`](https://pymongo.readthedocs.io/en/stable/api/bson/index.html#bson.has_c)
  reports whether the compiled encoder is in use, and the throughput line times a thousand
  round trips on the device rather than quoting a desktop figure.
- **Compute off the UI thread, and survive it going wrong** — appends and the benchmark run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button disabled and a spinner up, ending with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. `run_thread` swallows what the worker raises, so the worker sits inside a `finally`
  that always hands the button back — without it, one unreadable store file leaves the app
  spinning for good. A module-level lock keeps two appends from interleaving inside one file,
  and a torn tail costs only the document it tore.

The `same` column is the whole argument. A format that hands back the types it was given is
what turns an ordinary file into a document store — you stop writing conversion code at both
ends, and stop losing an exact decimal to a float on the way through.

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
