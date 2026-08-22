# msgspec three ways

One screen answering "what does decoding *with a type* actually cost, and what does it catch?"
on the device in front of you. A slider picks the document size — 100 to 5,000 records of a
deterministic, order-shaped payload. Let it go and the app hands the identical `bytes` object to
three decoders in turn — `json.loads`, `orjson.loads` and
`msgspec.json.decode(blob, type=list[Order])` — and fills a table with the per-call cost, the
ratio against the standard library, and whether that decoder checked anything at all. Below
that, a panel feeds all three a record with one wrong field and prints what each did with it.

What it demonstrates:

- **What validating actually costs, on this hardware.** Two of the three columns are parsing and
  nothing more; the third parses *and* checks every field against `Order` in the same pass, and
  the `checks` column says which is which. Whether the validating one still comes out fastest on
  a phone is what the table is for.
- **Single-pass validation, as two millisecond figures rather than a claim.** The same document
  is corrupted twice — the bad field at record 1 and at the last record — and both are timed
  beside the fully valid decode. The first stops in about a microsecond because msgspec never
  built the rest; the second costs a full pass. The `ValidationError` is printed underneath with
  its `` - at `$[1].qty` `` path, so the *reason* sits next to the *cost*.
- **Two cross-checks, so a wrong answer is visible rather than merely plausible.** msgspec's
  re-encoded `Struct`s are compared byte for byte against orjson's re-encoded dicts, printing
  `identical bytes` or `DIFFERENT BYTES` — without it, a faster column could just as well be a
  column that decoded less. And the MessagePack bytes the size line calls smaller are decoded
  back through the same `Order` and compared against the JSON decode: "22% smaller" is a claim
  any encoder can satisfy by dropping something, and that line says it did not.
- **What silence costs you.** The panel walks three malformed records. Two are rejections —
  `qty` sent as `"NOPE"` and `price` sent as `null`, each printed with the located message
  msgspec produced. The third is the one to read twice: an extra `"discount"` field is
  **accepted** and silently dropped, where `orjson` and `json` both hand it back. Putting
  `forbid_unknown_fields=True` on the `Struct` is what turns that into an error.
- **Whether TOML and YAML work here, asked rather than assumed.** The second header line calls
  all four shipped codecs and prints `ok` or the exception type. `toml decode` is the interesting
  one: it works with nothing installed beyond msgspec *if* this runtime has the stdlib `tomllib`,
  which is a property of Flet's Python build rather than of the wheel. `yaml decode` reports
  `ImportError` on a device on purpose — this example does not depend on PyYAML. A desktop
  `flet run` may print `ok` instead, because `flet-cli` in the `dev` group drags PyYAML in
  through `cookiecutter`, and the `dev` group is not packaged into the app.
- **Where the native module came from, on this device.** The first header line carries
  `msgspec.__version__`, the Python version, `page.platform.value` and the basename of
  `msgspec._core`'s origin, read through `__file__` first and `__spec__.origin` second, because
  Flet relocates native extensions out of site-packages and which attribute survives varies by
  platform and by package.
- **Compute off the UI thread.** The run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. Its body is wrapped in `try/except`, because `run_thread` discards whatever a worker
  raises. The thread buys a handler that returns immediately and nothing else: msgspec holds the
  GIL for the whole of a decode, so there is no parallelism to win.

Every decode goes through a helper that catches broad `Exception`, because these libraries raise
plain `ValueError` and `UnicodeDecodeError` subclasses rather than anything library-shaped, and
an unhandled exception in a Flet event handler crashes the session. The document is generated
from the slider position with no randomness, so the same position produces the same bytes on
every install and two devices can be compared directly. Nothing is downloaded, nothing is
written to disk and no asset is bundled.

`orjson` is here as the honest comparison rather than as something the pattern needs: it is the
fastest parse-only option on this index, so beating it is the claim worth testing, and its column
in the malformed panel is what makes "parsed successfully, wrong type, no complaint" concrete.
Delete its rows and its `import` and the screen still answers every question above — but delete
the dependency without editing the code and the app dies on `import orjson` before Flet draws
anything.

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

`pyproject.toml` pins `flet`, `msgspec` and `orjson`, which is the combination that was verified.
`requires-python` stays at `>=3.10` because all three pins declare exactly that floor, so every
split uv resolves for is satisfiable.
