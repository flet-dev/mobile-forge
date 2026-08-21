# ormsgpack

[`ormsgpack`](https://github.com/ormsgpack/ormsgpack) is a
[MessagePack](https://msgpack.org/) serialiser written in Rust, derived from
[`orjson`](../orjson). It turns Python objects into a compact binary blob and back — on
mobile, what a cache file, an offline queue or a request body is made of.

The reason to reach for this one rather than [`msgpack`](../msgpack) is not the wire format —
the two write the same bytes. It is that `ormsgpack` packs a dataclass, a `datetime`, a
`date`, a `time`, a `UUID`, an `Enum` and (with a flag) a numpy array with no `default=`
hook, and packs everything two to three times faster. The cost is that those extra types
are converted, not preserved: a round trip through `packb`/`unpackb` returns msgpack's own
types, so a dataclass comes back a `dict` and a `UUID` comes back a `str`.

## Install

Add ormsgpack to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "ormsgpack",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`pack-bench`](examples/pack-bench) — packs the same records with both libraries, times
  each, and shows what eight different values return from a round trip.

## Usage in a Flet app

Two module-level functions do all the work.
[`packb`](https://ormsgpack.readthedocs.io/en/latest/api.html#ormsgpack.packb) returns
`bytes`;
[`unpackb`](https://ormsgpack.readthedocs.io/en/latest/api.html#ormsgpack.unpackb) accepts
`bytes`, `bytearray` or `memoryview` and rejects anything else — including a `str` — with
`ValueError: Input must be bytes, bytearray, memoryview`:

```python
import ormsgpack

blob = ormsgpack.packb({"id": 7, "tags": ["indoor", "spare"], "ok": True})
data = ormsgpack.unpackb(blob)
```

The two error names are aliases and not subclasses: `MsgpackEncodeError` *is* `TypeError`
and `MsgpackDecodeError` *is* `ValueError`, so `except ormsgpack.MsgpackEncodeError` also
swallows every unrelated `TypeError` in the block. Keep the `try` tight.

Truncation announces itself — every prefix of a test blob raised `ValueError: unexpected end
of file` — but corruption does not. MessagePack carries no checksum: of 400 single-bit flips
of one blob, roughly three quarters decoded with no error at all and returned wrong values.
Store a digest beside a cache file whose contents you need to trust.

### Storage

Cached blobs are ordinary binary files. Put what the user expects to keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
and open it in binary mode, because `packb` hands you `bytes`:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "readings.msgpack")
with open(path, "wb") as handle:
    handle.write(ormsgpack.packb(readings))
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything the app can rebuild and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch. A blob shipped with the app is an asset: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and read it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

[Client storage](https://flet.dev/docs/cookbook/client-storage) is the one place a blob
cannot go:
[`page.shared_preferences`](https://flet.dev/docs/services/sharedpreferences/) takes `str`,
`int`, `float`, `bool` and `list[str]`, and hands `packb` output back as
`ValueError: Unsupported value type: <class 'bytes'>`. Base64 it into a `str` if the value
genuinely belongs there — a third more bytes than the blob — or write a file instead.

Reading a large file back, `unpackb` taking a `memoryview` is worth using: an
[`mmap`](https://docs.python.org/3/library/mmap.html) wrapped in `memoryview(mm)` decodes
without first copying the file into `bytes`. The `mmap` itself is not accepted — wrap it.

For scale, on desktop: 5,000 records of the example's shape packed to about 479 KB against
731 KB for `json.dumps`, or 651 KB with compact separators — 34% and 26% smaller.

### Threading

`packb` and `unpackb` hold the GIL for their whole run, so threads buy nothing: splitting a
fixed number of calls over two of them takes the same wall time as one (0.99× on desktop,
against 1.98× for a GIL-releasing `hashlib.sha256`). Moving a pack into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) keeps it
out of the event handler but does not stop it competing with the UI thread — the lever for a
janky frame is a smaller payload or fewer records per call, not another thread.

Concurrency itself is safe: there is no shared decoder state, and six threads running 60
round trips each over a 50,000-element list finished with no error and identical results.
No application-wide lock is needed. When work does go to a background thread, catch
exceptions inside the worker and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Choosing between this and msgpack

The output is identical. Every payload shape tried — records, floats, ints, strings, CJK
text, 1 MB blobs, booleans, `None`, deep nesting and each container-length and integer-width
boundary in the format — produced byte-for-byte the same blob from both libraries, so
switching one for the other leaves existing files and existing peers readable.

What differs is the clock and the API. Desktop measurements (macOS arm64, CPython 3.12, a
5,000-record list of dicts, best of seven runs):

| | ormsgpack | msgpack |
| --- | ---: | ---: |
| pack | 0.50 ms | 1.45 ms |
| unpack | 1.51 ms | 2.24 ms |

Packing held at 2.1–3.3× across every shape tried. Unpacking did not: it ranged from 1.5×
down to **0.7×**, msgpack decoding faster on flat lists of short strings, booleans or
`None`. Unpacking speed alone is not a reason to switch, and a phone produces its own
numbers — the [`pack-bench`](examples/pack-bench) example prints them.

The API differs in the shape of the options: msgpack takes keyword arguments per call
(`datetime=True`, `strict_map_key=False`), ormsgpack one `option=` integer OR-ed from module
constants, plus a `default=` callback for anything it does not know. Those constants are not
interchangeable between the two calls — see the `Invalid opts` bullet below.

The types are where the choice is actually made:

| Value | `ormsgpack` | `msgpack` |
| --- | --- | --- |
| dataclass instance | packs as a map, returns a `dict` | `TypeError: can not serialize 'Reading' object` |
| aware `datetime` | RFC 3339 string, 34 bytes; `OPT_DATETIME_AS_TIMESTAMP_EXT` writes the 10-byte timestamp extension | `datetime=True` writes the timestamp extension; `timestamp=3` returns a `datetime` |
| naive `datetime` | string; the extension additionally needs `OPT_NAIVE_UTC` | `ValueError: can not serialize 'datetime.datetime' object where tzinfo=None` |
| `date`, `time` | ISO string; no extension form | needs `default=` |
| `UUID` | 36-character string | `TypeError: can not serialize 'UUID' object` |
| `Enum` | the member's value | needs `default=` |
| non-string dict keys | `OPT_NON_STR_KEYS`, on **both** calls | `strict_map_key=False` on `unpackb` |
| `tuple` | list; as a dict key it stays a tuple | list, or `use_list=False` for tuples everywhere |
| numpy array | `OPT_SERIALIZE_NUMPY` | needs `default=` |

The two agree on the wire for timestamps: `OPT_DATETIME_AS_TIMESTAMP_EXT` writes exactly
what `msgpack.packb(..., datetime=True)` writes, and each reads the other's.

### App size

Approximately 0.18–0.22 MB compressed and 0.42–0.48 MB unpacked per architecture, nearly
all of it the single Rust extension; Android is the larger end, iOS the smaller. At that
size the usual levers — an app bundle, split APKs, narrowing
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) —
are not worth pulling for this package alone. The size question it raises is the size of
the blobs it writes into app storage, which grows with your data, not with the wheel.

### Other considerations

A desktop `flet run` uses PyPI's own wheel, built from the same Rust source and — the crate
declares no cargo features — with the same code compiled in, so the option flags, the wire
format and the type conversions do not vary by platform and a schema worked out on desktop
holds on device. The timings do not transfer: every ratio on this page is a desktop
measurement, and the example exists so you can read the device's own.

Two flags reach outside the package. `OPT_SERIALIZE_NUMPY` serialises numpy arrays and
`OPT_SERIALIZE_PYDANTIC` pydantic models, so an app that enables either lists that package
among its own dependencies.

## Things to know

- **A round trip is not a type round trip.** Nothing in the bytes records what the extra
  types were: a dataclass returns a `dict`, a `UUID` and a `datetime` a `str`, an `Enum` its
  value, a `tuple` a `list`. The decoder has to know the schema. The one exception is a
  `tuple` used as a dict key, which stays a tuple because a key has to stay hashable.

- **`OPT_NON_STR_KEYS` is a flag on both calls.** Packing `{1: "a"}` without it raises
  `TypeError: Dict key must be str`; packing with it and unpacking without it raises
  `ValueError: invalid type FixPos(1)` on bytes you wrote seconds earlier. It rejects
  `OPT_SORT_KEYS` in the same call, and it does not preserve every key type: `int`, `float`,
  `bool`, `None`, `bytes` and `tuple` keys survive, while `date`, `time`, `datetime` and
  `UUID` keys are stringified — `{date(2026, 8, 21): "cell"}` reads back as
  `{'2026-08-21': 'cell'}`.

- **`unpackb` accepts exactly two flags** — `OPT_NON_STR_KEYS` and
  `OPT_DATETIME_AS_TIMESTAMP_EXT`; every other constant raises `ValueError: Invalid opts`.
  So one shared `option` constant breaks the moment a packing-only flag joins it. Mask it:
  `option & (OPT_NON_STR_KEYS | OPT_DATETIME_AS_TIMESTAMP_EXT)`.

- **The timestamp extension trades the offset for nine tenths of the bytes.** With
  [`OPT_DATETIME_AS_TIMESTAMP_EXT`](https://ormsgpack.readthedocs.io/en/latest/api.html#ormsgpack.OPT_DATETIME_AS_TIMESTAMP_EXT)
  on both calls, `18:00:45.123456+05:30` packs into 10 bytes instead of 34 and returns a real
  `datetime` with the microseconds intact — but as `12:30:45.123456+00:00`, because the
  extension stores an instant. A *naive* datetime has no instant and silently falls back to
  the string form until
  [`OPT_NAIVE_UTC`](https://ormsgpack.readthedocs.io/en/latest/api.html#ormsgpack.OPT_NAIVE_UTC)
  declares that naive means UTC. Storing local wall-clock time? Keep the string form.

- **Any extension type needs an `ext_hook` to read.** Unpacking one without it raises
  `ValueError: ext_hook missing` — including
  [`Ext`](https://ormsgpack.readthedocs.io/en/latest/api.html#ormsgpack.Ext) objects
  ormsgpack packed itself, and a `msgpack.ExtType` from a peer. Pass
  `ext_hook=lambda tag, data: ...` on every `unpackb` that might meet one.

- **Nesting is capped tighter on the way out than on the way in.** Packing stops at 255
  nested containers (the 256th raises `TypeError: Recursion limit reached`; a recursive
  `default=` raises `Recursion limit for default hook reached`), unpacking at 1,023. A
  document from elsewhere can therefore be readable and then unwritable — and msgpack packs
  to 512, so a peer using it can write one that ormsgpack reads but cannot write back.

- **There is no incremental reader or writer.** Objects are packed and unpacked whole, so a
  large cache file is fully resident on both sides: budget memory for the biggest blob the
  app will ever write, not the average one. Where a stream is the requirement, msgpack's
  `Packer`/`Unpacker` are the tools that have it.

- **`OPT_SERIALIZE_NUMPY` saves the `.tolist()` call, not the bytes.** An array is written as
  nested msgpack arrays of numbers — identical output to `msgpack.packb(array.tolist())` —
  and comes back as lists, with shape and dtype gone; 200,000 `float64` values took
  1,800,005 bytes against 1,600,000 for `array.tobytes()`. For numeric bulk, pack
  `tobytes()` with the dtype and shape alongside it. Object-dtype arrays are refused with
  `TypeError: numpy array is not C contiguous`, whatever the actual layout.

## Build notes (maintainers)

### Recipe shape

A stock PyO3/maturin recipe: no patches, no `build.sh`, no host-build dependency, and no
source changes of any kind. Worth recording because that is unusual for a Rust recipe — in
particular the crate needs no `excluded_arches`, and `armeabi-v7a` builds and ships like the
rest, so nothing here depends on 64-bit atomics.

### Upgrade hazards

- The consumer sections above quote Rust-side error strings verbatim (`Invalid opts`,
  `invalid type FixPos(1)`, `Recursion limit reached`, `Dict key must be str`). These are not
  covered by any compatibility promise and can be reworded in a patch release.
- The set of flags `unpackb` accepts is a documented claim on this page — exactly two. A
  bump that widens or narrows it invalidates the masking advice.
- `MsgpackEncodeError` and `MsgpackDecodeError` are the builtins themselves today, not
  subclasses. Giving them their own classes would look source-compatible upstream and would
  quietly change what a caller's bare `except TypeError` catches.
- `Cargo.toml` currently declares no cargo features at all, which is what lets this page say
  a desktop schema holds on device. A bump that adds one, default-on or not, breaks that.
- Building from source needs Rust 1.81 or newer per upstream's installation notes; a bump can
  raise that floor and fail in the toolchain rather than in the code.

### Re-verification checklist

- **Byte identity with msgpack**, on every scalar type and at the format's length boundaries
  (15/16, 31/32, 255/256, 65535/65536). It is the page's central claim and the reason the
  recipe is worth having next to `msgpack` rather than instead of it.
- **Which options `unpackb` accepts**, by passing each constant and checking for
  `Invalid opts`.
- **Timestamp-extension interop both ways** against `msgpack.packb(..., datetime=True)` and
  `msgpack.unpackb(..., timestamp=3)`, including that the returned tzinfo is UTC.
- **Both nesting caps**, by bisecting pack and unpack separately; they differ by a factor of
  four and both are quoted above. Count containers, not wrapper levels, and check the two
  the same way — the numbers are one apart from the ones the source constants suggest.
  Bisect rather than spot-check: the unpack cap is a fixed count, unmoved by
  `sys.setrecursionlimit`.
- **That the error names are still aliases**, with `is TypeError` and `is ValueError`.
- **Non-string key behaviour**: which key types survive as themselves and which are
  stringified. The list in Things to know is exhaustive as measured, not as documented
  upstream.
- **GIL behaviour**, since the threading advice rests on the calls holding it throughout.
  Grep the built binaries for `PyEval_SaveThread` — absent in both at 1.12.2 — because that
  survives machine noise where a counting-thread ratio does not.
- **Sizes**, re-measured from the built wheels rather than scaled.

### Coverage gaps

The device test imports the module and round-trips one flat dict. Nothing on device
exercises an option flag, the dataclass, datetime or UUID conversions, non-string keys, the
`ext_hook` path, the depth limits, or the msgpack interop this page relies on — all of that
is desktop evidence, as are the timings and the byte-identity figures. No on-device
benchmark backs them beyond the example app.
