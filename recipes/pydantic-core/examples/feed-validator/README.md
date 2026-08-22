# pydantic feed validator

A slider sets how many order records to invent — 200 to 2000. Let it go and the app hands the
whole feed to pydantic as raw JSON bytes in one call, keeps the records that fit the schema,
totals the survivors, and reports every record that did not fit with the exact path to the
field that broke it.

Six records are sabotaged on purpose, one per kind of failure, which is what makes the
rejection table checkable: you can point at `214.lines.0.qty / greater_than / Input should be
greater than 0 / 0` and match it to the record the generator broke.

What it demonstrates:

- **Raw bytes to typed objects in one call** —
  [`TypeAdapter(list[Order]).validate_json(payload)`](https://docs.pydantic.dev/latest/api/type_adapter/#pydantic.type_adapter.TypeAdapter.validate_json)
  parses and validates in the same pass, with no intermediate dicts. The schema is four
  fields and a nested list, and it is the only place in the app that says what "valid" means:
  a [`Literal`](https://docs.pydantic.dev/latest/api/standard_library_types/#literals) for the
  currency, [`AwareDatetime`](https://docs.pydantic.dev/latest/api/types/#pydantic.types.AwareDatetime)
  for the timestamp, and [`Field`](https://docs.pydantic.dev/latest/api/fields/#pydantic.fields.Field)
  constraints on the line items.
- **Recovering from a rejection instead of losing the batch.** One bad record fails the whole
  list, so `validate_feed()` reads the leading index out of each error's `loc`, drops those
  records, and re-runs
  [`validate_python`](https://docs.pydantic.dev/latest/api/type_adapter/#pydantic.type_adapter.TypeAdapter.validate_python)
  over the rest. The second pass has to start from parsed records rather than from the bytes,
  which is what recovering costs over rejecting.
- **A rejection table you can read on a phone** — built from
  [`errors(include_url=False)`](https://docs.pydantic.dev/latest/api/pydantic_core/#pydantic_core.ValidationError.errors),
  showing `loc`, `type`, `msg` and the offending `input`. Without `include_url=False` every
  row would carry a link to errors.pydantic.dev, which is dead weight on a device.
- **`Decimal` that stays exact.** Prices travel as JSON strings and land in
  `decimal.Decimal`, so the revenue rollup adds cents rather than floats. The header line
  reports `decimal.__libmpdec_version__`, the C accelerator that arithmetic runs on.
- **How the extension got loaded.** Also in the header: the file `pydantic_core` was imported
  from, plus pydantic-core's own `build_info` — the Rust profile the wheel was compiled with.
  On desktop that file is the wheel's tagged `.so`; on a phone it is not, because Flet moves
  native extensions out of site-packages — into the APK's `jniLibs` on Android, into a signed
  framework on iOS — and leaves a marker at the import path. So read it as which file the
  import system resolved, not as the wheel tag.
- **Two paths to the same objects, timed on this device.** `validate_json` against
  `json.loads` + `validate_python` over identical bytes, best of three each. The survivors are
  re-serialised with
  [`dump_json`](https://docs.pydantic.dev/latest/api/type_adapter/#pydantic.type_adapter.TypeAdapter.dump_json)
  to produce those bytes, so the comparison runs on a payload that validates cleanly instead
  of on the error path.
- **The parser's own nesting limit, measured rather than quoted.** `deepest_nesting()`
  binary-searches how deeply nested a JSON document `validate_json` will accept. One level
  past it the failure is reported as
  [`json_invalid`](https://docs.pydantic.dev/latest/errors/validation_errors/#json_invalid)
  — "recursion limit exceeded" — so it reads like malformed input rather than a limit.
- **Compute off the UI thread** — the run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. The body is wrapped in `try/except` because `run_thread` discards anything a worker
  raises.

The generator is seeded, so the records, the six rejections and the totals come out the same on
every install and two devices can be compared directly. It builds plain dicts and dumps them to
bytes rather than starting from models, because the point is a feed the app did not write.

`src/feed.py` owns the models, the generator, the salvage pass and the timing harness, and
hands back plain values; `src/main.py` is the screen and its wiring.

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

`pyproject.toml` pins `pydantic` and deliberately does not pin `pydantic-core`: pydantic pins
its own core with `==`, so pinning both is a resolution conflict that fails the build. The pin
here resolves `pydantic-core 2.46.4`, one release behind the version the recipe builds, because
that newer core is named only by a pydantic pre-release. See the
[recipe README](../../README.md).
