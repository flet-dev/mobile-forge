# ormsgpack pack-bench

The same list of sensor records is packed and unpacked by `ormsgpack` and by `msgpack`, on
the device, and the table reports what each one cost and how many bytes each produced.
Below it, eight values are packed and unpacked again by `ormsgpack` alone, so you can read
off which of them changed type on the way through.

What it demonstrates:

- **That the two libraries write the same bytes.**
  [`ormsgpack.packb`](https://ormsgpack.readthedocs.io/en/latest/api.html#ormsgpack.packb)
  and [`msgpack.packb`](https://msgpack-python.readthedocs.io/en/latest/api.html#msgpack.packb)
  produced byte-identical output for every payload tried while writing this, which is what
  the `identical` line checks on your device. The choice is never about wire size, and a
  file written by one still reads with the other.
- **Where the Rust implementation actually wins.** Packing runs at roughly three times
  msgpack's speed on this payload; unpacking is much closer, and on a flat list of short
  strings msgpack has been measured *ahead*. The ratios under the table are this device's.
- **Types msgpack refuses, and the price of taking them.** A
  [dataclass](https://ormsgpack.readthedocs.io/en/latest/types.html#dataclass), a
  [`UUID`](https://ormsgpack.readthedocs.io/en/latest/types.html#uuid) and a
  [`datetime`](https://ormsgpack.readthedocs.io/en/latest/types.html#datetime) all pack with
  no `default=` hook — into msgpack's own types. The cards show the dataclass coming back a
  `dict` and the UUID a `str`, because nothing in the bytes records what they were.
- **The one datetime flag worth knowing.**
  [`OPT_DATETIME_AS_TIMESTAMP_EXT`](https://ormsgpack.readthedocs.io/en/latest/api.html#ormsgpack.OPT_DATETIME_AS_TIMESTAMP_EXT)
  writes the MessagePack
  [timestamp extension](https://github.com/msgpack/msgpack/blob/master/spec.md#timestamp-extension-type)
  in 10 bytes instead of 34 and returns a real `datetime` — in UTC, with the `+05:30` gone,
  because that extension stores an instant and not an offset. It has to be set on `unpackb`
  too, which is why the example masks the flags rather than passing the same number twice.
- **Compute off the UI thread.** The benchmark runs inside
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, and the worker ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. The [`SegmentedButton`](https://flet.dev/docs/controls/segmentedbutton/)
  reports its
  [`selected`](https://flet.dev/docs/controls/segmentedbutton/#flet.SegmentedButton.selected)
  value as a list, so the handler reads `selected[0]`.

The `tuple key` card is the exception that explains all the others: a tuple in a list comes
back a list, but a tuple used as a dict *key* comes back a tuple, because a key has to stay
hashable and the decoder has nowhere else to put it.

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
