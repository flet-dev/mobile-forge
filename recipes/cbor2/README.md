# cbor2

[`cbor2`](https://cbor2.readthedocs.io/) encodes and decodes CBOR, the binary format specified
by [RFC 8949](https://www.rfc-editor.org/rfc/rfc8949.html). The API is `dumps`, `loads`, `dump`
and `load`, the same shape as `json`, but the format writes a
[type tag](https://www.rfc-editor.org/rfc/rfc8949.html#name-tagging-of-items) in front of a
value — a datetime is tag 0, a `Decimal` tag 4, an integer too wide for 64 bits tag 2 or 3 — so
a document round-trips as the types it was built from rather than as strings the two ends
agreed about privately. On a phone that suits an on-device record file, a cache of typed
values, or a message whose payload is not all text. It is also the encoding underneath COSE,
WebAuthn and many IoT protocols, so `cbor2` is what reads those — the encoding only; verifying
a signature over the structure it hands back is another library's job.

## Install

Add cbor2 to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "cbor2",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`binary-records`](examples/binary-records) — encodes tagged values and a device journal, and
  puts the CBOR and JSON results side by side.

## Usage in a Flet app

```python
import cbor2
from datetime import datetime, timezone
from decimal import Decimal

blob = cbor2.dumps({"at": datetime.now(timezone.utc), "total": Decimal("19.99")})
doc = cbor2.loads(blob)
doc["at"]     # a datetime
doc["total"]  # a Decimal, exact
```

Nothing was configured to make that work, and no schema travelled with the bytes.

### Storage

`dump` and `load` take a binary file object. Put records the user expects to keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
data_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
with open(os.path.join(data_dir, "journal.cbor"), "wb") as fp:
    cbor2.dump(document, fp)
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you could rebuild and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files. A CBOR file shipped with the app is an asset: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

Each `load` consumes exactly one document and leaves the file at the next byte, so an
append-only log needs no wrapper array and never rewrites what is there. `CBORDecodeEOF` is how
a clean end of file arrives as well as a truncated one, so it is the loop's sentinel:

```python
with open(path, "ab") as fp:
    cbor2.dump(record, fp)

records = []
with open(path, "rb") as fp:
    while True:
        try:
            records.append(cbor2.load(fp))
        except cbor2.CBORDecodeEOF:
            break
```

### Threading

Encoding and decoding is CPU work over Python objects, and holds the GIL for most of it. On
desktop, two encodes of the same 3.0 MB document took the same wall time in two threads as one
after the other, and a busy Python thread alongside a single encode roughly doubled that
encode's duration. Threads will not make this faster — but they will keep the UI thread free.
Move a document big enough to be felt into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch
exceptions inside the worker, and end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). Separate `dumps` and
`loads` calls share no state, but a file object does: two threads calling `load` on the same
open file advance the same position.

### Types and tags

These encode with a tag and decode back to the same type, with no hook and no options:
`datetime` (tag 0, or 1 with `datetime_as_timestamp=True`), `date` (1004), `Decimal` (4),
integers wider than 64 bits (2 and 3), `set` and `frozenset` (258), `Fraction` (30), `UUID`
(37), `ipaddress` addresses and networks (52 for IPv4, 54 for IPv6), a compiled `re.Pattern`
(35) and `complex` (43000). Upstream lists the full set for the
[encoder](https://cbor2.readthedocs.io/en/latest/usage.html#encoder-semantic-tag-support) and
the [decoder](https://cbor2.readthedocs.io/en/latest/usage.html#decoder-support-for-semantic-tags).

Anything else needs a
[`default=`](https://cbor2.readthedocs.io/en/latest/customizing.html#customizing-the-encoder)
hook; without one, `dumps` raises
`CBOREncodeError: cannot encode type <class 'app.Coordinate'>`.
[Tag 27](https://www.iana.org/assignments/cbor-tags/cbor-tags.xhtml) is registered for an object
carried with its type name and constructor arguments, which is the shape to reach for:

```python
def default(encoder, value):
    if isinstance(value, Coordinate):
        encoder.encode(cbor2.CBORTag(27, ["Coordinate", value.lat, value.lon]))
    else:
        raise cbor2.CBOREncodeTypeError(f"cannot serialise {type(value).__name__}")
```

A [`tag_hook=`](https://cbor2.readthedocs.io/en/latest/customizing.html#customizing-the-decoder)
turns it back into a `Coordinate`, and is needed *only* for tags you invented — everything
listed above decodes on its own. A decoder without your hook does not fail: an unknown tag
becomes `CBORTag(27, ('Coordinate', 48.8584, 2.2945))`, so a reader that never heard of your
type still parses the document and can pass the rest of it on.

### Size and speed against json

Measured on desktop (CPython 3.12, macOS on Apple Silicon) with the example's 500-record journal
of timestamps, decimals, UUIDs, sets, serials wider than 64 bits and 16-byte digests:

| | cbor2 | json |
| --- | ---: | ---: |
| bytes | 76 KB | 119 KB |
| encode | 1.7 ms | 1.1 ms |
| decode | 1.1 ms | 0.3 ms, or 0.8 ms with the code that restores the types |

That size ratio held from 50 records to 2000, and
[`string_referencing=True`](https://cbor2.readthedocs.io/en/latest/usage.html#string-references)
took a further fifth off the CBOR. Speed goes the other way: the stdlib `json` module wins on
this document even after you add back the twenty lines that turn its strings into datetimes,
decimals and UUIDs. Choose CBOR for the types and the bytes, not to outrun `json` — the
advantage the table cannot show is that those twenty lines do not exist, so a field cannot be
renamed on one side and not the other.

### App size

Approximately 0.38–0.42 MB compressed and 0.85–1.2 MB unpacked per architecture, nearly all of
it the single `_cbor2` extension, so there is nothing for
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) to remove. An
app bundle, split APKs or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) are
levers worth pulling for other packages rather than for this one.

### Other considerations

A desktop `flet run` uses PyPI's own wheel: the same source at the same version, so the API and
the bytes are the same. What differs is how you inspect the install. With Flet's package
compilation on, the mobile default, `cbor2/__init__.py` ships as bytecode with no source beside
it, and a native extension may report no `__file__` at all on Android — so identify the
implementation by `cbor2.dumps.__module__`, never by a file path.

## Things to know

- **There is one implementation and it is native.** `cbor2.dumps` is a builtin whose
  `__module__` is `cbor2._cbor2`, on desktop and on device. The 6.x line has no pure-Python
  fallback, so there is no slow path to land on by accident and no build flag to check: a broken
  install fails outright at `import cbor2`.

- **Tuples come back as lists, and a tag's payload comes back immutable.** CBOR has one array
  type, so `loads(dumps((1, 2)))` is a list, and a `frozenset` decodes as a `set`. Inside a
  `CBORTag` it is the opposite: payloads decode immutably so they can be used as map keys, so
  `tag.value` is a tuple and a map nested in it an immutable mapping. The symptom is
  `AttributeError: 'tuple' object has no attribute 'append'` inside a `tag_hook`.

- **A naive datetime is refused, not guessed.** `dumps` raises
  `CBOREncodeError: naive datetime encountered and no default timezone has been set`. Attach a
  `tzinfo`, or pass `timezone=timezone.utc` to supply one for the whole document; upstream
  covers the choices under
  [date/time handling](https://cbor2.readthedocs.io/en/latest/usage.html#date-time-handling).

- **`Decimal("NaN")` and `Decimal("Infinity")` leave the Decimal domain.** They encode as CBOR
  floats and decode as `float` nan and inf. The infinity still compares equal to the `Decimal`
  it came from, so only a type check catches it; a NaN does not equal itself, so a document
  containing one never compares equal to what you encoded. Finite decimals are exact, stored as
  exponent and mantissa: `Decimal("19.99")` returns `Decimal("19.99")`.

- **Decoding untrusted bytes is guarded, but not completely.** Nesting is capped, with
  `CBORDecodeError: maximum container nesting depth (400) exceeded`, and `max_depth` moves the
  cap. A truncated document, or a header claiming a length the file does not contain, raises
  `CBORDecodeEOF` without allocating for it. But duplicate map keys are accepted by default and
  the last one wins, which RFC 8949 calls invalid — pass `allow_duplicate_keys=False` for input
  you did not write.

- **Use `canonical=True` for anything you hash, sign or compare byte for byte.** It sorts map
  keys and uses the shortest head for each value, as RFC 8949's deterministic encoding requires.
  Without it keys are written in insertion order, so two documents that are equal in Python can
  produce different bytes and different digests.

- **`string_referencing=True` is an extension to RFC 8949, not part of it.** The output uses
  tags 256 and 25, which a strict RFC 8949 decoder will not resolve. It is a good lever for a
  file this app writes and reads itself, and a bad one for a document that leaves the device.

## Build notes (maintainers)

### Recipe shape

The package is `setuptools-rust` plus PyO3, and every dependency crate is pure Rust, so there is
no native library to build first and no host tool to shim. The recipe is therefore the plain
Rust template with no patches, and CI's mobile Rust targets — added for earlier Rust recipes —
needed no change. If a bump ever requires a patch here, treat that as a signal that the upstream
build changed shape rather than as a line to add.

The recipe exists because 6.x is Rust-only: the 5.x line shipped a `py3-none-any` wheel a Flet
app could install anywhere, and 6.x ships none, so the current release is otherwise
uninstallable on device.

### Upgrade hazards

- 6.x replaced a C accelerator plus a pure-Python fallback with a single mandatory Rust
  extension. A future line that changes the build backend again is a redesign, not a bump.
- The 32-bit ARM slice is where a Rust bump breaks: a newly pulled crate that wants 64-bit
  atomics fails on `armeabi-v7a` with `E0432: unresolved import core::sync::atomic::AtomicU64`.
  Build all three Android ABIs and all three iOS slices before calling a bump clean.
- 6.x also changed the hook signatures from 5.x, to `tag_hook(tag, shareable)` and
  `object_hook(mapping, shareable)`. The sections above quote the current ones.

### Re-verification checklist

- **Tag coverage:** regenerate the automatic-tag list from the encoder rather than carrying it
  forward — it is this page's central claim, and a new tag is a silent addition.
- **Decoder defaults:** the 400-deep nesting cap, permissive duplicate keys and the immutable
  tag payload are all quoted above and all cheap to re-check.
- **Wheel shape:** one `_cbor2` extension beside `__init__.py`, `__init__.pyi`, `py.typed` and
  `tool.py`; a `py3-none-any` wheel reappearing upstream would remove this recipe's reason to
  exist.
- **Size:** re-measure compressed and unpacked from the built wheels; the figures above are
  decimal MB.

### Coverage gaps

The device tests cover import, a nested `dumps`/`loads` round trip, an RFC 8949 appendix-A
vector, `CBORTag` and the bignum path. They do not exercise the datetime, `Decimal`, `set` or
`UUID` tags, any of the hooks, `dump`/`load` against a real file, `canonical` or
`string_referencing` output, or the decoder's limits — everything this page says about those
came from desktop inspection.
