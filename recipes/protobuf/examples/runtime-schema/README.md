# protobuf runtime schema

One screen that answers the two questions a protobuf app on a phone actually has: *is the C
extension the thing doing the work here*, and *what does it buy me over the standard library
on this hardware*. There is no `.proto` file in this project, no generated `_pb2.py` and no
protoc anywhere — the schema (`Reading{id, sensor, celsius, ts, ok}`, `Batch{repeated
Reading}`, plus small helper messages) is described as a `FileDescriptorProto` at import and
compiled by `DescriptorPool.Add`, which is the one route to a schema on a phone that needs no
protoc on any machine, not even the one you build on. A slider picks 500 / 2,000 / 8,000 / 20,000 readings; releasing it
runs one measurement in a background thread and rewrites the table.

What it demonstrates:

- **Which implementation is live, in the first line, in red when it is the wrong one.**
  protobuf silently substitutes a pure-Python implementation when its extension is missing —
  no warning, no exception, every message still round-trips — and it is roughly two orders of
  magnitude slower. The header prints `api_implementation.Type()`,
  `descriptor._USE_C_DESCRIPTORS` and the module that built the message classes, because all
  three flip together and none of them is the same question as "does `google._upb._message`
  import". Proved failable by forcing the fallback: the same screen then reads `python`,
  `False`, `google.protobuf.internal.python_message`, and the ratio column inverts.
- **A schema with no compiler behind it.** `build_schema()` is the whole pattern in about
  fifty lines: fields appended to a `DescriptorProto`, a map field spelled out as its
  `map_entry` message, and proto3 `optional` spelled out as its synthetic one-field oneof. It
  runs once at module scope on purpose — messages from two different pools never compare
  equal, and the default pool refuses a second file under a name it already holds.
- **A comparison that does not cheat.** Four rows against `json.dumps`/`json.loads` on exactly
  the same values: wire bytes, serialise, parse, and parse-plus-read-every-field. That last
  row is the one that licenses the others — upb's parse does not build Python objects, so
  parse alone is ~12x on desktop while parse-plus-read is ~1.6x, and quoting only the first
  would be marketing. Desktop reference at 2,000 readings (CPython 3.14.6, arm64 macOS):
  65,034 B against 149,475 B; serialise 0.044 vs 0.652 ms; parse 0.055 vs 0.648 ms; parse +
  read 0.507 vs 0.805 ms. Under the forced fallback the same three become 3.927, 9.251 and
  9.904 ms — every one of them slower than the standard library.
- **Three independent checks, so a fast wrong answer cannot pass as a fast right one.** Every
  parsed record is compared field by field against the row it came from; the parsed batch is
  re-serialised and its bytes compared with the original blob; and `ByteSize()` is checked
  against the length of what `SerializeToString` produced. The two folds — protobuf's and
  JSON's — are compared as well, so the two timing columns are proven to have read the same
  numbers.
- **Where the data goes on a device.** The batch is also written to
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  as a length-prefixed log through `google.protobuf.proto`, then read straight
  back and counted, so the on-disk framing is exercised rather than assumed. At 2,000 readings
  the log is 63,034 B against the single `Batch` message's 65,034 B — one length byte per
  record instead of a tag and a length.
- **Bytes that are not your message.** Three payloads are fed to a `Reading` — the message
  truncated to half, one byte flipped, and a JSON document — and the panel prints the
  exception each one produced. The middle row is the one to read twice: it is `DecodeError`
  under upb and `UnicodeDecodeError` under the fallback, which is why the helper catches broad
  `Exception` rather than `DecodeError`.
- **Schema drift, both directions.** A record carrying a field the parsing schema has never
  heard of is parsed by the older class: the unknown field is listed as it was kept,
  `(9, b'from-the-future')`, and comes back intact when the newer class reads the older one's
  re-serialised output.
- **The map trap, as two digests side by side.** The same thirty-entry map is serialised
  normally and with `deterministic=True`, and both are hashed. They differ, and relaunching
  the app moves the first one while the second never moves — which is the whole argument
  against hashing, signing or content-addressing a serialised message by default.
- **Where a zero goes.** A plain proto3 scalar set to `0` serialises to `b''`; the same field
  declared `optional` and set to `0` serialises to `b'\x10\x00'` and reports `HasField` true.

The measurement runs in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
with a spinner up, started from the slider's
[`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
gesture is one run, and ends with the explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
needs. Its body is wrapped in `try/except` because `run_thread` discards whatever a worker
raises, and it clears the table on the way out so the previous run's timings cannot sit under
this run's error. The thread buys a handler that returns immediately and nothing else:
protobuf holds the GIL for the whole of a call, as the [recipe
README](../../README.md#threading) measures.

The data is generated in code from the slider position with no randomness, so the same
position produces the same bytes on every install and two devices can be compared directly.
Nothing is downloaded, no asset is bundled, and the only file written is the log in app
storage.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

`pyproject.toml` pins `flet` and `protobuf`, and the `protobuf` pin is not cosmetic here: an
unpinned `protobuf` resolves to upstream's pure-Python `py3-none-any` wheel on every mobile
slice whenever PyPI is ahead of this index, and the app then runs the fallback the header line
warns about. `requires-python` stays at `>=3.10` — both pins declare exactly that floor —
checked the way a consumer meets it, by copying that `pyproject.toml` alone into an empty
directory and running `uv lock` there.
